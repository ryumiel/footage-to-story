"""Synthetic document relationships; no real media, approval, or export."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.check_integrity import STAGES, check_documents, covers, main
from scripts.validate_json import ROOT, build_validator, load_json


@pytest.fixture
def bundle():
    return {stage: load_json(ROOT / f"examples/contracts/{stage}.json") for stage in STAGES}


def codes(bundle):
    return {issue.code for issue in check_documents(bundle)}


def test_complete_synthetic_bundle_passes_without_mutation(bundle):
    before = deepcopy(bundle)
    assert check_documents(bundle) == []
    assert bundle == before


def test_manifest_only_and_manual_non_ai_edit(bundle):
    assert check_documents({"manifest": bundle["manifest"]}) == []
    plan = bundle["edit-plan"]
    for item in plan["items"]:
        item.pop("select_ref")
    assert check_documents({"manifest": bundle["manifest"], "edit-plan": plan}) == []
    for item in plan["items"]:
        item["select_ref"] = None
    assert check_documents({"manifest": bundle["manifest"], "edit-plan": plan}) == []


@pytest.mark.parametrize("stage,array,key", [
    ("manifest", "sources", "source_id"),
    ("analysis-request", "sources", "source_id"),
    ("analysis", "segments", "segment_id"),
    ("selects", "items", "select_id"),
    ("story-plan", "chapters", "chapter_id"),
    ("edit-plan", "items", "edit_id"),
])
def test_duplicate_identifiers_are_schema_valid_but_fail_integrity(bundle, stage, array, key):
    bundle[stage][array].append(deepcopy(bundle[stage][array][0]))
    build_validator(ROOT / f"schemas/2.0.0/{stage}.schema.json").validate(bundle[stage])
    failures = check_documents(bundle)
    assert any(f.code == "DUPLICATE_ID" and f.path.endswith("/" + key) for f in failures)


@pytest.mark.parametrize("stage", STAGES[1:])
def test_every_document_must_match_manifest_job(bundle, stage):
    bundle[stage]["job_id"] = "other-synthetic-job"
    assert "JOB_MISMATCH" in codes(bundle)


@pytest.mark.parametrize("stage,array", [("analysis-request", "sources"), ("analysis", "segments"),
                                        ("selects", "items"), ("edit-plan", "items")])
def test_unknown_source_references_fail(bundle, stage, array):
    bundle[stage][array][0]["source_id"] = "missing-source"
    assert "MISSING_SOURCE" in codes(bundle)


@pytest.mark.parametrize("stage", ["analysis-request", "analysis", "selects", "edit-plan"])
@pytest.mark.parametrize("empty", [False, True])
def test_range_ordering_rejects_schema_valid_empty_or_reversed_intervals(bundle, stage, empty):
    if stage == "analysis-request":
        item = bundle[stage]["sources"][0]["ranges"][0]
    else:
        item = bundle[stage]["segments" if stage == "analysis" else "items"][0]
    start, end = ("source_in_frame", "source_out_frame") if stage == "edit-plan" else ("start_ms", "end_ms")
    item[start], item[end] = 50, 50 if empty else 1
    build_validator(ROOT / f"schemas/2.0.0/{stage}.schema.json").validate(bundle[stage])
    assert "RANGE_ORDER" in codes(bundle)


@pytest.mark.parametrize("stage", ["analysis-request", "analysis", "selects", "edit-plan"])
def test_outside_declared_source_bounds_fails(bundle, stage):
    if stage == "analysis-request":
        bundle[stage]["sources"][0]["ranges"][0]["end_ms"] = 10001
    else:
        item = bundle[stage]["segments" if stage == "analysis" else "items"][0]
        item["source_out_frame" if stage == "edit-plan" else "end_ms"] = 251 if stage == "edit-plan" else 10001
    assert "SOURCE_BOUND" in codes(bundle)


@pytest.mark.parametrize("field", ["duration_ms", "frame_count"])
def test_unknown_bounds_block_range_checks_but_not_inventory(bundle, field):
    bundle["manifest"]["sources"][0][field] = None
    assert "UNKNOWN_BOUND" in codes(bundle)
    assert check_documents({"manifest": bundle["manifest"]}) == []


def test_request_identity_must_match(bundle):
    bundle["analysis"]["request_id"] = "other-request"
    assert "REQUEST_MISMATCH" in codes(bundle)


def test_adjacent_request_intervals_provide_complete_scope(bundle):
    bundle["analysis-request"]["sources"][0]["ranges"] = [
        {"start_ms": 3000, "end_ms": 5000}, {"start_ms": 1000, "end_ms": 3000}]
    assert check_documents(bundle) == []


def test_gap_in_request_is_not_authorized_by_its_outer_envelope(bundle):
    bundle["analysis-request"]["sources"][0]["ranges"] = [
        {"start_ms": 1000, "end_ms": 2999}, {"start_ms": 3000, "end_ms": 5000}]
    assert "OUTSIDE_REQUEST" in codes(bundle)


def test_source_not_in_request_fails_even_when_in_manifest(bundle):
    bundle["analysis-request"]["sources"].pop(0)
    assert "OUTSIDE_REQUEST" in codes(bundle)


@pytest.mark.parametrize("case,expected", [("missing", "MISSING_EVIDENCE"),
                                          ("other-source", "SOURCE_MISMATCH"),
                                          ("partial", "EVIDENCE_GAP")])
def test_evidence_links_and_full_interval_coverage(bundle, case, expected):
    item = bundle["selects"]["items"][0]
    if case == "missing":
        item["evidence_refs"] = ["missing-segment"]
    elif case == "other-source":
        item["evidence_refs"] = ["seg-002"]
    else:
        bundle["analysis"]["segments"][0]["end_ms"] = 4999
    assert expected in codes(bundle)


def test_adjacent_evidence_can_cover_a_select_without_invented_segments(bundle):
    segment = bundle["analysis"]["segments"][0]
    second = deepcopy(segment)
    segment["end_ms"] = 3000
    second.update(segment_id="seg-synthetic-extra", start_ms=3000)
    bundle["analysis"]["segments"].append(second)
    bundle["selects"]["items"][0]["evidence_refs"].append(second["segment_id"])
    assert check_documents(bundle) == []
    second["start_ms"] = 3001
    assert "EVIDENCE_GAP" in codes(bundle)


@pytest.mark.parametrize("stage", ["story-plan", "edit-plan"])
@pytest.mark.parametrize("case", ["missing", "REVIEW", "REJECT"])
def test_story_and_edit_require_selected_existing_refs(bundle, stage, case):
    if case == "missing":
        if stage == "story-plan":
            bundle[stage]["chapters"][0]["select_ids"][0] = "missing-select"
        else:
            bundle[stage]["items"][0]["select_ref"] = "missing-select"
    else:
        bundle["selects"]["items"][0]["decision"] = case
    assert ("MISSING_SELECT" if case == "missing" else "UNSELECTED_REFERENCE") in codes(bundle)


def test_edit_select_reference_must_match_source(bundle):
    bundle["edit-plan"]["items"][0]["select_ref"] = "sel-002"
    assert "SOURCE_MISMATCH" in codes(bundle)


def test_review_revision_and_issue_edit_links(bundle):
    bundle["review"]["edit_plan_revision"] = "other-revision"
    bundle["review"]["issues"].append({"severity": "WARN", "message": "Synthetic issue", "edit_id": "missing-edit"})
    assert {"REVISION_MISMATCH", "MISSING_EDIT"} <= codes(bundle)


def test_shape_errors_stop_domain_checks_and_unknown_fields_are_not_repaired(bundle):
    bundle["analysis"]["unexpected"] = "synthetic bad field"
    bundle["edit-plan"]["items"][0].pop("source_out_frame")
    failures = check_documents(bundle)
    assert failures and all(f.code == "SCHEMA_INVALID" for f in failures)
    assert "unexpected" in bundle["analysis"]


@pytest.mark.parametrize("stage,dependency", [("analysis", "analysis-request"), ("selects", "analysis"),
                                             ("story-plan", "selects"), ("review", "edit-plan")])
def test_missing_upstream_documents_fail(bundle, stage, dependency):
    bundle.pop(dependency)
    assert "MISSING_DOCUMENT" in codes(bundle)


def test_referenced_selects_cannot_be_omitted(bundle):
    assert "MISSING_DOCUMENT" in codes({"manifest": bundle["manifest"], "edit-plan": bundle["edit-plan"]})
    assert check_documents({})[0].code == "MISSING_DOCUMENT"
    with pytest.raises(ValueError, match="Unknown document"):
        check_documents({"manifest": bundle["manifest"], "invented-stage": {}})


def test_pending_gates_are_not_silently_implemented(bundle):
    """A relationship pass must not be presented as media/approval verification."""
    bundle["review"]["edit_plan_sha256"] = "0" * 64
    bundle["edit-plan"]["items"][1]["timeline_in_frame"] = 999
    bundle["manifest"]["sources"][0].update(cfr_status="UNKNOWN", fps_num=None, fps_den=None)
    assert check_documents(bundle) == []


@pytest.mark.parametrize("start,end,intervals,expected", [
    (0, 10, [(0, 5), (5, 10)], True),
    (0, 10, [(0, 7), (3, 10)], True),
    (0, 10, [(0, 5), (6, 10)], False),
    (1, 5, [(0, 1), (1, 5)], True),
    (1, 5, [(0, 1)], False),
    (1, 5, [(5, 1)], False),
])
def test_half_open_union_coverage(start, end, intervals, expected):
    assert covers(start, end, intervals) is expected


def cli_args(paths):
    return [argument for stage, path in paths.items() for argument in ("--" + stage, str(path))]


def test_real_cli_pass_is_explicitly_scoped():
    args = {stage: ROOT / f"examples/contracts/{stage}.json" for stage in STAGES}
    result = subprocess.run([sys.executable, str(ROOT / "scripts/check_integrity.py"), *cli_args(args)],
                            text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "DOCUMENT_INTEGRITY_VALID" in result.stdout
    assert "approval digest/authenticity" in result.stdout and "NOT_CHECKED" in result.stdout


def test_cli_invalid_bundle_returns_one_with_pointer(tmp_path, bundle, capsys):
    bundle["manifest"]["sources"][1]["source_id"] = "src-001"
    path = tmp_path / "synthetic-manifest.json"
    path.write_text(json.dumps(bundle["manifest"]), encoding="utf-8")
    assert main(["--manifest", str(path)]) == 1
    stderr = capsys.readouterr().err
    assert "manifest/sources/1/source_id [DUPLICATE_ID]" in stderr


@pytest.mark.parametrize("text", ['{"job_id":"a","job_id":"b"}', "NaN", "{"])
def test_cli_malformed_json_returns_two(tmp_path, text, capsys):
    path = tmp_path / "synthetic-invalid.json"
    path.write_text(text, encoding="utf-8")
    assert main(["--manifest", str(path)]) == 2
    assert "INPUT_OR_SCHEMA_ERROR" in capsys.readouterr().err


def test_cli_missing_path_returns_two(tmp_path):
    assert main(["--manifest", str(tmp_path / "missing.json")]) == 2


def test_cli_schema_invalid_returns_one(tmp_path, capsys):
    path = tmp_path / "synthetic-invalid.json"
    path.write_text("{}", encoding="utf-8")
    assert main(["--manifest", str(path)]) == 1
    assert "[SCHEMA_INVALID]" in capsys.readouterr().err
