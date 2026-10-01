"""Synthetic media tests for bounded local analysis staging."""
from __future__ import annotations

import json
from pathlib import Path
import os
import shutil
import subprocess
import sys
import time

import pytest

from scripts.probe_manifest import build_manifest
from scripts.stage_analysis_media import _check_audio_contiguity, _run, stage_media


pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
                                reason="Requires local FFmpeg tools")


@pytest.fixture
def input_pair(tmp_path: Path) -> tuple[Path, Path, Path]:
    movie = tmp_path / "source.mov"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                    "testsrc=size=64x48:rate=25", "-f", "lavfi", "-i",
                    "sine=frequency=440:sample_rate=48000", "-t", "2", "-c:v", "mpeg4",
                    "-pix_fmt", "yuv420p", "-c:a", "libmp3lame", str(movie)],
                   check=True, capture_output=True, timeout=30)
    inventory = tmp_path / "inventory"
    build_manifest("synthetic-job", [("src-1", movie)], inventory)
    request = {"schema_version": "2.0.0", "job_id": "synthetic-job", "request_id": "req-1",
               "runner": "antigravity", "provider": "gemini", "cloud_upload_allowed": False,
               "authorization_ref": None,
               "sources": [{"source_id": "src-1", "ranges": [{"start_ms": 400, "end_ms": 1200}]}],
               "questions": ["What speech is audible?"], "requested_categories": ["audible_dialogue"]}
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    return movie, inventory / "manifest.json", request_path


def test_stage_compressed_clip_and_immutable_mapping(input_pair, tmp_path):
    movie, manifest, request = input_pair
    original = movie.read_bytes()
    output = tmp_path / "staged"
    report = stage_media(manifest, request, output)
    assert report["status"] == "PASS"
    clip = report["clips"][0]
    assert (clip["source_start_frame"], clip["source_end_frame"]) == (10, 30)
    assert (clip["source_start_ms"], clip["source_end_ms"], clip["local_end_ms"]) == (400, 1200, 800)
    assert clip["decoded_samples"] == 38400
    assert clip["waveform_correlation"] > .98
    assert (output / clip["audio_path"]).read_bytes().startswith(b"ID3")
    assert json.loads((output / "mapping.json").read_text()) == report
    assert movie.read_bytes() == original
    with pytest.raises(ValueError, match="already exists"):
        stage_media(manifest, request, output)


@pytest.mark.parametrize("change,match", [
    ("unaligned", "align"), ("overlap", "Overlapping"),
    ("too_long", "duration exceeds"), ("changed", "hash mismatch"),
    ("proxy", "no proxies"),
])
def test_stage_fails_closed_without_output(input_pair, tmp_path, change, match):
    movie, manifest_path, request_path = input_pair
    request = json.loads(request_path.read_text())
    if change == "unaligned":
        request["sources"][0]["ranges"][0]["start_ms"] = 401
    elif change == "overlap":
        request["sources"][0]["ranges"].append({"start_ms": 800, "end_ms": 1600})
    elif change == "too_long":
        request["sources"][0]["ranges"][0] = {"start_ms": 0, "end_ms": 1600}
    elif change == "changed":
        movie.write_bytes(movie.read_bytes() + b"x")
    elif change == "proxy":
        manifest = json.loads(manifest_path.read_text())
        manifest["sources"][0]["proxy_path"] = str(movie)
        manifest_path.write_text(json.dumps(manifest))
    if change in {"unaligned", "overlap", "too_long"}:
        request_path.write_text(json.dumps(request))
    output = tmp_path / "staged"
    with pytest.raises(ValueError, match=match):
        stage_media(manifest_path, request_path, output,
                    max_total_seconds=1 if change == "too_long" else 60)
    assert not output.exists()


