"""Verify local file identity and decoded video timing; never authorize export."""
from __future__ import annotations

import argparse
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any

from jsonschema.exceptions import SchemaError
from referencing.exceptions import Unresolvable

try:
    from .validate_json import load_json, _unique_object, _reject_constant
    from .check_integrity import check_documents
    from .audio_timing import analyze_aac, analyze_pcm
    from .probe_manifest import (MAX_INTEGER, check_output_directory, file_signature,
                                 positive_integer, positive_rate, run_probe_command)
except ImportError:
    from validate_json import load_json, _unique_object, _reject_constant
    from check_integrity import check_documents
    from audio_timing import analyze_aac, analyze_pcm
    from probe_manifest import (MAX_INTEGER, check_output_directory, file_signature,
                                positive_integer, positive_rate, run_probe_command)


def rational(value: Fraction) -> dict[str, int]:
    return {"num": value.numerator, "den": value.denominator}


def tick(value: Any) -> int | None:
    """Accept actual integer timestamp ticks, including negative origins."""
    if isinstance(value, bool) or not isinstance(value, int) or abs(value) > MAX_INTEGER:
        return None
    return value


def analyze_video(stream: dict, frames: list[dict]) -> dict:
    """Describe observed timing without relying on advertised average/nominal FPS."""
    issues = []
    result = {"decoded_frame_count": len(frames), "cfr_status": "UNKNOWN",
              "fps": None, "origin_seconds": None, "duration_seconds": None,
              "issues": issues}
    base = positive_rate(stream.get("time_base"))
    if not frames:
        issues.append("NO_DECODED_VIDEO")
        return result
    if base is None:
        issues.append("UNKNOWN_TIME_BASE")
        return result
    pts = [tick(frame.get("pts")) for frame in frames]
    durations = [positive_integer(frame.get("duration")) for frame in frames]
    if any(value is None for value in pts):
        issues.append("MISSING_ACTUAL_PTS")
        return result
    result["origin_seconds"] = rational(pts[0] * base)
    if pts[0] != 0:
        issues.append("NONZERO_VIDEO_ORIGIN_UNSUPPORTED")
    deltas = [right - left for left, right in zip(pts, pts[1:])]
    if any(delta <= 0 for delta in deltas):
        issues.append("NONMONOTONIC_PTS")
        return result
    if any(duration is None for duration in durations):
        issues.append("MISSING_FRAME_DURATION")
        return result
    result["duration_seconds"] = rational((pts[-1] + durations[-1] - pts[0]) * base)
    if len(frames) < 2:
        issues.append("INSUFFICIENT_VIDEO_FRAMES")
    elif len(set(deltas)) == 1 and all(duration == deltas[0] for duration in durations):
        result["cfr_status"] = "CFR"
        result["fps"] = rational(1 / (deltas[0] * base))
    else:
        # A one-tick variation may be an otherwise constant grid quantized by the
        # container. Never label that grid confidently CFR or VFR without a map.
        result["cfr_status"] = "VFR" if max(deltas) - min(deltas) > 1 else "UNKNOWN"
        issues.append("IRREGULAR_OR_QUANTIZED_TIMING")
    return result


def summarize_decode(probe: dict, audio_stream_index: int | None = None) -> dict:
    streams, frames = probe.get("streams"), probe.get("frames")
    if not isinstance(streams, list) or not all(isinstance(s, dict) for s in streams):
        raise ValueError("Decode evidence must contain stream objects")
    if not isinstance(frames, list) or not all(isinstance(f, dict) for f in frames):
        raise ValueError("Decode evidence must contain frame objects")
    if any(not isinstance(s.get("disposition", {}), dict) for s in streams):
        raise ValueError("Invalid stream disposition")
    indices = [tick(s.get("index")) for s in streams]
    if any(index is None or index < 0 for index in indices) or len(set(indices)) != len(indices):
        raise ValueError("Stream indices must be distinct nonnegative integers")
    videos = [s for s in streams if s.get("codec_type") == "video"
              and not s.get("disposition", {}).get("attached_pic")]
    audios = [s for s in streams if s.get("codec_type") == "audio"]
    if len(videos) > 1 or not (videos or audios):
        raise ValueError("Exactly one usable video and/or audio stream is supported")
    if audio_stream_index is not None and (type(audio_stream_index) is not int or
                                           audio_stream_index < 0 or audio_stream_index > MAX_INTEGER):
        raise ValueError("Audio stream selector must be a nonnegative integer")
    if len(audios) > 1 and audio_stream_index is None:
        raise ValueError("Multiple audio streams require an explicit selector")
    if audio_stream_index is not None and not any(s["index"] == audio_stream_index for s in audios):
        raise ValueError("Selected stream is absent or not audio")
    by_index = {s["index"]: s for s in streams}
    for frame in frames:
        index = tick(frame.get("stream_index"))
        if index not in by_index or frame.get("media_type") != by_index[index].get("codec_type"):
            raise ValueError("Decoded frame does not match a declared stream")
    video = analyze_video(videos[0], [f for f in frames if f["stream_index"] == videos[0]["index"]]) if videos else None
    audio = None
    issues = list(video["issues"]) if video else []
    if audios:
        stream = (next(s for s in audios if s["index"] == audio_stream_index)
                  if audio_stream_index is not None else audios[0])
        decoded = [f for f in frames if f["stream_index"] == stream["index"]]
        samples = [positive_integer(f.get("nb_samples")) for f in decoded]
        if not decoded or any(sample is None for sample in samples):
            issues.append("MISSING_DECODED_AUDIO_SAMPLES")
        audio = {"stream_index": stream["index"], "decoded_audio_frames": len(decoded),
                 "decoded_samples": sum(samples) if decoded and all(sample is not None for sample in samples) else None,
                 "sample_rate": positive_integer(stream.get("sample_rate")),
                 "channels": positive_integer(stream.get("channels"))}
        audio["timing"] = (analyze_aac(stream, decoded) if stream.get("codec_name") == "aac"
                           else analyze_pcm(stream, decoded))
        if stream.get("codec_name") == "aac" and 'mov' not in probe.get('format', {}).get('format_name', '').split(','):
            audio["timing"]["status"] = "FAIL"
            audio["timing"]["issues"].append("AAC_CONTAINER_UNSUPPORTED")
        if audio["sample_rate"] is None or audio["channels"] is None:
            issues.append("UNKNOWN_AUDIO_FORMAT")
    if video:
        video["stream_index"] = videos[0]["index"]
    return {"video": video, "audio": audio, "issues": issues}


