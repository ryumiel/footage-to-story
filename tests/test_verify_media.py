"""Decoded timing tests use synthetic evidence and generated media only."""
from copy import deepcopy
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from scripts import verify_media as vm
from scripts.probe_manifest import build_manifest
from scripts.validate_json import ROOT, load_json


def video_frames(points, durations=None):
    return [{"media_type": "video", "stream_index": 0, "pts": pts,
             "duration": duration} for pts, duration in zip(points, durations or [40] * len(points))]


@pytest.fixture
def probe():
    return {"streams": [{"index": 0, "codec_type": "video", "time_base": "1/1000"}],
            "frames": video_frames([0, 40, 80]), "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2"}}


def test_exact_decoded_cfr_and_extent(probe):
    result = vm.summarize_decode(probe)
    assert result["issues"] == []
    video = result["video"]
    assert video["decoded_frame_count"] == 3
    assert video["cfr_status"] == "CFR"
    assert video["fps"] == {"num": 25, "den": 1}
    assert video["duration_seconds"] == {"num": 3, "den": 25}


def test_ntsc_is_measured_as_exact_rational_not_rounded(probe):
    probe["streams"][0]["time_base"] = "1/30000"
    probe["frames"] = video_frames([0, 1001, 2002], [1001] * 3)
    video = vm.summarize_decode(probe)["video"]
    assert video["fps"] == {"num": 30000, "den": 1001}
    assert video["duration_seconds"] == {"num": 1001, "den": 10000}


@pytest.mark.parametrize("points,expected", [([0, 40, 120], "VFR"),
                                          ([0, 33, 67], "UNKNOWN")])
def test_variable_and_quantized_timing_never_pass_cfr(probe, points, expected):
    probe["frames"] = video_frames(points)
    result = vm.summarize_decode(probe)
    assert result["video"]["cfr_status"] == expected
    assert "IRREGULAR_OR_QUANTIZED_TIMING" in result["issues"]


@pytest.mark.parametrize("case,expected", [
    ("missing-pts", "MISSING_ACTUAL_PTS"),
    ("estimated-only", "MISSING_ACTUAL_PTS"),
    ("duplicate-pts", "NONMONOTONIC_PTS"),
    ("backward-pts", "NONMONOTONIC_PTS"),
    ("nonzero-origin", "NONZERO_VIDEO_ORIGIN_UNSUPPORTED"),
    ("negative-origin", "NONZERO_VIDEO_ORIGIN_UNSUPPORTED"),
    ("missing-duration", "MISSING_FRAME_DURATION"),
    ("zero-duration", "MISSING_FRAME_DURATION"),
    ("unknown-base", "UNKNOWN_TIME_BASE"),
    ("empty", "NO_DECODED_VIDEO"),
    ("single", "INSUFFICIENT_VIDEO_FRAMES"),
])
def test_unverified_timing_is_explicitly_blocked(probe, case, expected):
    if case in {"missing-pts", "estimated-only"}:
        probe["frames"][0].pop("pts")
        if case == "estimated-only":
            probe["frames"][0]["best_effort_timestamp"] = 0
    elif case == "duplicate-pts":
        probe["frames"][1]["pts"] = 0
    elif case == "backward-pts":
        probe["frames"][1]["pts"] = -1
    elif case in {"nonzero-origin", "negative-origin"}:
        offset = 100 if case == "nonzero-origin" else -100
        for frame in probe["frames"]:
            frame["pts"] += offset
    elif case == "missing-duration":
        probe["frames"][-1].pop("duration")
    elif case == "zero-duration":
        probe["frames"][-1]["duration"] = 0
    elif case == "unknown-base":
        probe["streams"][0]["time_base"] = "N/A"
    elif case == "empty":
        probe["frames"] = []
    elif case == "single":
        probe["frames"] = probe["frames"][:1]
    assert expected in vm.summarize_decode(probe)["issues"]


def test_final_frame_duration_cannot_be_guessed(probe):
    probe["frames"][-1]["duration"] = 20
    result = vm.summarize_decode(probe)
    assert result["video"]["cfr_status"] == "UNKNOWN"
    assert result["issues"]


