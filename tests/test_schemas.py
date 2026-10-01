"""Contract tests against the real JSON Schema library, including scope limits."""
from __future__ import annotations

from functools import lru_cache
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from referencing.exceptions import Unresolvable

from scripts.validate_json import (
    DIALECT, ROOT, SCHEMA_DIR, build_validator, json_pointer, load_json, load_registry,
)

NAMES = ("manifest", "analysis-request", "analysis", "selects", "story-plan", "edit-plan", "review")
EXAMPLES = ROOT / "examples" / "contracts"


def example(name):
    return load_json(EXAMPLES / f"{name}.json")


@lru_cache(maxsize=None)
def validator(name):
    return build_validator(SCHEMA_DIR / f"{name}.schema.json")


def nodes(value, path=()):
    if isinstance(value, dict):
        yield path, value
        for key, item in value.items():
            yield from nodes(item, (*path, key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from nodes(item, (*path, index))


def at(value, path):
    for key in path:
        value = value[key]
    return value


@pytest.mark.parametrize("path", sorted(SCHEMA_DIR.glob("*.schema.json")), ids=lambda p: p.name)
def test_schema_meta_validity_ids_and_refs(path):
    schema = load_json(path)
    assert schema["$schema"] == DIALECT
    assert schema["$id"].endswith("/2.0.0/" + path.name)
    Draft202012Validator.check_schema(schema)
    resolver = load_registry().resolver(base_uri=schema["$id"])
    for _, item in nodes(schema):
        if "$ref" in item:
            resolver.lookup(item["$ref"])


def test_no_open_typed_objects_in_contract_definitions():
    for path in SCHEMA_DIR.glob("*.schema.json"):
        for _, item in nodes(load_json(path)):
            if item.get("type") == "object":
                assert item.get("additionalProperties") is False, path


@pytest.mark.parametrize("name", NAMES)
def test_complete_positive_fixtures(name):
    validator(name).validate(example(name))


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("mutation", ["unknown-root", "wrong-version", "missing-job", "blank-job"])
def test_root_contract_rejections(name, mutation):
    data = example(name)
    if mutation == "unknown-root":
        data["accidental_field"] = "not allowed"
    elif mutation == "wrong-version":
        data["schema_version"] = "1.0.0"
    elif mutation == "missing-job":
        del data["job_id"]
    else:
        data["job_id"] = "  "
    assert not validator(name).is_valid(data)


NESTED_CASES = [
    (name, path)
    for name in NAMES
    for path, item in nodes(example(name))
    if path and path[-1] != "scores"
]


@pytest.mark.parametrize("name,path", NESTED_CASES)
def test_unknown_fields_rejected_in_nested_objects(name, path):
    data = example(name)
    at(data, path)["misspelled_field"] = True
    assert not validator(name).is_valid(data)


INVALID_VALUES = [
    ("manifest", ("sources",), []),
    ("manifest", ("sources", 0, "source_id"), ""),
    ("manifest", ("sources", 0, "source_id"), "src-001\n"),
    ("manifest", ("sources", 0, "path"), " \t"),
    ("manifest", ("sources", 0, "duration_ms"), -1),
    ("manifest", ("sources", 0, "fps_num"), None),
    ("manifest", ("sources", 0, "fps_den"), 0),
    ("manifest", ("sources", 0, "frame_count"), 0),
    ("manifest", ("sources", 0, "audio_sample_rate"), -48000),
    ("analysis-request", ("questions",), []),
    ("analysis-request", ("sources", 0, "ranges"), []),
    ("analysis-request", ("sources", 0, "ranges", 0, "start_ms"), 0.5),
    ("analysis-request", ("runner",), "gemini-cli"),
    ("analysis-request", ("cloud_upload_allowed",), "false"),
    ("analysis", ("segments", 0, "confidence"), 1.1),
    ("analysis", ("segments", 0, "evidence"), []),
    ("analysis", ("segments", 0, "audible_content"), None),
    ("analysis", ("segments", 1, "visible_content"), "  "),
    ("analysis", ("segments", 0, "start_ms"), -1),
    ("selects", ("items", 0, "evidence_refs"), []),
    ("selects", ("items", 0, "evidence_refs"), ["seg-001", "seg-001"]),
    ("selects", ("items", 0, "scores"), {"dialogue": 9}),
    ("selects", ("items", 0, "scores"), {"dialogue\n": 0.5}),
    ("selects", ("items", 0, "role"), "unknown"),
    ("selects", ("items", 0, "locked"), "false"),
    ("story-plan", ("chapters",), []),
    ("story-plan", ("thesis",), "  "),
    ("story-plan", ("chapters", 0, "select_ids"), []),
    ("story-plan", ("chapters", 0, "target_duration_ms"), -1),
    ("edit-plan", ("timeline_fps", "den"), 0),
    ("edit-plan", ("items",), []),
    ("edit-plan", ("items", 0, "audio_policy"), "SEPARATE"),
    ("edit-plan", ("items", 0, "audio_policy"), "UNKNOWN"),
    ("edit-plan", ("items", 0, "source_in_frame"), 1.25),
    ("edit-plan", ("items", 0, "source_out_frame"), 9007199254740992),
    ("review", ("edit_plan_sha256",), "not-a-hash"),
    ("review", ("edit_plan_sha256",), "0" * 64 + "\n"),
    ("review", ("reviewed_at",), "2026-02-30T10:00:00Z"),
    ("review", ("reviewed_at",), "2026-10-01T10:00:00"),
    ("review", ("issues",), []),
]


@pytest.mark.parametrize("name,path,value", INVALID_VALUES)
def test_invalid_scalar_and_container_values(name, path, value):
    data = example(name)
    at(data, path[:-1])[path[-1]] = value
    assert not validator(name).is_valid(data)


def test_explicit_unknown_metadata_is_valid_but_not_export_ready():
    data = example("manifest")
    data["sources"][0].update(duration_ms=None, fps_num=None, fps_den=None,
                              frame_count=None, cfr_status="UNKNOWN", audio_sample_rate=None)
    validator("manifest").validate(data)


def test_unknown_fps_must_be_a_complete_null_pair():
    data = example("manifest")
    data["sources"][0].update(fps_num=None, fps_den=1, cfr_status="UNKNOWN")
    assert not validator("manifest").is_valid(data)


def test_noninteger_nominal_frame_rate_is_a_rational_pair():
    data = example("edit-plan")
    data["timeline_fps"] = {"num": 30000, "den": 1001}
    validator("edit-plan").validate(data)


@pytest.mark.parametrize("name,field", [("analysis", "segments"), ("selects", "items")])
def test_no_findings_can_be_reported_without_fabrication(name, field):
    data = example(name)
    data[field] = []
    validator(name).validate(data)


def test_empty_chapter_requires_explicit_coverage_gap():
    data = example("story-plan")
    data["chapters"][0].update(select_ids=[], coverage_gaps=["No usable source coverage."])
    validator("story-plan").validate(data)


def test_unknown_role_is_allowed_for_review_not_selection():
    data = example("selects")
    data["items"][0].update(role="unknown", decision="REVIEW")
    validator("selects").validate(data)


def test_cloud_scope_requires_recorded_authorization_reference():
    data = example("analysis-request")
    data["cloud_upload_allowed"] = True
    assert not validator("analysis-request").is_valid(data)
    data["authorization_ref"] = "Synthetic authorization reference; not a real grant."
    validator("analysis-request").validate(data)
    data["cloud_upload_allowed"] = False
    assert not validator("analysis-request").is_valid(data)


def test_approval_requires_human_record_and_no_errors_or_changes():
    data = example("review")
    data.update(status="APPROVED", issues=[], required_changes=[])
    assert not validator("review").is_valid(data)
    data["reviewer_type"] = "HUMAN"
    validator("review").validate(data)  # Shape only; this is not authentic human consent.
    data["issues"] = [{"severity": "ERROR", "message": "Unresolved test problem."}]
    assert not validator("review").is_valid(data)
    data["issues"] = []
    data["required_changes"] = ["Outstanding change."]
    assert not validator("review").is_valid(data)


def test_changes_required_requires_a_specific_change():
    data = example("review")
    data.update(status="CHANGES_REQUIRED", issues=[], required_changes=[])
    assert not validator("review").is_valid(data)
    data["required_changes"] = ["Recheck the dialogue boundary."]
    validator("review").validate(data)


def test_fixture_hash_matches_exact_edit_plan_bytes():
    digest = hashlib.sha256((EXAMPLES / "edit-plan.json").read_bytes()).hexdigest()
    assert example("review")["edit_plan_sha256"] == digest


@pytest.mark.parametrize("boundary", ["reversed-range", "missing-source", "duplicate-id", "wrong-hash"])
def test_schema_does_not_claim_domain_integrity(boundary):
    """Passing schema validation must never be reported as export approval."""
    if boundary == "reversed-range":
        data = example("analysis")
        data["segments"][0].update(start_ms=5000, end_ms=1000)
        name = "analysis"
    elif boundary == "missing-source":
        data = example("selects")
        data["items"][0]["source_id"] = "not-in-the-manifest"
        name = "selects"
    elif boundary == "duplicate-id":
        data = example("manifest")
        data["sources"][1]["source_id"] = data["sources"][0]["source_id"]
        name = "manifest"
    else:
        data = example("review")
        data["edit_plan_sha256"] = "0" * 64
        name = "review"
    validator(name).validate(data)


def test_references_resolve_offline(monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("Validation attempted network access.")
    monkeypatch.setattr(socket, "socket", no_network)
    for name in NAMES:
        validator(name).validate(example(name))


def test_unknown_reference_fails_without_fetching(monkeypatch, tmp_path):
    schema = {"$schema": DIALECT, "$id": "urn:test:missing-ref", "$ref": "https://example.invalid/not-cached"}
    path = tmp_path / "bad.schema.json"
    path.write_text(json.dumps(schema))
    def no_network(*args, **kwargs):
        raise AssertionError("Network must remain disabled.")
    monkeypatch.setattr(socket, "socket", no_network)
    with pytest.raises(Unresolvable):
        build_validator(path, tmp_path).validate({})


def test_duplicate_schema_ids_fail(tmp_path):
    schema = {"$schema": DIALECT, "$id": "urn:test:duplicate", "type": "string"}
    for name in ("one", "two"):
        (tmp_path / f"{name}.schema.json").write_text(json.dumps(schema))
    with pytest.raises(ValueError, match="Duplicate schema"):
        load_registry(tmp_path)


def test_missing_format_dependency_is_not_silently_ignored(monkeypatch):
    monkeypatch.delitem(FormatChecker.checkers, "date-time")
    with pytest.raises(ValueError, match="format-nongpl"):
        build_validator(SCHEMA_DIR / "review.schema.json")


@pytest.mark.parametrize("text", ['{"a":1,"a":2}', '{"a":{"b":1,"b":2}}', 'NaN', 'Infinity', '-Infinity'])
def test_json_parser_rejects_ambiguous_or_nonjson_input(tmp_path, text):
    path = tmp_path / "input.json"
    path.write_text(text)
    with pytest.raises(ValueError):
        load_json(path)


def test_error_pointer_escapes_property_names_and_indices():
    assert json_pointer(["a/b", 0, "~tilde"]) == "/a~1b/0/~0tilde"


def cli(*args):
    return subprocess.run([sys.executable, str(ROOT / "scripts/validate_json.py"), *map(str, args)],
                          capture_output=True, text=True, timeout=30)


def test_cli_reports_schema_only_success():
    result = cli(SCHEMA_DIR / "analysis.schema.json", EXAMPLES / "analysis.json")
    assert result.returncode == 0
    assert "SCHEMA_VALID" in result.stdout and "not checked" in result.stdout


def test_cli_invalid_data_has_exit_one(tmp_path):
    path = tmp_path / "invalid.json"
    path.write_text('{"schema_version":"2.0.0"}')
    result = cli(SCHEMA_DIR / "analysis.schema.json", path)
    assert result.returncode == 1 and "SCHEMA_INVALID" in result.stderr


def test_cli_missing_input_has_exit_two(tmp_path):
    result = cli(SCHEMA_DIR / "analysis.schema.json", tmp_path / "missing.json")
    assert result.returncode == 2 and "INPUT_OR_SCHEMA_ERROR" in result.stderr


def test_cli_rejects_common_library_as_stage_schema():
    result = cli(SCHEMA_DIR / "common.schema.json", EXAMPLES / "analysis.json")
    assert result.returncode == 2


def test_cli_unresolved_ref_has_exit_two(tmp_path):
    schema = {"$schema": DIALECT, "$id": "urn:test:cli-ref", "$ref": "urn:test:does-not-exist"}
    path = tmp_path / "bad.schema.json"
    path.write_text(json.dumps(schema))
    data = tmp_path / "data.json"
    data.write_text('{}')
    result = cli(path, data, "--schema-dir", tmp_path)
    assert result.returncode == 2 and "Traceback" not in result.stderr


def test_cli_unregistered_schema_has_exit_two(tmp_path):
    schema = {"$schema": DIALECT, "$id": "urn:test:not-registered", "type": "object"}
    path = tmp_path / "foreign.schema.json"
    path.write_text(json.dumps(schema))
    result = cli(path, EXAMPLES / "analysis.json")
    assert result.returncode == 2 and "Traceback" not in result.stderr


def test_differing_content_under_existing_id_is_rejected(tmp_path):
    schema = load_json(SCHEMA_DIR / "analysis.schema.json")
    schema["description"] = "This is not the registered schema."
    path = tmp_path / "altered.schema.json"
    path.write_text(json.dumps(schema))
    with pytest.raises(ValueError, match="match a registered"):
        build_validator(path)


def test_invalid_metaschema_content_is_rejected(tmp_path):
    schema = {"$schema": DIALECT, "$id": "urn:test:bad-schema", "type": "bogus-type"}
    path = tmp_path / "bad.schema.json"
    path.write_text(json.dumps(schema))
    result = cli(path, EXAMPLES / "analysis.json", "--schema-dir", tmp_path)
    assert result.returncode == 2 and "Traceback" not in result.stderr
