"""Synthetic controls for metadata-only exploratory analysis copies."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from array import array

import pytest

from scripts import analysis_cache as cache
from scripts.probe_manifest import build_manifest

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="Requires FFmpeg")


@pytest.fixture
def inputs(tmp_path):
    movie = tmp_path / "source.mp4"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=96x64:rate=25",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
                    "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=48000", "-t", "3",
                    "-map", "0:v", "-map", "1:a", "-map", "2:a", "-c:v", "libx264", "-c:a", "aac", str(movie)],
                   check=True, capture_output=True, timeout=30)
    build_manifest("synthetic-cache", [("source-1", movie)], tmp_path / "inventory", audio_stream_indices={"source-1": 2})
    manifest = tmp_path / "inventory/manifest.json"
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"schema_version": "2.0.0", "job_id": "synthetic-cache", "request_id": "request-1",
                      "runner": "antigravity", "provider": "gemini", "cloud_upload_allowed": False, "authorization_ref": None,
                      "sources": [{"source_id": "source-1", "ranges": [{"start_ms": 400, "end_ms": 1200}]}],
                      "questions": ["What is visible?"], "requested_categories": ["visual"]}))
    return movie, manifest, request


def test_prepare_reuse_without_frame_scan_or_reencode(inputs, tmp_path, monkeypatch):
    movie, manifest, _ = inputs
    before = hashlib.sha256(movie.read_bytes()).hexdigest()
    commands = []
    real = cache._run
    def observed(command, **options):
        commands.append(command)
        return real(command, **options)
    monkeypatch.setattr(cache, "_run", observed)
    record = cache.prepare_copy(manifest, "source-1", tmp_path / "cache", timeout=30)
    assert not record["reused"]
    assert record["source_audio_stream_index"] == 2
    assert record["exact_frame_correspondence"] == "NOT_RUN"
    assert record["final_export_mapping"] == "NOT_IMPLEMENTED"
    assert all("-show_frames" not in c for c in commands)
    assert "0:2" in next(c for c in commands if "-vf" in c)
    samples = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", record["copy_path"],
                              "-ss", "0.5", "-t", "0.5", "-map", "0:a:0", "-f", "f32le", "-"],
                             check=True, capture_output=True, timeout=30).stdout
    values = array("f"); values.frombytes(samples)
    crossings = sum((a < 0) != (b < 0) for a, b in zip(values, values[1:]))
    assert 800 < crossings < 950  # Selected 880 Hz track, not the 440 Hz backup.
    commands.clear()
    real_sha = cache._sha
    def copy_only_sha(path):
        assert path != movie  # Reuse relies on the original's unchanged signature.
        return real_sha(path)
    monkeypatch.setattr(cache, "_sha", copy_only_sha)
    reused = cache.prepare_copy(manifest, "source-1", tmp_path / "cache", timeout=30)
    assert reused["reused"] and commands == []
    assert hashlib.sha256(movie.read_bytes()).hexdigest() == before


@pytest.mark.parametrize("mode", ["speech", "visual", "audiovisual"])
def test_fast_candidate_clip_all_modes(inputs, tmp_path, mode):
    _, manifest, request = inputs
    r = json.loads(request.read_text())
    r["requested_categories"] = {"speech": ["audible_dialogue"], "visual": ["visual"], "audiovisual": ["visual", "audible_dialogue"]}[mode]
    request.write_text(json.dumps(r))
    report = cache.stage_cached(manifest, request, tmp_path / "clips", cache_root=tmp_path / "cache", timeout=30, preparation_timeout=30, mode=mode)
    clip = report["clips"][0]
    assert report["validation_level"] == "ANALYSIS_METADATA_ONLY"
    assert (clip["source_start_ms"], clip["source_end_ms"], clip["local_end_ms"]) == (400, 1200, 800)
    assert clip["source_start_frame"] == 10 and clip["source_end_frame"] == 30
    assert clip["exact_audio_correspondence"] == "NOT_RUN"
    assert clip["source_audio_stream_index"] == 2
    assert (tmp_path / "clips" / clip["media_path"]).is_file()


@pytest.mark.parametrize("change", ["copy", "record", "source"])
def test_cache_rejects_changed_bindings(inputs, tmp_path, change):
    movie, manifest, _ = inputs
    record = cache.prepare_copy(manifest, "source-1", tmp_path / "cache", timeout=30)
    copy = Path(record["copy_path"])
    if change == "copy":
        with copy.open("ab") as f: f.write(b"changed")
    elif change == "record":
        p = copy.parent / "record.json"
        r = json.loads(p.read_text()); r["invented"] = True; p.write_text(json.dumps(r))
    else:
        with movie.open("ab") as f: f.write(b"changed")
    with pytest.raises(ValueError):
        cache.prepare_copy(manifest, "source-1", tmp_path / "cache", timeout=30)


@pytest.mark.parametrize("start,end", [(401, 1200), (400, 3200)])
def test_unaligned_or_out_of_bounds_candidates_fail(inputs, tmp_path, start, end):
    _, manifest, request = inputs
    r = json.loads(request.read_text());r["sources"][0]["ranges"] = [{"start_ms": start, "end_ms": end}]; request.write_text(json.dumps(r))
    with pytest.raises(ValueError):
        cache.stage_cached(manifest, request, tmp_path / "clips", cache_root=tmp_path / "cache", mode="visual", timeout=30, preparation_timeout=30)
    assert not (tmp_path / "clips").exists()


def test_byte_ceiling_blocks_preparation(inputs, tmp_path):
    _, manifest, _ = inputs
    with pytest.raises(ValueError):
        cache.prepare_copy(manifest, "source-1", tmp_path / "cache", timeout=30, max_copy_bytes=100)
    assert not list((tmp_path / "cache").glob("*/record.json"))


def test_nonzero_reported_origin_is_rejected():
    with pytest.raises(ValueError, match="zero origins"):
        cache._streams({"streams": [{"codec_type": "video", "start_time": "1"}, {"codec_type": "audio", "start_time": "0"}]})


def test_timestamp_seek_extracts_later_scene_not_recording_prefix(tmp_path):
    movie = tmp_path / "two-scenes.mp4"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i", "color=black:s=64x48:r=25:d=1",
                    "-f", "lavfi", "-i", "color=white:s=64x48:r=25:d=1", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
                    "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]", "-map", "[v]", "-map", "2:a", "-t", "2",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(movie)],
                   check=True, capture_output=True, timeout=30)
    build_manifest("synthetic-cache", [("source-1", movie)], tmp_path / "inventory")
    request = {"schema_version": "2.0.0", "job_id": "synthetic-cache", "request_id": "later-scene",
               "runner": "antigravity", "provider": "gemini", "cloud_upload_allowed": False, "authorization_ref": None,
               "sources": [{"source_id": "source-1", "ranges": [{"start_ms": 1200, "end_ms": 1800}]}],
               "requested_categories": ["visual"], "questions": ["What is visible?"]}
    path = tmp_path / "request.json"; path.write_text(json.dumps(request))
    report = cache.stage_cached(tmp_path / "inventory/manifest.json", path, tmp_path / "clips",
                                cache_root=tmp_path / "cache", timeout=30, preparation_timeout=30, mode="visual")
    media = tmp_path / "clips" / report["clips"][0]["media_path"]
    pixels = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(media), "-map", "0:v:0", "-frames:v", "1",
                             "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], check=True, capture_output=True, timeout=30).stdout
    assert len(pixels) == 64 * 48 * 3 and sum(pixels) / len(pixels) > 220