@pytest.mark.parametrize("mutation", ["missing-streams", "missing-frames", "null-frame", "duplicate-index",
                                     "missing-index", "missing-frame-index", "wrong-frame-type", "ambiguous-video",
                                     "ambiguous-audio", "bad-disposition"])
def test_malformed_or_ambiguous_decode_evidence_fails(probe, mutation):
    if mutation == "missing-streams":
        probe.pop("streams")
    elif mutation == "missing-frames":
        probe.pop("frames")
    elif mutation == "null-frame":
        probe["frames"].append(None)
    elif mutation == "duplicate-index":
        probe["streams"].append(deepcopy(probe["streams"][0]))
    elif mutation == "missing-index":
        probe["streams"][0].pop("index")
    elif mutation == "missing-frame-index":
        probe["frames"][0].pop("stream_index")
    elif mutation == "wrong-frame-type":
        probe["frames"][0]["media_type"] = "audio"
    elif mutation == "ambiguous-video":
        probe["streams"].append({"index": 1, "codec_type": "video"})
    elif mutation == "ambiguous-audio":
        probe["streams"].extend([{"index": 1, "codec_type": "audio"}, {"index": 2, "codec_type": "audio"}])
    else:
        probe["streams"][0]["disposition"] = []
    with pytest.raises(ValueError):
        vm.summarize_decode(probe)


def test_audio_sample_counts_are_recorded_without_claiming_synchronization():
    probe = {"streams": [{"index": 0, "codec_type": "audio", "sample_rate": "48000", "channels": 2}],
             "frames": [{"stream_index": 0, "media_type": "audio", "nb_samples": 1024}]}
    result = vm.summarize_decode(probe)
    assert result["video"] is None
    assert result["audio"]["decoded_samples"] == 1024
    assert result["issues"] == []
    probe["frames"][0].pop("nb_samples")
    assert "MISSING_DECODED_AUDIO_SAMPLES" in vm.summarize_decode(probe)["issues"]


def test_multiple_audio_streams_require_and_obey_explicit_selection(probe):
    probe["streams"].extend([
        {"index": 1, "codec_type": "audio", "sample_rate": "48000", "channels": 2},
        {"index": 2, "codec_type": "audio", "sample_rate": "44100", "channels": 1},
    ])
    probe["frames"].extend([
        {"stream_index": 1, "media_type": "audio", "nb_samples": 480},
        {"stream_index": 2, "media_type": "audio", "nb_samples": 441},
    ])
    with pytest.raises(ValueError, match="Multiple audio"):
        vm.summarize_decode(probe)
    decoded = vm.summarize_decode(probe, audio_stream_index=2)
    assert decoded["audio"]["stream_index"] == 2
    assert decoded["audio"]["sample_rate"] == 44100
    assert decoded["audio"]["channels"] == 1
    assert decoded["audio"]["decoded_samples"] == 441
    for selector in (True, -1, 0, 3):
        with pytest.raises(ValueError):
            vm.summarize_decode(probe, audio_stream_index=selector)
    probe["frames"][-2]["media_type"] = "video"
    with pytest.raises(ValueError, match="Decoded frame"):
        vm.summarize_decode(probe, audio_stream_index=2)


def test_selected_audio_stream_identity_is_compared(probe):
    probe["streams"].append({"index": 2, "codec_type": "audio", "sample_rate": "48000", "channels": 2})
    probe["frames"].append({"stream_index": 2, "media_type": "audio", "nb_samples": 480})
    decoded = vm.summarize_decode(probe, audio_stream_index=2)
    source = {"frame_count": 3, "fps_num": 25, "fps_den": 1, "cfr_status": "CFR",
              "duration_ms": 120, "audio_stream_index": 1}
    assert "AUDIO_STREAM_INDEX_MISMATCH" in vm.compare_inventory(source, decoded)
    source["audio_stream_index"] = 2
    assert vm.compare_inventory(source, decoded) == []


