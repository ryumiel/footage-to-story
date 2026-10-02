"""Check schema-valid document relationships, not media truth or export readiness."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any

from jsonschema.exceptions import SchemaError
from referencing.exceptions import Unresolvable

try:
    from .validate_json import ROOT, build_validator, json_pointer, load_json
except ImportError:
    from validate_json import ROOT, build_validator, json_pointer, load_json

STAGES = ("manifest", "analysis-request", "analysis", "selects", "story-plan", "edit-plan", "review")
DEPENDENCIES = {"analysis": "analysis-request", "selects": "analysis",
                "story-plan": "selects", "review": "edit-plan"}


@dataclass(frozen=True)
class IntegrityIssue:
    document: str
    path: str
    code: str
    message: str


def covers(start: int, end: int, intervals: list[tuple[int, int]]) -> bool:
    """Check complete half-open coverage, allowing adjacent/overlapping ranges."""
    cursor = start
    for lower, upper in sorted(intervals):
        if lower >= upper or upper <= cursor:
            continue
        if lower > cursor:
            return False
        cursor = max(cursor, upper)
        if cursor >= end:
            return True
    return False


def check_documents(documents: dict[str, Any]) -> list[IntegrityIssue]:
    """Validate immutable caller documents, then compare explicit relationships.

    Missing upstream documents fail; omitted independent branches are not checked.
    Unknown declared bounds fail only when a range requires that bound.
    """
    unknown = set(documents) - set(STAGES)
    if unknown:
        raise ValueError(f"Unknown document stages: {', '.join(sorted(unknown))}")
    issues: list[IntegrityIssue] = []

    def issue(stage: str, path: str, code: str, message: str) -> None:
        issues.append(IntegrityIssue(stage, path, code, message))

    if "manifest" not in documents:
        return [IntegrityIssue("manifest", "", "MISSING_DOCUMENT", "A manifest is required")]
    # Delegate all shape/type/keyword validation to the committed schemas.
    for stage in STAGES:
        if stage not in documents:
            continue
        if stage == "manifest":
            version = documents[stage].get("schema_version") if isinstance(documents[stage], dict) else None
            if version not in ("2.0.0", "3.0.0"):
                issue(stage, "/schema_version", "SCHEMA_INVALID", "Unsupported manifest schema version")
                continue
            schema_path = ROOT / f"schemas/{version}/manifest.schema.json"
            validator = build_validator(schema_path, ROOT / "schemas")
        else:
            validator = build_validator(ROOT / f"schemas/2.0.0/{stage}.schema.json")
        errors = sorted(validator.iter_errors(documents[stage]),
                        key=lambda error: (json_pointer(error.absolute_path), error.message))
        for error in errors:
            issue(stage, json_pointer(error.absolute_path), "SCHEMA_INVALID", error.message)
    if issues:
        return issues

    for stage, dependency in DEPENDENCIES.items():
        if stage in documents and dependency not in documents:
            issue(stage, "", "MISSING_DOCUMENT", f"{stage} requires {dependency}")
    if "edit-plan" in documents and "selects" not in documents:
        for number, item in enumerate(documents["edit-plan"]["items"]):
            if item.get("select_ref") is not None:
                issue("edit-plan", f"/items/{number}/select_ref", "MISSING_DOCUMENT",
                      "A non-null select_ref requires selects and its upstream documents")
    if issues:
        return issues

    job = documents["manifest"]["job_id"]
    for stage in STAGES:
        if stage in documents and documents[stage]["job_id"] != job:
            issue(stage, "/job_id", "JOB_MISMATCH", "Job differs from the manifest")

    def index(stage: str, array: str, key: str) -> dict:
        result = {}
        for number, item in enumerate(documents.get(stage, {}).get(array, [])):
            value = item[key]
            if value in result:
                issue(stage, f"/{array}/{number}/{key}", "DUPLICATE_ID", f"Duplicate {key}: {value}")
            else:
                result[value] = item
        return result

    sources = index("manifest", "sources", "source_id")
    scope = index("analysis-request", "sources", "source_id")
    segments = index("analysis", "segments", "segment_id")
    selects = index("selects", "items", "select_id")
    index("story-plan", "chapters", "chapter_id")
    edits = index("edit-plan", "items", "edit_id")

    def source_for(stage: str, path: str, source_id: str) -> dict | None:
        if source_id not in sources:
            issue(stage, path + "/source_id", "MISSING_SOURCE", f"Unknown source: {source_id}")
            return None
        return sources[source_id]

    def ordered(stage: str, path: str, start: int, end: int) -> bool:
        if start >= end:
            issue(stage, path, "RANGE_ORDER", "OUT must be greater than IN")
            return False
        return True

    def bounded(stage: str, path: str, end: int, source: dict | None, field: str) -> None:
        if source is None:
            return
        limit = source[field]
        if limit is None:
            issue(stage, path, "UNKNOWN_BOUND", f"Cannot check range: manifest {field} is unknown")
        elif end > limit:
            issue(stage, path, "SOURCE_BOUND", f"OUT exceeds declared manifest {field}: {limit}")

    for number, entry in enumerate(documents.get("analysis-request", {}).get("sources", [])):
        path = f"/sources/{number}"
        source = source_for("analysis-request", path, entry["source_id"])
        for position, interval in enumerate(entry["ranges"]):
            range_path = f"{path}/ranges/{position}"
            if ordered("analysis-request", range_path, interval["start_ms"], interval["end_ms"]):
                bounded("analysis-request", range_path, interval["end_ms"], source, "duration_ms")

    if "analysis" in documents and documents["analysis"]["request_id"] != documents["analysis-request"]["request_id"]:
        issue("analysis", "/request_id", "REQUEST_MISMATCH", "Analysis refers to a different request")

    for stage, array in (("analysis", "segments"), ("selects", "items")):
        for number, item in enumerate(documents.get(stage, {}).get(array, [])):
            path = f"/{array}/{number}"
            source = source_for(stage, path, item["source_id"])
            start, end = item["start_ms"], item["end_ms"]
            if ordered(stage, path, start, end):
                bounded(stage, path, end, source, "duration_ms")
                permitted = [(r["start_ms"], r["end_ms"]) for r in scope.get(item["source_id"], {}).get("ranges", [])]
                if not covers(start, end, permitted):
                    issue(stage, path, "OUTSIDE_REQUEST", "Range is not fully covered by the declared request scope")
            if stage == "selects":
                evidence = []
                for position, ref in enumerate(item["evidence_refs"]):
                    ref_path = f"{path}/evidence_refs/{position}"
                    segment = segments.get(ref)
                    if segment is None:
                        issue(stage, ref_path, "MISSING_EVIDENCE", f"Unknown segment: {ref}")
                    elif segment["source_id"] != item["source_id"]:
                        issue(stage, ref_path, "SOURCE_MISMATCH", "Evidence segment belongs to a different source")
                    else:
                        evidence.append((segment["start_ms"], segment["end_ms"]))
                if start < end and not covers(start, end, evidence):
                    issue(stage, path + "/evidence_refs", "EVIDENCE_GAP", "Referenced observations do not cover the whole select interval")

    def selected_ref(stage: str, path: str, ref: str) -> dict | None:
        select = selects.get(ref)
        if select is None:
            issue(stage, path, "MISSING_SELECT", f"Unknown select: {ref}")
        elif select["decision"] != "SELECT":
            issue(stage, path, "UNSELECTED_REFERENCE", "Story/edit references an item not marked SELECT")
        return select

    for number, chapter in enumerate(documents.get("story-plan", {}).get("chapters", [])):
        for position, ref in enumerate(chapter["select_ids"]):
            selected_ref("story-plan", f"/chapters/{number}/select_ids/{position}", ref)

    for number, item in enumerate(documents.get("edit-plan", {}).get("items", [])):
        path = f"/items/{number}"
        source = source_for("edit-plan", path, item["source_id"])
        if ordered("edit-plan", path, item["source_in_frame"], item["source_out_frame"]):
            bounded("edit-plan", path, item["source_out_frame"], source, "frame_count")
        if item.get("select_ref") is not None:
            select = selected_ref("edit-plan", path + "/select_ref", item["select_ref"])
            if select is not None and select["source_id"] != item["source_id"]:
                issue("edit-plan", path + "/select_ref", "SOURCE_MISMATCH", "Referenced select belongs to a different source")

    if "review" in documents:
        review = documents["review"]
        if review["edit_plan_revision"] != documents["edit-plan"]["revision"]:
            issue("review", "/edit_plan_revision", "REVISION_MISMATCH", "Review refers to a different plan revision")
        for number, entry in enumerate(review["issues"]):
            if entry.get("edit_id") is not None and entry["edit_id"] not in edits:
                issue("review", f"/issues/{number}/edit_id", "MISSING_EDIT", f"Unknown edit: {entry['edit_id']}")
    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for stage in STAGES:
        parser.add_argument(f"--{stage}", type=Path, required=stage == "manifest")
    args = parser.parse_args(argv)
    try:
        documents = {stage: load_json(path) for stage in STAGES
                     if (path := getattr(args, stage.replace("-", "_"))) is not None}
        issues = check_documents(documents)
    except (OSError, ValueError, SchemaError, Unresolvable) as exc:
        print(f"INPUT_OR_SCHEMA_ERROR: {exc}", file=sys.stderr)
        return 2
    for entry in issues:
        print(f"INTEGRITY_INVALID {entry.document}{entry.path or '/'} [{entry.code}]: {entry.message}", file=sys.stderr)
    if issues:
        return 1
    print("DOCUMENT_INTEGRITY_VALID (provided documents and declared bounds only)")
    print("Media/timing, permission authenticity, approval digest/authenticity, prior locks, and export NOT_CHECKED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