def compare_inventory(source: dict, decoded: dict) -> list[str]:
    issues = []
    video, audio = decoded["video"], decoded["audio"]
    if video:
        if source["frame_count"] is not None and source["frame_count"] != video["decoded_frame_count"]:
            issues.append("FRAME_COUNT_MISMATCH")
        if video["fps"] is not None and source["fps_num"] is not None:
            if Fraction(int(source["fps_num"]), int(source["fps_den"])) != Fraction(video["fps"]["num"], video["fps"]["den"]):
                issues.append("FPS_MISMATCH")
        if source["cfr_status"] != "UNKNOWN" and source["cfr_status"] != video["cfr_status"]:
            issues.append("CFR_STATUS_MISMATCH")
        if video["duration_seconds"] is not None and source["duration_ms"] is not None:
            duration = Fraction(video["duration_seconds"]["num"], video["duration_seconds"]["den"])
            if math.ceil(duration * 1000) != source["duration_ms"]:
                issues.append("VIDEO_DURATION_MISMATCH")
    elif any(source[field] is not None for field in ("frame_count", "fps_num", "fps_den")) or source["cfr_status"] != "UNKNOWN":
        issues.append("VIDEO_METADATA_WITHOUT_VIDEO")
    for field, name in (("audio_sample_rate", "sample_rate"), ("audio_channels", "channels")):
        if source.get(field) is not None and (audio is None or source[field] != audio[name]):
            issues.append("AUDIO_FORMAT_MISMATCH")
    if "audio_stream_index" in source and (audio is None or source["audio_stream_index"] != audio["stream_index"]):
        issues.append("AUDIO_STREAM_INDEX_MISMATCH")
    return issues


