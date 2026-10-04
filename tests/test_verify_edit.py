"""Synthetic calculations and live generated-media sequential edit checks."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from scripts import verify_edit as ve
from scripts.probe_manifest import build_manifest, file_signature
from scripts.validate_json import ROOT, load_json


@pytest.fixture
def documents():
    return {stage: load_json(ROOT / f"examples/contracts/{stage}.json") for stage in ve.STAGES}


@pytest.fixture
def media(documents):
    return {"job_id": documents["manifest"]["job_id"], "status": "PASS", "sources": [
        {"source_id": source["source_id"], "status": "PASS", "path": source["path"],
         "video": {"cfr_status": "CFR", "fps": {"num": 25, "den": 1},
                   "decoded_frame_count": source["frame_count"]},
         "audio": {"sample_rate": 48000, "channels": 2,
                   "timing": {"status": "PASS", "sample_rate": 48000,
                              "sample_count": 480000, "issues": []}}}
        for source in documents["manifest"]["sources"]]}


def issue_codes(report):
    return {entry["code"] for entry in report["issues"]}


def test_complete_bundle_maps_exact_sequential_cuts(documents, media):
    before = deepcopy(documents), deepcopy(media)
    report = ve.analyze_edit(documents, media)
    assert report["status"] == "PASS"
    assert report["timeline_frame_count"] == 175
    assert report["timeline_duration_seconds"] == {"num": 7, "den": 1}
    assert report["items"][0]["timeline_out_frame"] == 100
    assert report["items"][1]["timeline_out_frame"] == 175
    assert "compressed-audio priming/resampling" in report["not_checked"]
    assert (documents, media) == before


def manual(documents):
    result = {stage: deepcopy(documents[stage]) for stage in ("manifest", "edit-plan")}
    for item in result["edit-plan"]["items"]:
        item.pop("select_ref", None)
    return result


def test_manual_branch_needs_no_editorial_artifacts(documents, media):
    assert ve.analyze_edit(manual(documents), media)["status"] == "PASS"


@pytest.mark.parametrize("number,start,expected", [(0, 1, "TIMELINE_GAP"),
                                                  (1, 101, "TIMELINE_GAP"),
                                                  (1, 99, "TIMELINE_OVERLAP")])
def test_first_frame_and_adjacent_continuity(documents, media, number, start, expected):
    documents["edit-plan"]["items"][number]["timeline_in_frame"] = start
    report = ve.analyze_edit(documents, media)
    assert expected in issue_codes(report)
    assert report["timeline_frame_count"] is None


def test_array_order_is_not_silently_sorted(documents, media):
    documents["edit-plan"]["items"].reverse()
    assert {"TIMELINE_GAP", "TIMELINE_OVERLAP"} <= issue_codes(ve.analyze_edit(documents, media))


def test_decoded_bounds_are_authoritative_after_declared_bound_checks(documents, media):
    media["sources"][0]["video"]["decoded_frame_count"] = 124
    assert "DECODED_SOURCE_BOUND" in issue_codes(ve.analyze_edit(documents, media))
    media["sources"][0]["video"]["decoded_frame_count"] = 125
    assert ve.analyze_edit(documents, media)["status"] == "PASS"


@pytest.mark.parametrize("case,expected", [("failed-media", "MEDIA_SCAN_FAILED"),
                                         ("missing-source", "SOURCE_SCAN_FAILED"),
                                         ("failed-source", "SOURCE_SCAN_FAILED"),
                                         ("audio-only", "VIDEO_REQUIRED"),
                                         ("vfr", "CFR_REQUIRED"),
                                         ("unknown-fps", "CFR_REQUIRED"),
                                         ("other-job", "MEDIA_JOB_MISMATCH")])
def test_required_fresh_scan_facts(documents, media, case, expected):
    if case == "failed-media":
        media["status"] = "FAIL"
    elif case == "missing-source":
        media["sources"].pop(0)
    elif case == "failed-source":
        media["sources"][0]["status"] = "FAIL"
    elif case == "audio-only":
        media["sources"][0]["video"] = None
    elif case == "vfr":
        media["sources"][0]["video"]["cfr_status"] = "VFR"
    elif case == "unknown-fps":
        media["sources"][0]["video"]["fps"] = None
    else:
        media["job_id"] = "other-job"
    assert expected in issue_codes(ve.analyze_edit(documents, media))


def test_mixed_fps_is_rejected_even_if_frame_counts_fit(documents, media):
    media["sources"][1]["video"]["fps"] = {"num": 30, "den": 1}
    assert "MIXED_FPS_UNSUPPORTED" in issue_codes(ve.analyze_edit(documents, media))


@pytest.mark.parametrize("case,expected", [("missing", "SOURCE_AUDIO_MISSING"),
                                         ("unverified", "SOURCE_AUDIO_TIMING_UNVERIFIED"),
                                         ("short", "DECODED_AUDIO_BOUND"),
                                         ("multichannel", "MULTICHANNEL_AUDIO_UNSUPPORTED"),
                                         ("mixed-rate", "MIXED_AUDIO_FORMAT_UNSUPPORTED")])
def test_source_audio_requires_supported_exact_clock(documents, media, case, expected):
    audio = media["sources"][0]["audio"]
    if case == "missing":
        media["sources"][0]["audio"] = None
    elif case == "unverified":
        audio["timing"]["status"] = "FAIL"
    elif case == "short":
        audio["timing"]["sample_count"] = 239999
    elif case == "multichannel":
        audio["channels"] = 6
    else:
        documents["edit-plan"]["items"][1]["audio_policy"] = "SOURCE"
        audio = media["sources"][1]["audio"]
        audio["sample_rate"] = audio["timing"]["sample_rate"] = 44100
    assert expected in issue_codes(ve.analyze_edit(documents, media))


def test_mute_does_not_claim_or_require_source_audio_timing(documents, media):
    documents["edit-plan"]["items"][0]["audio_policy"] = "MUTE"
    media["sources"][0]["audio"]["timing"]["status"] = "FAIL"
    assert ve.analyze_edit(documents, media)["status"] == "PASS"


def test_equivalent_fractional_rates_and_integer_float_schema_values(documents, media):
    documents = manual(documents)
    documents["edit-plan"]["timeline_fps"] = {"num": 60000.0, "den": 2002.0}
    for source in media["sources"]:
        source["video"]["fps"] = {"num": 30000, "den": 1001}
    documents["edit-plan"]["items"][0]["source_in_frame"] = 25.0
    documents["edit-plan"]["items"][0]["source_out_frame"] = 125.0
    report = ve.analyze_edit(documents, media)
    assert report["status"] == "PASS"
    assert report["timeline_duration_seconds"] == {"num": 7007, "den": 1200}


@pytest.mark.parametrize("start,end", [(24, 125), (25, 126)])
def test_exact_frame_window_cannot_exceed_referenced_select(documents, media, start, end):
    item = documents["edit-plan"]["items"][0]
    item.update(source_in_frame=start, source_out_frame=end)
    documents["edit-plan"]["items"][1]["timeline_in_frame"] = end - start
    assert "SELECT_WINDOW_BOUND" in issue_codes(ve.analyze_edit(documents, media))


def test_fractional_mapping_does_not_round_outside_a_select(documents, media):
    documents["edit-plan"]["timeline_fps"] = {"num": 30000, "den": 1001}
    for source in media["sources"]:
        source["video"]["fps"] = {"num": 30000, "den": 1001}
    item = documents["edit-plan"]["items"][0]
    item.update(source_in_frame=30, source_out_frame=150)
    documents["edit-plan"]["items"][1]["timeline_in_frame"] = 120
    # OUT is 5005 ms, outside the 5000 ms candidate despite nominal "30 fps".
    assert "SELECT_WINDOW_BOUND" in issue_codes(ve.analyze_edit(documents, media))


def test_missing_prerequisites_and_schema_errors_stop_calculations(documents, media):
    documents.pop("analysis")
    assert "MISSING_DOCUMENT" in issue_codes(ve.analyze_edit(documents, media))
    documents["edit-plan"]["items"][0]["extra"] = True
    report = ve.analyze_edit(documents, media)
    assert "SCHEMA_INVALID" in issue_codes(report)
    assert report["items"] == []


def test_missing_plan_and_unknown_declared_bounds_fail_closed(documents, media):
    assert "MISSING_DOCUMENT" in issue_codes(ve.analyze_edit({"manifest": documents["manifest"]}, media))
    documents["manifest"]["sources"][0]["frame_count"] = None
    assert "UNKNOWN_BOUND" in issue_codes(ve.analyze_edit(documents, media))


def test_calculated_final_out_is_bounded(documents, media):
    documents = manual(documents)
    for source, scan in zip(documents["manifest"]["sources"], media["sources"]):
        source["frame_count"] = ve.MAX_INTEGER
        scan["video"]["decoded_frame_count"] = ve.MAX_INTEGER
    first, second = documents["edit-plan"]["items"]
    first.update(source_in_frame=0, source_out_frame=ve.MAX_INTEGER)
    second.update(source_in_frame=0, source_out_frame=1, timeline_in_frame=ve.MAX_INTEGER)
    assert "TIMELINE_BOUND" in issue_codes(ve.analyze_edit(documents, media))


@pytest.fixture
def synthetic_run(tmp_path, documents, media, monkeypatch):
    documents = manual(documents)
    for source, scan in zip(documents["manifest"]["sources"], media["sources"]):
        path = tmp_path / (source["source_id"] + "-synthetic.mov")
        path.write_bytes(b"synthetic stand-in; media scan mocked")
        source.update(path=str(path), content_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        scan["path"] = str(path)
    paths = {}
    for stage, document in documents.items():
        path = tmp_path / (stage + ".json")
        path.write_text(json.dumps(document), encoding="utf-8")
        paths[stage] = path
    calls = []

    def scan(manifest_path, output, *args):
        calls.append(manifest_path)
        result = deepcopy(media)
        result["manifest_sha256"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        output.mkdir()
        for number, source in enumerate(result["sources"], 1):
            (output / f"decode-{number:04d}.json").write_text('{"synthetic":"mocked"}', encoding="utf-8")
            (output / f"decode-{number:04d}-provenance.json").write_text(
                json.dumps({"stat_signature": list(file_signature(Path(source["path"])))}), encoding="utf-8")
        (output / "media-report.json").write_text(json.dumps(result), encoding="utf-8")
        return result

    monkeypatch.setattr(ve, "verify_media", scan)
    return paths, documents, media, calls


def test_wrapper_reruns_media_and_preserves_exact_input_bytes(tmp_path, synthetic_run):
    paths, _, _, calls = synthetic_run
    before = {stage: path.read_bytes() for stage, path in paths.items()}
    report = ve.verify_edit(paths, tmp_path / "output")
    assert report["status"] == "PASS" and calls == [paths["manifest"]]
    assert report["input_sha256"] == {stage: hashlib.sha256(raw).hexdigest() for stage, raw in before.items()}
    assert {stage: path.read_bytes() for stage, path in paths.items()} == before
    assert load_json(tmp_path / "output/edit-report.json") == report
    assert (tmp_path / "output/media/media-report.json").exists()


def test_bad_records_fail_before_reading_media(tmp_path, synthetic_run):
    paths, documents, _, calls = synthetic_run
    documents["edit-plan"]["items"][0]["source_id"] = "missing-source"
    paths["edit-plan"].write_text(json.dumps(documents["edit-plan"]), encoding="utf-8")
    with pytest.raises(ValueError, match="MISSING_SOURCE"):
        ve.verify_edit(paths, tmp_path / "output")
    assert not calls and not (tmp_path / "output").exists()


@pytest.mark.parametrize("which", ["plan", "manifest-between-phases", "source-after-scan"])
def test_mutated_inputs_block_publication(tmp_path, synthetic_run, monkeypatch, which):
    paths, _, media, _ = synthetic_run
    original = ve.verify_media

    def changed(*args):
        report = original(*args)
        if which == "plan":
            paths["edit-plan"].write_bytes(paths["edit-plan"].read_bytes() + b"\n")
        elif which == "manifest-between-phases":
            report["manifest_sha256"] = "0" * 64
        else:
            Path(media["sources"][0]["path"]).write_bytes(b"changed synthetic source")
        return report

    monkeypatch.setattr(ve, "verify_media", changed)
    with pytest.raises(ValueError, match="changed"):
        ve.verify_edit(paths, tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_failure_report_retains_scan_evidence_and_cli_status(tmp_path, synthetic_run):
    paths, documents, _, _ = synthetic_run
    documents["edit-plan"]["items"][1]["timeline_in_frame"] = 101
    paths["edit-plan"].write_text(json.dumps(documents["edit-plan"]), encoding="utf-8")
    args = [argument for stage, path in paths.items() for argument in ("--" + stage, str(path))]
    assert ve.main([*args, "--output-dir", str(tmp_path / "output")]) == 1
    assert "TIMELINE_GAP" in issue_codes(load_json(tmp_path / "output/edit-report.json"))
    assert (tmp_path / "output/media").exists()


def test_cli_missing_input_and_output_preservation(tmp_path):
    assert ve.main(["--manifest", str(tmp_path / "missing"), "--edit-plan", str(tmp_path / "missing-plan"),
                    "--output-dir", str(tmp_path / "output")]) == 2
    (tmp_path / "output").mkdir()
    sentinel = tmp_path / "output/preserve.txt"
    sentinel.write_text("preserve", encoding="utf-8")
    with pytest.raises(ValueError, match="already exists"):
        ve.verify_edit({"manifest": tmp_path / "missing", "edit-plan": tmp_path / "missing-plan"}, tmp_path / "output")
    assert sentinel.read_text() == "preserve"


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="Requires real FFmpeg tools")
@pytest.mark.parametrize("rate,frames,den", [("25", 25, 1), ("30000/1001", 30, 1001)])
def test_generated_video_edit_cli(tmp_path, rate, frames, den):
    media = tmp_path / "synthetic.mov"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                    f"testsrc=size=64x48:rate={rate}", "-frames:v", str(frames),
                    "-c:v", "mpeg4", "-pix_fmt", "yuv420p", str(media)],
                   capture_output=True, check=True, timeout=30)
    inventory = tmp_path / "inventory"
    build_manifest("synthetic-job", [("src-1", media)], inventory)
    plan = {"schema_version": "2.0.0", "job_id": "synthetic-job", "revision": "synthetic-r1",
            "timeline_name": "Synthetic video edit", "edit_mode": "SEQUENTIAL_CUTS",
            "timeline_fps": {"num": 25 if den == 1 else 30000, "den": den}, "items": []}
    for number, (start, end) in enumerate(((0, 5), (5, frames))):
        plan["items"].append({"edit_id": f"edit-{number}", "source_id": "src-1", "source_in_frame": start,
                              "source_out_frame": end, "timeline_in_frame": start,
                              "audio_policy": "MUTE", "reason": "Synthetic split", "locked": False})
    plan_path = tmp_path / "edit-plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    args = [sys.executable, str(ROOT / "scripts/verify_edit.py"), "--manifest", str(inventory / "manifest.json"),
            "--edit-plan", str(plan_path), "--output-dir", str(tmp_path / "checked")]
    result = subprocess.run(args, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    report = load_json(tmp_path / "checked/edit-report.json")
    assert report["timeline_frame_count"] == frames
    assert report["timeline_duration_seconds"] == ({"num": 1, "den": 1} if den == 1 else {"num": 1001, "den": 1000})
    assert "approval" in result.stdout and "NOT_CHECKED" in result.stdout


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="Requires real FFmpeg tools")
@pytest.mark.parametrize("case", ["pcm", "ntsc", "shifted", "compressed", "compressed-shifted", "fractional", "mute-shifted"])
def test_generated_source_audio_clock_and_cuts(tmp_path, case):
    ntsc = case in {"ntsc", "fractional"}
    media = tmp_path / "synthetic-av.mov"
    command = ["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
               f"testsrc=size=64x48:rate={'30000/1001' if ntsc else '25'}"]
    if case in {"shifted", "compressed-shifted", "mute-shifted"}:
        command += ["-itsoffset", "0.04"]
    command += ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
                "-t", "1.001" if ntsc else "1", "-c:v", "mpeg4", "-pix_fmt", "yuv420p",
                "-c:a", "aac" if case.startswith("compressed") else "pcm_s16le", str(media)]
    subprocess.run(command, check=True, capture_output=True, timeout=30)
    build_manifest("synthetic-av", [("src-1", media)], tmp_path / "inventory")
    frames, split = (30, 1 if case == "fractional" else 5) if ntsc else (25, 5)
    plan = {"schema_version": "2.0.0", "job_id": "synthetic-av", "revision": "synthetic-r1",
            "timeline_name": "Synthetic audio timing", "edit_mode": "SEQUENTIAL_CUTS",
            "timeline_fps": {"num": 30000 if ntsc else 25, "den": 1001 if ntsc else 1}, "items": []}
    for number, (start, end) in enumerate(((0, split), (split, frames))):
        plan["items"].append({"edit_id": f"edit-{number}", "source_id": "src-1", "source_in_frame": start,
                              "source_out_frame": end, "timeline_in_frame": start,
                              "audio_policy": "MUTE" if case == "mute-shifted" else "SOURCE",
                              "reason": "Synthetic sample-aligned cut", "locked": False})
    plan_path = tmp_path / "edit-plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    report = ve.verify_edit({"manifest": tmp_path / "inventory/manifest.json", "edit-plan": plan_path}, tmp_path / "checked")
    if case in {"pcm", "ntsc", "compressed", "mute-shifted"}:
        assert report["status"] == "PASS", report["issues"]
        if case != "mute-shifted":
            assert report["items"][0]["audio_cut"]["source_out_sample"] == (8008 if ntsc else 9600)
    else:
        assert report["status"] == "FAIL"
        assert ("FRACTIONAL_AUDIO_SAMPLE_CUT_UNSUPPORTED" if case == "fractional" else "SOURCE_AUDIO_TIMING_UNVERIFIED") in issue_codes(report)