def test_stage_rejects_audio_with_nonzero_origin(input_pair, tmp_path):
    original, _, request = input_pair
    shifted = tmp_path / "shifted.mov"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(original),
                    "-itsoffset", "0.2", "-i", str(original), "-map", "0:v:0", "-map", "1:a:0",
                    "-c", "copy", str(shifted)], check=True, capture_output=True, timeout=30)
    inventory = tmp_path / "shifted-inventory"
    build_manifest("synthetic-job", [("src-1", shifted)], inventory)
    output = tmp_path / "staged"
    with pytest.raises(ValueError, match="nonzero origin"):
        stage_media(inventory / "manifest.json", request, output)
    assert not output.exists()


def test_stage_rejects_vfr_video(input_pair, tmp_path):
    original, _, request = input_pair
    irregular = tmp_path / "irregular.mov"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(original),
                    "-vf", "setpts=if(lt(N\\,10)\\,PTS\\,PTS+(N-10)*512)", "-fps_mode", "vfr",
                    "-c:v", "mpeg4", "-c:a", "copy", str(irregular)],
                   check=True, capture_output=True, timeout=30)
    inventory = tmp_path / "irregular-inventory"
    build_manifest("synthetic-job", [("src-1", irregular)], inventory)
    output = tmp_path / "staged"
    with pytest.raises(ValueError, match="Unsupported video timing"):
        stage_media(inventory / "manifest.json", request, output)
    assert not output.exists()


def test_stage_clip_byte_budget_leaves_no_partial_bundle(input_pair, tmp_path):
    _, manifest, request = input_pair
    output = tmp_path / "staged"
    with pytest.raises(ValueError, match="limit|byte"):
        stage_media(manifest, request, output, max_clip_bytes=100)
    assert not output.exists()


def test_media_tool_timeout_kills_child_process(tmp_path):
    started = time.monotonic()
    with pytest.raises(ValueError, match="timed out"):
        _run([sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.1,
             max_bytes=1024, output=tmp_path / "stdout")
    assert time.monotonic() - started < 2


def test_media_tool_rejects_zero_exit_stderr(tmp_path):
    with pytest.raises(ValueError, match="reported errors"):
        _run([sys.executable, "-c", "import sys; sys.stderr.write('decode error\\n')"],
             timeout=2, max_bytes=1024, output=tmp_path / "stdout")


@pytest.mark.parametrize("exit_status", [0, 7])
def test_media_tool_reaps_children_after_leader_exits(tmp_path, exit_status):
    marker = tmp_path / "survived"
    child = f"import time, pathlib; time.sleep(0.7); pathlib.Path({str(marker)!r}).write_text('survived')"
    parent = ("import subprocess, sys; "
              f"subprocess.Popen([sys.executable, '-c', {child!r}]); sys.exit({exit_status})")
    command = [sys.executable, "-c", parent]
    if exit_status:
        with pytest.raises(ValueError, match="reported errors"):
            _run(command, timeout=2, max_bytes=1024, output=tmp_path / "stdout")
    else:
        _run(command, timeout=2, max_bytes=1024, output=tmp_path / "stdout")
    time.sleep(0.9)
    assert not marker.exists()


@pytest.mark.parametrize("frames,match", [
    ([{"pts": 0, "nb_samples": 100}, {"pts": 101, "nb_samples": 100}], "gap"),
    ([{"pts": 0, "nb_samples": 100}, {"pts": 99, "nb_samples": 100}], "overlap"),
    ([{"pts": 0, "nb_samples": 100}, {"pts": 0, "nb_samples": 100}], "overlap"),
    ([{"pts": 0, "nb_samples": 100}, {"nb_samples": 100}], "Missing audio PTS"),
    ([{"pts": 0, "nb_samples": 100}, {"pts": 100}], "sample count"),
])
def test_decoded_audio_requires_exact_sample_clock(frames, match):
    stream = {"time_base": "1/1000", "sample_rate": "1000", "channels": 2}
    with pytest.raises(ValueError, match=match):
        _check_audio_contiguity(stream, frames)


def test_decoded_audio_rejects_unknown_or_multichannel():
    frames = [{"pts": 0, "nb_samples": 100}]
    with pytest.raises(ValueError, match="Unsupported audio format"):
        _check_audio_contiguity({"time_base": "1/1000", "sample_rate": "1000", "channels": 3}, frames)
    assert _check_audio_contiguity({"time_base": "1/1000", "sample_rate": "1000", "channels": 2},
                                   frames) == (1000, 2, 100)


def test_metadata_fifo_and_source_symlink_fail_without_opening_media(input_pair, tmp_path):
    movie, manifest, request = input_pair
    fifo = tmp_path / "request-fifo"
    os.mkfifo(fifo)
    started = time.monotonic()
    with pytest.raises(ValueError, match="regular file"):
        stage_media(manifest, fifo, tmp_path / "fifo-output")
    assert time.monotonic() - started < 2
    alias = tmp_path / "alias.mov"
    alias.symlink_to(movie)
    document = json.loads(manifest.read_text())
    document["sources"][0]["path"] = str(alias)
    manifest.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="symlinks"):
        stage_media(manifest, request, tmp_path / "alias-output")