def decode_to_file(command: list[str], path: Path, timeout: float, max_bytes: int) -> str:
    """Spool frame JSON to disk; enforce a timeout and a post-run read-size cap."""
    with path.open("xb") as stdout, tempfile.TemporaryFile() as stderr:
        try:
            result = subprocess.run(command, stdout=stdout, stderr=stderr, timeout=timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            raise ValueError("Full media decode timed out") from exc
        stderr.seek(0)
        diagnostic = stderr.read(max_bytes + 1)
        if result.returncode or diagnostic:
            raise ValueError(f"Decode reported errors (exit {result.returncode}): {diagnostic[:4096].decode('utf-8', errors='replace')}")
    if path.stat().st_size > max_bytes:
        raise ValueError("Decode JSON exceeds --max-output-bytes; no evidence loaded")
    return ""


def verify_media(manifest_path: Path, output: Path, ffprobe: str = "ffprobe",
                 timeout: float = 60, max_bytes: int = 64 * 1024 * 1024) -> dict:
    if not math.isfinite(timeout) or timeout <= 0 or not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes <= 0:
        raise ValueError("Timeout and output-byte limit must be finite positive values")
    output = check_output_directory(output)
    manifest_path = manifest_path.expanduser().resolve(strict=True)
    initial_manifest_stat = file_signature(manifest_path)
    raw_manifest = manifest_path.read_bytes()
    manifest = json.loads(raw_manifest.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    errors = check_documents({"manifest": manifest})
    if errors:
        raise ValueError(f"Invalid manifest: {errors[0].code}: {errors[0].message}")
    paths = [Path(s["path"]).expanduser() for s in manifest["sources"]]
    if any(not path.is_absolute() for path in paths):
        raise ValueError("Media verification requires absolute manifest source paths")
    paths = [path.resolve(strict=True) for path in paths]
    if any(not path.is_file() for path in paths):
        raise ValueError("Media sources must be existing regular local files")
    signatures = [file_signature(path) for path in paths]
    if len({sig[:2] for sig in signatures}) != len(paths):
        raise ValueError("Duplicate media file identities")
    executable = shutil.which(ffprobe)
    if executable is None:
        raise ValueError("ffprobe executable unavailable")
    executable = str(Path(executable).resolve())
    version = run_probe_command([executable, "-version"], timeout).stdout
    report = {"job_id": manifest["job_id"], "manifest_sha256": hashlib.sha256(raw_manifest).hexdigest(),
              "status": "PASS", "sources": [],
              "not_checked": ["timeline continuity", "edit audio cuts/synchronization", "proxy mappings",
                              "document references", "permission authenticity", "approval", "export"]}
    # Temporary decode files are external runtime artifacts, never source fixtures.
    with tempfile.TemporaryDirectory(prefix="footage-media-check-") as temporary:
        evidence = []
        for number, (source, path, before) in enumerate(zip(manifest["sources"], paths, signatures), 1):
            digest = hashlib.sha256()
            with path.open("rb") as media:
                for chunk in iter(lambda: media.read(1024 * 1024), b""):
                    digest.update(chunk)
            if source.get("content_sha256") is None or digest.hexdigest() != source["content_sha256"]:
                raise ValueError(f"Missing/mismatched source SHA-256: {source['source_id']}")
            command = [executable, "-v", "error", "-protocol_whitelist", "file",
                       "-format_whitelist", "mov,wav", "-enable_drefs", "0",
                       "-show_frames", "-show_streams", "-show_format", "-show_entries",
                       "frame=stream_index,media_type,pts,duration,nb_samples,sample_fmt,channels,side_data_list,width,height,interlaced_frame", "-of", "json", str(path)]
            raw_path = Path(temporary) / f"decode-{number:04d}.json"
            stderr = decode_to_file(command, raw_path, timeout, max_bytes)
            probe = load_json(raw_path)
            if not isinstance(probe, dict):
                raise ValueError("Decode evidence must be an object")
            media_format = probe.get("format")
            if not isinstance(media_format, dict) or media_format.get("format_name") not in {"mov,mp4,m4a,3gp,3g2,mj2", "wav"}:
                raise ValueError("Only self-contained MOV/MP4-family or WAV inputs are supported")
            decoded = summarize_decode(probe, source.get("audio_stream_index"))
            issues = decoded["issues"] + compare_inventory(source, decoded)
            selected_index = (decoded["video"] or decoded["audio"])["stream_index"]
            selected = next(s for s in probe["streams"] if s["index"] == selected_index)
            measured_base = positive_rate(selected.get("time_base"))
            if source.get("time_base") is not None:
                claimed = source["time_base"]
                if measured_base != Fraction(int(claimed["num"]), int(claimed["den"])):
                    issues.append("TIME_BASE_MISMATCH")
            if source.get("proxy_path") is not None:
                issues.append("PROXY_MAPPING_UNSUPPORTED")
            if file_signature(path) != before:
                raise ValueError(f"Source changed during verification: {path}")
            report["sources"].append({"source_id": source["source_id"], "path": str(path),
                                       "content_sha256": digest.hexdigest(), **decoded,
                                       "issues": issues, "status": "FAIL" if issues else "PASS"})
            if issues:
                report["status"] = "FAIL"
            evidence.append((raw_path, {"source_id": source["source_id"], "command": command,
                                       "ffprobe_version": version, "stderr": stderr,
                                       "stat_signature": list(before), "content_sha256": digest.hexdigest()}))
        if file_signature(manifest_path) != initial_manifest_stat or any(file_signature(path) != sig for path, sig in zip(paths, signatures)):
            raise ValueError("Manifest or source changed during batch verification")
        output.mkdir(parents=True, exist_ok=False)
        for raw_path, provenance in evidence:
            shutil.copyfile(raw_path, output / raw_path.name)
            (output / (raw_path.stem + "-provenance.json")).write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
        temporary_report = output / "media-report.json.tmp"
        temporary_report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        os.link(temporary_report, output / "media-report.json")
        temporary_report.unlink()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--max-output-bytes", type=int, default=64 * 1024 * 1024)
    args = parser.parse_args(argv)
    try:
        report = verify_media(args.manifest, args.output_dir, args.ffprobe, args.timeout, args.max_output_bytes)
    except (OSError, ValueError, SchemaError, Unresolvable) as exc:
        print(f"MEDIA_ERROR: {exc}", file=sys.stderr)
        return 2
    print(f"MEDIA_SCAN_{report['status']}: {args.output_dir.resolve() / 'media-report.json'}")
    print("Media identity/video timing scan; PCM timing recorded separately. Edit audio cuts, timeline, approval, and export NOT_CHECKED")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