@pytest.fixture
def synthetic_run(tmp_path, probe, monkeypatch):
    media = tmp_path / "synthetic stand-in.mov"
    media.write_bytes(b"synthetic stand-in; full decode mocked")
    source = {"source_id": "src-1", "path": str(media), "duration_ms": 120,
              "frame_count": 3, "fps_num": 25, "fps_den": 1, "cfr_status": "UNKNOWN",
              "content_sha256": hashlib.sha256(media.read_bytes()).hexdigest()}
    manifest = {"schema_version": "2.0.0", "job_id": "synthetic-job", "sources": [source]}
    manifest_path = tmp_path / "synthetic-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(vm.shutil, "which", lambda _: "/synthetic/ffprobe")
    monkeypatch.setattr(vm, "run_probe_command", lambda command, timeout: subprocess.CompletedProcess(command, 0, "synthetic ffprobe", ""))
    calls = []

    def decode(command, path, timeout, max_bytes):
        calls.append(command)
        path.write_text(json.dumps(probe), encoding="utf-8")
        return ""

    monkeypatch.setattr(vm, "decode_to_file", decode)
    return manifest_path, manifest, media, calls


def save_manifest(path, manifest):
    path.write_text(json.dumps(manifest), encoding="utf-8")


def test_verified_report_preserves_inputs_and_provenance(tmp_path, synthetic_run):
    path, manifest, media, calls = synthetic_run
    before = path.read_bytes(), media.read_bytes()
    report = vm.verify_media(path, tmp_path / "output")
    assert report["status"] == "PASS"
    assert report["sources"][0]["video"]["decoded_frame_count"] == 3
    assert report["manifest_sha256"] == hashlib.sha256(before[0]).hexdigest()
    assert (path.read_bytes(), media.read_bytes()) == before
    assert "edit audio cuts/synchronization" in report["not_checked"]
    assert load_json(tmp_path / "output/media-report.json") == report
    provenance = load_json(tmp_path / "output/decode-0001-provenance.json")
    assert provenance["command"] == calls[0]
    assert calls[0][-1] == str(media)
    assert calls[0][3:5] == ["-protocol_whitelist", "file"]


@pytest.mark.parametrize("field,value,expected", [("frame_count", 4, "FRAME_COUNT_MISMATCH"),
                                               ("duration_ms", 121, "VIDEO_DURATION_MISMATCH"),
                                               ("fps_num", 30, "FPS_MISMATCH"),
                                               ("cfr_status", "VFR", "CFR_STATUS_MISMATCH"),
                                               ("audio_channels", 2, "AUDIO_FORMAT_MISMATCH"),
                                               ("proxy_path", "/synthetic/proxy.mov", "PROXY_MAPPING_UNSUPPORTED"),
                                               ("time_base", {"num": 1, "den": 25000}, "TIME_BASE_MISMATCH")])
def test_inventory_mismatch_produces_failed_report(tmp_path, synthetic_run, field, value, expected):
    path, manifest, _, _ = synthetic_run
    manifest["sources"][0][field] = value
    save_manifest(path, manifest)
    report = vm.verify_media(path, tmp_path / "output")
    assert report["status"] == "FAIL"
    assert expected in report["sources"][0]["issues"]


def test_unknown_inventory_can_be_measured_without_rewriting_it(tmp_path, synthetic_run):
    path, manifest, _, _ = synthetic_run
    manifest["sources"][0].update(duration_ms=None, frame_count=None, fps_num=None, fps_den=None)
    save_manifest(path, manifest)
    before = path.read_bytes()
    report = vm.verify_media(path, tmp_path / "output")
    assert report["status"] == "PASS"
    assert report["sources"][0]["video"]["fps"] == {"num": 25, "den": 1}
    assert path.read_bytes() == before


def test_schema_valid_integral_floats_are_compared_exactly(tmp_path, synthetic_run):
    path, manifest, _, _ = synthetic_run
    manifest["sources"][0].update(fps_num=25.0, fps_den=1.0,
                                  time_base={"num": 1.0, "den": 1000.0})
    save_manifest(path, manifest)
    assert vm.verify_media(path, tmp_path / "output")["status"] == "PASS"


