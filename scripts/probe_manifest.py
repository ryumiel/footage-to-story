"""Read local media into a schema-valid manifest with separate probe evidence.

Reported metadata is not decoded frame/timing verification or export readiness.
"""
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
from typing import Any

try:
    from .validate_json import ROOT, build_validator, _unique_object, _reject_constant
except ImportError:  # Direct CLI invocation.
    from validate_json import ROOT, build_validator, _unique_object, _reject_constant

MAX_INTEGER = 9007199254740991


def positive_integer(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    try:
        result = int(value)
    except ValueError:
        return None
    return result if 0 < result <= MAX_INTEGER else None


def positive_rate(value: Any) -> Fraction | None:
    if not isinstance(value, str):
        return None
    try:
        rate = Fraction(value)
    except (ValueError, ZeroDivisionError):
        return None
    return rate if (0 < rate and rate.numerator <= MAX_INTEGER
                    and rate.denominator <= MAX_INTEGER) else None


def duration_ms(value: Any) -> int | None:
    """Round positive reported seconds up to milliseconds, without float math."""
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        return None
    try:
        seconds = Fraction(value)
    except (ValueError, ZeroDivisionError):
        return None
    milliseconds = math.ceil(seconds * 1000)
    return milliseconds if 0 < milliseconds <= MAX_INTEGER else None


def normalize_probe(source_id: str, path: Path, probe: dict, digest: str,
                    evidence_name: str) -> dict:
    streams = probe.get("streams")
    media_format = probe.get("format", {})
    if not isinstance(streams, list) or not all(isinstance(s, dict) for s in streams):
        raise ValueError("ffprobe response must contain an array of stream objects")
    if not isinstance(media_format, dict):
        raise ValueError("ffprobe format must be an object")
    if any(not isinstance(s.get("disposition", {}), dict) for s in streams):
        raise ValueError("ffprobe stream dispositions must be objects")
    videos = [s for s in streams if s.get("codec_type") == "video"
              and not s.get("disposition", {}).get("attached_pic")]
    audios = [s for s in streams if s.get("codec_type") == "audio"]
    if not videos and not audios:
        raise ValueError(f"No usable video/audio stream: {path}")
    if len(videos) > 1 or len(audios) > 1:
        raise ValueError(f"Multiple video/audio streams cannot be represented unambiguously: {path}")
    video = videos[0] if videos else {}
    audio = audios[0] if audios else {}
    rate = positive_rate(video.get("avg_frame_rate"))
    time_base = positive_rate((video or audio).get("time_base"))
    selected = video or audio
    duration = duration_ms(selected.get("duration"))
    duration_origin = "selected stream duration"
    if duration is None:
        duration = duration_ms(media_format.get("duration"))
        duration_origin = "format duration fallback (may include other streams)"
    tags = selected.get("tags", {})
    if not isinstance(tags, dict):
        raise ValueError("ffprobe stream tags must be an object")
    timecode = tags.get("timecode")
    if not isinstance(timecode, str) or not timecode.strip():
        timecode = None
    return {
        "source_id": source_id, "path": str(path),
        "duration_ms": duration,
        "fps_num": rate.numerator if rate else None,
        "fps_den": rate.denominator if rate else None,
        "frame_count": positive_integer(video.get("nb_frames")),
        "cfr_status": "UNKNOWN",
        "audio_sample_rate": positive_integer(audio.get("sample_rate")),
        "audio_channels": positive_integer(audio.get("channels")),
        "content_sha256": digest, "source_start_timecode": timecode,
        "time_base": {"num": time_base.numerator, "den": time_base.denominator} if time_base else None,
        "proxy_path": None,
        "notes": [
            f"Raw metadata and command provenance: {evidence_name}; source_id supplied by caller.",
            f"Selected video stream index: {video.get('index')}; audio stream index: {audio.get('index')}.",
            f"duration_ms: {duration_origin}, rounded up; null means unavailable.",
            "FPS: selected video avg_frame_rate; frame_count: reported nb_frames only, never duration multiplied by FPS.",
            "Audio fields: selected audio sample_rate/channels; time_base: selected video or audio time_base; timecode: selected stream tags.timecode.",
            "content_sha256: exact local file bytes; source stat checked before and after probing/hashing.",
            "CFR/VFR and decoded frame bounds have not been verified; metadata does not authorize export.",
        ],
    }


def run_probe_command(command: list[str], timeout: float) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise ValueError(f"ffprobe timed out after {timeout} seconds") from exc
    if result.returncode:
        raise ValueError(f"ffprobe exited {result.returncode}: {result.stderr.strip()}")
    return result


def file_signature(path: Path) -> tuple[int, ...]:
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def check_output_directory(output: Path) -> Path:
    output = output.resolve()
    if output == ROOT or (ROOT in output.parents and
                          not any(root in output.parents for root in (ROOT / "work", ROOT / "artifacts"))):
        raise ValueError("Output inside the repository must be below work/ or artifacts/; external storage is also allowed")
    if output.exists():
        raise ValueError(f"Output directory already exists; choose a new run directory: {output}")
    return output


def build_manifest(job_id: str, sources: list[tuple[str, Path]], output: Path,
                   ffprobe: str = "ffprobe", timeout: float = 30) -> dict:
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Timeout must be a finite positive number")
    output = check_output_directory(output)
    validator = build_validator(ROOT / "schemas/2.0.0/manifest.schema.json")
    # Validate caller identifiers before invoking external programs.
    manifest = {"schema_version": "2.0.0", "job_id": job_id, "sources": [
        {"source_id": sid, "path": str(path), "duration_ms": None,
         "fps_num": None, "fps_den": None, "frame_count": None, "cfr_status": "UNKNOWN"}
        for sid, path in sources
    ]}
    errors = list(validator.iter_errors(manifest))
    if errors:
        raise ValueError(f"Invalid manifest inputs: {errors[0].message}")
    if len({sid for sid, _ in sources}) != len(sources):
        raise ValueError("Duplicate source IDs")
    resolved = [(sid, path.expanduser().resolve(strict=True)) for sid, path in sources]
    if any(not path.is_file() for _, path in resolved):
        raise ValueError("All sources must be existing local regular files")
    signatures = [file_signature(path) for _, path in resolved]
    if len({sig[:2] for sig in signatures}) != len(sources):
        raise ValueError("Duplicate source files (including aliases/hard links)")
    executable = shutil.which(ffprobe)
    if executable is None:
        raise ValueError(f"ffprobe executable unavailable: {ffprobe}")
    executable = str(Path(executable).resolve())
    version = run_probe_command([executable, "-version"], timeout).stdout
    evidence = []
    manifest["sources"] = []
    for number, ((sid, path), before) in enumerate(zip(resolved, signatures), 1):
        command = [executable, "-v", "error", "-protocol_whitelist", "file",
                   "-show_format", "-show_streams", "-of", "json", str(path)]
        result = run_probe_command(command, timeout)
        # Apply the same strict parser hygiene as the contract validator.
        probe = json.loads(result.stdout, object_pairs_hook=_unique_object,
                           parse_constant=_reject_constant)
        if not isinstance(probe, dict):
            raise ValueError("ffprobe response must be an object")
        digest = hashlib.sha256()
        with path.open("rb") as media:
            for chunk in iter(lambda: media.read(1024 * 1024), b""):
                digest.update(chunk)
        if file_signature(path) != before:
            raise ValueError(f"Source changed while probing/hashing: {path}")
        evidence_name = f"probe-{number:04d}.json"
        manifest["sources"].append(normalize_probe(sid, path, probe, digest.hexdigest(), evidence_name))
        evidence.append((evidence_name, {
            "source_id": sid, "path": str(path), "command": command,
            "ffprobe_version": version, "stdout": result.stdout, "stderr": result.stderr,
            "content_sha256": digest.hexdigest(), "stat_signature": list(before),
        }))
    errors = list(validator.iter_errors(manifest))
    if errors:
        raise ValueError(f"Generated manifest failed schema validation: {errors[0].message}")
    # Recheck all files after the whole batch; no writes on probe/validation failure.
    if any(file_signature(path) != sig for (_, path), sig in zip(resolved, signatures)):
        raise ValueError("Source changed during batch")
    output.mkdir(parents=True, exist_ok=False)
    for name, document in evidence + [("manifest.json", manifest)]:
        temporary = output / (name + ".tmp")
        with temporary.open("x", encoding="utf-8") as destination:
            destination.write(json.dumps(document, indent=2, ensure_ascii=False) + "\n")
        # Publish complete bytes without replacing an existing destination.
        os.link(temporary, output / name)
        temporary.unlink()
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--source", nargs=2, action="append", required=True, metavar=("ID", "PATH"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args(argv)
    try:
        build_manifest(args.job_id, [(sid, Path(path)) for sid, path in args.source],
                       args.output_dir, args.ffprobe, args.timeout)
    except (OSError, ValueError) as exc:
        print(f"MANIFEST_ERROR: {exc}", file=sys.stderr)
        return 2
    print(f"MANIFEST_WRITTEN: {args.output_dir.resolve() / 'manifest.json'}")
    print("SCHEMA_VALID; reported metadata only; timing, approval, and export NOT_IMPLEMENTED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
