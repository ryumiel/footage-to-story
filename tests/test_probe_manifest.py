"""Synthetic metadata and generated media tests; never use shoot footage."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from scripts import probe_manifest as pm
from scripts.validate_json import build_validator, load_json, ROOT


@pytest.fixture
def probe():
    return {"streams": [
        {"index": 0, "codec_type": "video", "avg_frame_rate": "30000/1001",
         "r_frame_rate": "30/1", "time_base": "1/30000", "nb_frames": "30",
         "duration": "1.001", "tags": {"timecode": "01:00:00:00"}},
        {"index": 1, "codec_type": "audio", "sample_rate": "48000", "channels": 2},
    ], "format": {"duration": "1.2"}}


def normalize(probe):
    return pm.normalize_probe("synthetic-source", Path("/synthetic/clip.mov"),
                              probe, "0" * 64, "probe-0001.json")


def test_reported_rational_metadata_and_provenance(probe):
    source = normalize(probe)
    assert (source["fps_num"], source["fps_den"]) == (30000, 1001)
    assert source["duration_ms"] == 1001
    assert source["frame_count"] == 30
    assert source["cfr_status"] == "UNKNOWN"
    assert source["time_base"] == {"num": 1, "den": 30000}
    assert source["source_start_timecode"] == "01:00:00:00"
    assert source["audio_sample_rate"] == 48000
    assert any("probe-0001.json" in note for note in source["notes"])


@pytest.mark.parametrize("value", [None, "N/A", "0", "0/0", "1/0", "-25/1", True, "NaN"])
def test_unknown_rate_and_count_are_not_inferred(probe, value):
    video = probe["streams"][0]
    video["avg_frame_rate"] = video["nb_frames"] = value
    source = normalize(probe)
    assert source["fps_num"] is None and source["fps_den"] is None
    assert source["frame_count"] is None
    assert source["cfr_status"] == "UNKNOWN"


@pytest.mark.parametrize("value,expected", [("0.0001", 1), ("1.00001", 1001),
                                           ("N/A", None), ("0", None), ("-1", None)])
def test_duration_rounding_and_unknowns(value, expected):
    assert pm.duration_ms(value) == expected


def test_audio_only_and_container_duration_fallback(probe):
    probe["streams"] = [probe["streams"][1]]
    probe["streams"][0]["time_base"] = "1/48000"
    source = normalize(probe)
    assert source["duration_ms"] == 1200
    assert source["fps_num"] is None and source["frame_count"] is None
    assert source["time_base"] == {"num": 1, "den": 48000}
    assert any("fallback" in note for note in source["notes"])


def test_cover_art_does_not_create_video_timing(probe):
    probe["streams"][0]["disposition"] = {"attached_pic": 1}
    assert normalize(probe)["fps_num"] is None


@pytest.mark.parametrize("kind", ["video", "audio"])
def test_ambiguous_streams_fail(probe, kind):
    extra = deepcopy(next(s for s in probe["streams"] if s["codec_type"] == kind))
    extra["index"] = 2
    probe["streams"].append(extra)
    with pytest.raises(ValueError, match="Multiple"):
        normalize(probe)


def test_duplicate_stream_indices_reject_even_with_audio_selector(probe):
    probe["streams"].append(deepcopy(probe["streams"][1]))
    with pytest.raises(ValueError, match="distinct"):
        pm.normalize_probe("synthetic-source", Path("/synthetic/clip.mov"), probe,
                           "0" * 64, "probe-0001.json", audio_stream_index=1)


def test_explicit_audio_selector_resolves_multiple_tracks(probe):
    probe["streams"].append({"index": 2, "codec_type": "audio", "sample_rate": "44100", "channels": 1})
    with pytest.raises(ValueError, match="require an explicit selector"):
        normalize(probe)
    selected = pm.normalize_probe("synthetic-source", Path("/synthetic/clip.mov"),
                                  probe, "0" * 64, "probe-0001.json",
                                  audio_stream_index=2, record_audio_stream_index=True)
    assert selected["audio_stream_index"] == 2
    assert selected["audio_sample_rate"] == 44100 and selected["audio_channels"] == 1
    assert any("audio stream index: 2" in note for note in selected["notes"])
    for wrong in (0, 3, -1, True):
        with pytest.raises(ValueError):
            pm.normalize_probe("synthetic-source", Path("/synthetic/clip.mov"),
                               probe, "0" * 64, "probe-0001.json", audio_stream_index=wrong)


@pytest.mark.parametrize("payload", [{}, {"streams": []}, {"streams": [None]},
                                     {"streams": [], "format": []},
                                     {"streams": [{"codec_type": "video", "disposition": None}]}])
def test_unusable_probe_responses_fail(payload):
    with pytest.raises(ValueError):
        normalize(payload)


@pytest.fixture
def mock_probe(monkeypatch, probe):
    commands = []
    monkeypatch.setattr(pm.shutil, "which", lambda _: "/synthetic/ffprobe")

    def run(command, timeout):
        commands.append(command)
        stdout = "synthetic ffprobe version\n" if "-version" in command else json.dumps(probe)
        return subprocess.CompletedProcess(command, 0, stdout, "")

    monkeypatch.setattr(pm, "run_probe_command", run)
    return commands


def test_bundle_has_exact_file_hash_and_raw_evidence(tmp_path, mock_probe):
    media = tmp_path / "synthetic media; $(literal).mov"
    media.write_bytes(b"synthetic stand-in; mocked probing only")
    output = tmp_path / "bundle"
    manifest = pm.build_manifest("synthetic-job", [("src-1", media)], output)
    source = manifest["sources"][0]
    assert source["content_sha256"] == hashlib.sha256(media.read_bytes()).hexdigest()
    assert source["path"] == str(media.resolve())
    assert load_json(output / "manifest.json") == manifest
    evidence = load_json(output / "probe-0001.json")
    assert json.loads(evidence["stdout"])["streams"][0]["nb_frames"] == "30"
    assert evidence["command"][-1] == str(media)
    assert evidence["command"][3:5] == ["-protocol_whitelist", "file"]
    assert evidence["content_sha256"] == source["content_sha256"]
    assert not list(build_validator(ROOT / "schemas/2.0.0/manifest.schema.json").iter_errors(manifest))


def test_manifest3_records_resolved_audio_stream_and_preserves_legacy_output(tmp_path, mock_probe, probe):
    media = tmp_path / "synthetic.mov"
    media.write_bytes(b"synthetic multi-audio stand-in")
    legacy = pm.build_manifest("synthetic-job", [("src-1", media)], tmp_path / "legacy")
    assert legacy["schema_version"] == "2.0.0"
    assert "audio_stream_index" not in legacy["sources"][0]
    probe["streams"].append({"index": 2, "codec_type": "audio", "sample_rate": "44100", "channels": 1})
    selected = pm.build_manifest("synthetic-job", [("src-1", media)], tmp_path / "selected",
                                 audio_stream_indices={"src-1": 2})
    assert selected["schema_version"] == "3.0.0"
    assert selected["sources"][0]["audio_stream_index"] == 2
    assert selected["sources"][0]["audio_sample_rate"] == 44100
    build_validator(ROOT / "schemas/3.0.0/manifest.schema.json", ROOT / "schemas").validate(selected)
    assert load_json(tmp_path / "selected/manifest.json") == selected
    with pytest.raises(ValueError, match="explicit selector"):
        pm.build_manifest("synthetic-job", [("src-1", media)], tmp_path / "ambiguous")
    assert not (tmp_path / "ambiguous").exists()


@pytest.mark.parametrize("selectors", [{"other": 1}, {"src-1": True}, {"src-1": -1},
                                       {"src-1": 2 ** 54}, [1]])
def test_invalid_selector_mapping_fails_before_probe(tmp_path, mock_probe, selectors):
    media = tmp_path / "synthetic.mov"
    media.write_bytes(b"synthetic")
    with pytest.raises(ValueError, match="selectors"):
        pm.build_manifest("synthetic-job", [("src-1", media)], tmp_path / "bundle",
                          audio_stream_indices=selectors)
    assert not (tmp_path / "bundle").exists()
    assert not mock_probe


def test_audio_stream_cli_repeat_and_duplicate_rejection(tmp_path, mock_probe, probe):
    media = tmp_path / "synthetic.mov"
    media.write_bytes(b"synthetic")
    probe["streams"].append({"index": 2, "codec_type": "audio", "sample_rate": "44100", "channels": 1})
    assert pm.main(["--job-id", "synthetic-job", "--source", "src-1", str(media),
                    "--audio-stream", "src-1", "2", "--output-dir", str(tmp_path / "bundle")]) == 0
    assert load_json(tmp_path / "bundle/manifest.json")["sources"][0]["audio_stream_index"] == 2
    assert pm.main(["--job-id", "synthetic-job", "--source", "src-1", str(media),
                    "--audio-stream", "src-1", "2", "--audio-stream", "src-1", "1",
                    "--output-dir", str(tmp_path / "duplicate")]) == 2
    assert not (tmp_path / "duplicate").exists()


@pytest.mark.parametrize("case", ["duplicate-id", "duplicate-path", "hard-link", "bad-id", "bad-job", "missing", "directory"])
def test_invalid_inputs_fail_before_probing(tmp_path, mock_probe, case):
    media = tmp_path / "synthetic.mov"
    media.write_bytes(b"synthetic")
    sources = [("src-1", media)]
    job = "synthetic-job"
    if case == "duplicate-id":
        other = tmp_path / "other.mov"
        other.write_bytes(b"other synthetic")
        sources.append(("src-1", other))
    elif case == "duplicate-path":
        sources.append(("src-2", media))
    elif case == "hard-link":
        alias = tmp_path / "alias.mov"
        alias.hardlink_to(media)
        sources.append(("src-2", alias))
    elif case == "bad-id":
        sources = [("invalid id", media)]
    elif case == "bad-job":
        job = "invalid job"
    elif case == "missing":
        sources = [("src-1", tmp_path / "missing.mov")]
    elif case == "directory":
        sources = [("src-1", tmp_path)]
    output = tmp_path / "bundle"
    with pytest.raises((ValueError, OSError)):
        pm.build_manifest(job, sources, output)
    assert not output.exists()
    assert not mock_probe


def test_existing_output_is_preserved(tmp_path, mock_probe):
    output = tmp_path / "bundle"
    output.mkdir()
    sentinel = output / "manifest.json"
    sentinel.write_text("preserve this", encoding="utf-8")
    with pytest.raises(ValueError, match="already exists"):
        pm.build_manifest("synthetic-job", [], output)
    assert sentinel.read_text() == "preserve this"


def test_output_cannot_enter_source_tree(tmp_path, monkeypatch):
    monkeypatch.setattr(pm, "ROOT", tmp_path)
    with pytest.raises(ValueError, match="below work"):
        pm.check_output_directory(tmp_path / "docs" / "bundle")
    assert pm.check_output_directory(tmp_path / "work" / "synthetic-job")
    alias = tmp_path / "artifacts"
    alias.symlink_to(tmp_path / "docs", target_is_directory=True)
    with pytest.raises(ValueError):
        pm.check_output_directory(alias / "bundle")


def test_source_change_blocks_output(tmp_path, mock_probe, monkeypatch):
    media = tmp_path / "synthetic.mov"
    media.write_bytes(b"synthetic")
    original = pm.run_probe_command

    def change(command, timeout):
        result = original(command, timeout)
        if "-show_streams" in command:
            media.write_bytes(b"changed synthetic source")
        return result

    monkeypatch.setattr(pm, "run_probe_command", change)
    with pytest.raises(ValueError, match="changed"):
        pm.build_manifest("synthetic-job", [("src-1", media)], tmp_path / "bundle")
    assert not (tmp_path / "bundle").exists()


@pytest.mark.parametrize("failure", ["bad-json", "duplicate-json", "timeout", "nonzero"])
def test_probe_failures_leave_no_manifest(tmp_path, mock_probe, monkeypatch, failure):
    media = tmp_path / "synthetic.mov"
    media.write_bytes(b"synthetic")

    def fail(command, timeout):
        if "-version" in command:
            return subprocess.CompletedProcess(command, 0, "synthetic version", "")
        if failure == "timeout":
            raise ValueError("ffprobe timed out")
        if failure == "nonzero":
            raise ValueError("ffprobe exited 1")
        text = "{" if failure == "bad-json" else '{"streams":[],"streams":[]}'
        return subprocess.CompletedProcess(command, 0, text, "")

    monkeypatch.setattr(pm, "run_probe_command", fail)
    assert pm.main(["--job-id", "synthetic-job", "--source", "src-1", str(media),
                    "--output-dir", str(tmp_path / "bundle")]) == 2
    assert not (tmp_path / "bundle").exists()


def test_subprocess_timeout_and_nonzero_are_errors(monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 1)
    monkeypatch.setattr(pm.subprocess, "run", timeout)
    with pytest.raises(ValueError, match="timed out"):
        pm.run_probe_command(["ffprobe"], 1)
    monkeypatch.setattr(pm.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a[0], 1, "", "bad media"))
    with pytest.raises(ValueError, match="bad media"):
        pm.run_probe_command(["ffprobe"], 1)


def test_missing_ffprobe_leaves_no_output(tmp_path, monkeypatch):
    media = tmp_path / "synthetic.mov"
    media.write_bytes(b"synthetic")
    monkeypatch.setattr(pm.shutil, "which", lambda _: None)
    with pytest.raises(ValueError, match="unavailable"):
        pm.build_manifest("synthetic-job", [("src-1", media)], tmp_path / "bundle")
    assert not (tmp_path / "bundle").exists()


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
def test_invalid_timeout_is_rejected(tmp_path, timeout):
    with pytest.raises(ValueError, match="Timeout"):
        pm.build_manifest("synthetic-job", [], tmp_path / "bundle", timeout=timeout)


def test_write_failure_never_publishes_partial_manifest(tmp_path, mock_probe, monkeypatch):
    media = tmp_path / "synthetic.mov"
    media.write_bytes(b"synthetic")
    original = pm.os.link

    def fail_manifest(source, destination):
        if destination.name == "manifest.json":
            raise OSError("synthetic publication failure")
        return original(source, destination)

    monkeypatch.setattr(pm.os, "link", fail_manifest)
    assert pm.main(["--job-id", "synthetic-job", "--source", "src-1", str(media),
                    "--output-dir", str(tmp_path / "bundle")]) == 2
    assert not (tmp_path / "bundle/manifest.json").exists()
    assert media.read_bytes() == b"synthetic"


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
                    reason="Generated-media integration requires ffmpeg and ffprobe")
@pytest.mark.parametrize("kind", ["video-audio", "silent-video", "audio-only"])
def test_generated_media_integration(tmp_path, kind):
    """Generate local test signals and verify real probing without any user media."""
    media = tmp_path / ("synthetic.wav" if kind == "audio-only" else "synthetic.mov")
    command = ["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi"]
    if kind == "audio-only":
        command += ["-i", "sine=frequency=440:sample_rate=48000", "-t", "1", "-c:a", "pcm_s16le"]
    else:
        rate = "30000/1001" if kind == "video-audio" else "25"
        command += ["-i", f"testsrc=size=64x48:rate={rate}"]
        if kind == "video-audio":
            command += ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000"]
        command += ["-t", "1.001" if kind == "video-audio" else "1",
                    "-c:v", "mpeg4", "-q:v", "5", "-pix_fmt", "yuv420p"]
        if kind == "video-audio":
            command += ["-c:a", "pcm_s16le", "-ac", "2"]
    subprocess.run(command + [str(media)], check=True, capture_output=True, timeout=30)
    digest = hashlib.sha256(media.read_bytes()).hexdigest()
    output = tmp_path / "bundle"
    result = subprocess.run([sys.executable, str(ROOT / "scripts/probe_manifest.py"),
                             "--job-id", "synthetic-job", "--source", "src-1", str(media),
                             "--output-dir", str(output)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    source = load_json(output / "manifest.json")["sources"][0]
    assert source["content_sha256"] == digest == hashlib.sha256(media.read_bytes()).hexdigest()
    assert source["cfr_status"] == "UNKNOWN"
    if kind == "audio-only":
        assert source["fps_num"] is None and source["frame_count"] is None
        assert source["duration_ms"] == 1000
    else:
        assert source["frame_count"] == (30 if kind == "video-audio" else 25)
        assert (source["fps_num"], source["fps_den"]) == ((30000, 1001) if kind == "video-audio" else (25, 1))
    assert source["audio_sample_rate"] == (None if kind == "silent-video" else 48000)