def test_source_changed_later_in_batch_blocks_publication(tmp_path, synthetic_run, monkeypatch):
    path, manifest, first, _ = synthetic_run
    second = tmp_path / "second-synthetic.mov"
    second.write_bytes(b"second synthetic stand-in")
    source = deepcopy(manifest["sources"][0])
    source.update(source_id="src-2", path=str(second), content_sha256=hashlib.sha256(second.read_bytes()).hexdigest())
    manifest["sources"].append(source)
    save_manifest(path, manifest)
    original = vm.decode_to_file

    def changed(command, *args):
        result = original(command, *args)
        if command[-1] == str(second):
            first.write_bytes(b"changed first synthetic source")
        return result

    monkeypatch.setattr(vm, "decode_to_file", changed)
    with pytest.raises(ValueError, match="batch verification"):
        vm.verify_media(path, tmp_path / "output")
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize("value", [None, "0" * 64])
def test_missing_or_mismatched_hash_blocks_before_decode(tmp_path, synthetic_run, value):
    path, manifest, _, calls = synthetic_run
    manifest["sources"][0]["content_sha256"] = value
    save_manifest(path, manifest)
    with pytest.raises(ValueError, match="SHA-256"):
        vm.verify_media(path, tmp_path / "output")
    assert not calls and not (tmp_path / "output").exists()