def test_exclusive_output_lock_prevents_concurrent_publication(input_pair, tmp_path):
    _, manifest, request = input_pair
    output = tmp_path / "staged"
    lock = tmp_path / "staged.lock"
    lock.write_text("existing run")
    with pytest.raises(FileExistsError):
        stage_media(manifest, request, output)
    assert lock.read_text() == "existing run"
    assert not output.exists()


def test_staged_audio_excludes_source_metadata_and_chapters(input_pair, tmp_path):
    original, _, request = input_pair
    metadata = tmp_path / "private.ffmetadata"
    metadata.write_text(";FFMETADATA1\n"
                        "title=SECRET_GLOBAL_TITLE\n"
                        "comment=SECRET_GLOBAL_COMMENT\n"
                        "location=SECRET_GLOBAL_LOCATION\n"
                        "[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=1500\n"
                        "title=SECRET_CHAPTER\n", encoding="utf-8")
    tagged = tmp_path / "tagged.mov"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(original),
                    "-f", "ffmetadata", "-i", str(metadata),
                    "-map", "0:v:0", "-map", "0:a:0", "-map_metadata", "1",
                    "-map_chapters", "1", "-metadata:s:a:0", "title=SECRET_STREAM_TITLE",
                    "-metadata:s:a:0", "comment=SECRET_STREAM_COMMENT",
                    "-metadata:s:a:0", "handler_name=SECRET_STREAM_COMMENT",
                    "-movflags", "use_metadata_tags", "-c", "copy", str(tagged)],
                   check=True, capture_output=True, timeout=30)
    def probe(path):
        raw = subprocess.check_output(["ffprobe", "-v", "error", "-show_format",
                                       "-show_streams", "-show_chapters", "-of", "json", str(path)],
                                      timeout=30)
        return json.loads(raw)
    source_probe = probe(tagged)
    source_text = json.dumps(source_probe)
    sentinels = ["SECRET_GLOBAL_TITLE", "SECRET_GLOBAL_COMMENT", "SECRET_GLOBAL_LOCATION",
                 "SECRET_STREAM_TITLE", "SECRET_STREAM_COMMENT", "SECRET_CHAPTER"]
    assert all(sentinel in source_text for sentinel in sentinels)
    inventory = tmp_path / "tagged-inventory"
    build_manifest("synthetic-job", [("src-1", tagged)], inventory)
    output = tmp_path / "staged"
    clip = stage_media(inventory / "manifest.json", request, output)["clips"][0]
    staged_probe = probe(output / clip["audio_path"])
    staged_text = json.dumps(staged_probe)
    assert not staged_probe.get("chapters")
    assert all(sentinel not in staged_text for sentinel in sentinels)