def test_file_changed_during_decode_blocks_publication(tmp_path, synthetic_run, monkeypatch):
    path, _, media, _ = synthetic_run
    original = vm.decode_to_file

    def changed(*args):
        result = original(*args)
        media.write_bytes(b"changed synthetic source")
        return result

    monkeypatch.setattr(vm, "decode_to_file", changed)
    with pytest.raises(ValueError, match="changed"):
        vm.verify_media(path, tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_relative_media_paths_and_existing_output_fail(tmp_path, synthetic_run):
    path, manifest, _, _ = synthetic_run
    manifest["sources"][0]["path"] = "relative-synthetic.mov"
    save_manifest(path, manifest)
    with pytest.raises(ValueError, match="absolute"):
        vm.verify_media(path, tmp_path / "output")
    (tmp_path / "output").mkdir()
    with pytest.raises(ValueError, match="already exists"):
        vm.verify_media(path, tmp_path / "output")


def test_malformed_format_evidence_blocks_publication(tmp_path, synthetic_run, probe):
    path, _, _, _ = synthetic_run
    probe["format"] = None
    with pytest.raises(ValueError, match="self-contained"):
        vm.verify_media(path, tmp_path / "output")
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize("timeout,max_bytes", [(0, 100), (float("nan"), 100), (1, 0)])
def test_limits_must_be_positive(tmp_path, timeout, max_bytes):
    with pytest.raises(ValueError, match="limit"):
        vm.verify_media(tmp_path / "missing.json", tmp_path / "output", timeout=timeout, max_bytes=max_bytes)


@pytest.mark.parametrize("failure", ["timeout", "stderr", "nonzero", "oversize"])
def test_spooled_decode_failures_are_not_accepted(tmp_path, monkeypatch, failure):
    def run(command, stdout, stderr, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, 1)
        stdout.write(b"x" * (101 if failure == "oversize" else 1))
        if failure == "stderr":
            stderr.write(b"synthetic decoder error despite exit zero")
        return subprocess.CompletedProcess(command, 1 if failure == "nonzero" else 0)

    monkeypatch.setattr(vm.subprocess, "run", run)
    with pytest.raises(ValueError):
        vm.decode_to_file(["synthetic-ffprobe"], tmp_path / "raw.json", 1, 100)


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="Requires real FFmpeg tools")
def test_composite_media_is_rejected_before_dependency_decode(tmp_path):
    media = tmp_path / "synthetic-dependency.mov"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                    "color=c=red:size=64x48:rate=25", "-t", "1", "-c:v", "mpeg4", str(media)],
                   check=True, capture_output=True, timeout=30)
    wrapper = tmp_path / "synthetic.ffconcat"
    wrapper.write_text("ffconcat version 1.0\nfile synthetic-dependency.mov\n", encoding="utf-8")
    inventory = tmp_path / "inventory"
    build_manifest("synthetic-job", [("src-1", wrapper)], inventory)
    # The same wrapper can point to changed content; its hash is not an identity
    # for that content. Verification must reject the wrapper demuxer entirely.
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                    "color=c=blue:size=64x48:rate=25", "-t", "1", "-c:v", "mpeg4", "-y", str(media)],
                   check=True, capture_output=True, timeout=30)
    with pytest.raises(ValueError, match="Decode reported errors"):
        vm.verify_media(inventory / "manifest.json", tmp_path / "checked")
    assert not (tmp_path / "checked").exists()


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="Requires real FFmpeg tools")
@pytest.mark.parametrize("kind", ["cfr", "bframes", "ntsc-audio", "vfr", "audio-only", "corrupt", "truncated"])
def test_real_synthetic_media_gate(tmp_path, kind):
    media = tmp_path / ("synthetic.wav" if kind == "audio-only" else "synthetic.mov")
    command = ["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi"]
    if kind == "audio-only":
        command += ["-i", "sine=frequency=440:sample_rate=48000", "-t", "1", "-c:a", "pcm_s16le"]
    else:
        rate = "30000/1001" if kind == "ntsc-audio" else "25"
        command += ["-i", f"testsrc=size=64x48:rate={rate}"]
        if kind == "ntsc-audio":
            command += ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-c:a", "pcm_s16le"]
        if kind == "vfr":
            command += ["-vf", "setpts=if(lt(N\\,10)\\,N\\,10+(N-10)*2)", "-fps_mode", "vfr", "-frames:v", "20"]
        else:
            command += ["-t", "1.001" if kind == "ntsc-audio" else "1"]
        command += ["-c:v", "mpeg4", "-pix_fmt", "yuv420p"]
        if kind == "bframes":
            command += ["-bf", "2"]
    subprocess.run(command + [str(media)], check=True, capture_output=True, timeout=30)
    inventory = tmp_path / "inventory"
    build_manifest("synthetic-job", [("src-1", media)], inventory)
    manifest_path = inventory / "manifest.json"
    original = media.read_bytes()
    if kind in {"corrupt", "truncated"}:
        if kind == "truncated":
            corrupt = bytearray(original[:len(original) // 2])
        else:
            packets = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_packets",
                                      "-show_entries", "packet=pos,size", "-of", "json", str(media)],
                                     text=True, capture_output=True, check=True, timeout=30)
            packet = json.loads(packets.stdout)["packets"][0]
            start, size = int(packet["pos"]), int(packet["size"])
            corrupt = bytearray(original)
            corrupt[start:start + size] = b"\0" * size
        media.write_bytes(corrupt)
        # Deliberately bind the synthetic inventory to the damaged bytes so this
        # exercises decoder errors rather than stopping at the identity gate.
        manifest = load_json(manifest_path)
        manifest["sources"][0]["content_sha256"] = hashlib.sha256(corrupt).hexdigest()
        save_manifest(manifest_path, manifest)
        result = vm.main(["--manifest", str(manifest_path), "--output-dir", str(tmp_path / "checked")])
        assert result == 2 and not (tmp_path / "checked").exists()
        assert media.read_bytes() == corrupt
    else:
        result = subprocess.run([sys.executable, str(ROOT / "scripts/verify_media.py"),
                                 "--manifest", str(manifest_path), "--output-dir", str(tmp_path / "checked")],
                                capture_output=True, text=True, timeout=30)
        assert result.returncode == (1 if kind == "vfr" else 0), result.stderr
        report = load_json(tmp_path / "checked/media-report.json")
        video = report["sources"][0]["video"]
        if kind == "vfr":
            assert video["cfr_status"] == "VFR"
        elif kind == "ntsc-audio":
            assert video["fps"] == {"num": 30000, "den": 1001}
            assert report["sources"][0]["audio"]["decoded_samples"] > 0
        elif kind == "audio-only":
            assert video is None
        else:
            assert video["decoded_frame_count"] == 25 and video["cfr_status"] == "CFR"
        assert media.read_bytes() == original
