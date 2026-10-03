"""Reusable resized media for exploratory analysis, without decoded-source proof.

This path checks reported metadata and conversion success. It deliberately does
not establish exact original-frame correspondence or authorize final exports.
"""
from __future__ import annotations

import argparse
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import tempfile
import os

from .check_integrity import check_documents
from .probe_manifest import check_output_directory, file_signature, positive_rate
from .stage_analysis_media import (_exclusive_output_lock, _load_document, _read_regular,
                                   _run, _sha, _video_layout)
from .validate_json import ROOT, build_validator

VERSION = "analysis-cache-1"
SCHEMA = ROOT / "schemas/2.0.0/analysis-cache.schema.json"


def _storage(path: Path, job_id: str) -> Path:
    if path.is_symlink():
        raise ValueError("Storage symlinks are unsupported")
    path = path.resolve()
    if path == ROOT or ROOT in path.parents:
        relative = path.relative_to(ROOT)
        if len(relative.parts) < 3 or relative.parts[:2] not in [("work", job_id), ("artifacts", job_id)]:
            raise ValueError("Repository runtime output requires work/job_id or artifacts/job_id")
    return path


def _probe(path: Path, directory: Path, name: str, timeout: float) -> dict:
    output = directory / name
    _run(["ffprobe", "-v", "error", "-protocol_whitelist", "file", "-enable_drefs", "0",
          "-show_streams", "-show_format", "-of", "json", str(path)],
         timeout=timeout, max_bytes=1024 * 1024, output=output)
    return _load_document(output, 1024 * 1024)


def _streams(probe: dict, audio_index: int | None = None) -> tuple[dict, dict]:
    videos = [s for s in probe.get("streams", []) if s.get("codec_type") == "video"
              and not s.get("disposition", {}).get("attached_pic")]
    audios = [s for s in probe.get("streams", []) if s.get("codec_type") == "audio"
              and (audio_index is None or s.get("index") == audio_index)]
    if len(videos) != 1 or len(audios) != 1:
        raise ValueError("Requires one video and an unambiguous selected audio stream")
    video, audio = videos[0], audios[0]
    for stream in (video, audio):
        if "start_time" not in stream or Fraction(stream["start_time"]) != 0:
            raise ValueError("Fast analysis requires reported zero origins")
    fps = positive_rate(video.get("avg_frame_rate"))
    if fps is None or fps != positive_rate(video.get("r_frame_rate")):
        raise ValueError("Unknown or inconsistent reported frame rate")
    if int(audio.get("sample_rate", 0)) <= 0 or audio.get("channels") not in (1, 2):
        raise ValueError("Unsupported selected audio format")
    return video, audio


def _duration(stream: dict) -> Fraction:
    duration = Fraction(stream.get("duration", "0"))
    if duration <= 0:
        raise ValueError("Stream duration is unknown")
    return duration


def _valid_record(record: dict) -> None:
    errors = list(build_validator(SCHEMA).iter_errors(record))
    if errors:
        raise ValueError(f"Invalid analysis cache record: {errors[0].message}")


def prepare_copy(manifest_path: Path, source_id: str, cache_root: Path, *,
                 timeout: float = 3600, decoder: str = "software",
                 max_copy_bytes: int = 2 * 1024**3) -> dict:
    """Create or reuse a byte-bound copy; metadata acceptance is not source proof."""
    if decoder not in {"software", "videotoolbox"}:
        raise ValueError("Unsupported decoder")
    if type(timeout) not in (int, float) or not 0 < timeout < float("inf") or type(max_copy_bytes) is not int or max_copy_bytes <= 0:
        raise ValueError("Invalid preparation limits")
    manifest_path = Path(manifest_path).absolute()
    raw = _read_regular(manifest_path, 4 * 1024**2)
    manifest = _load_document(manifest_path)
    problems = check_documents({"manifest": manifest})
    if problems:
        raise ValueError(f"Invalid manifest: {problems[0]}")
    sources = [s for s in manifest["sources"] if s["source_id"] == source_id]
    if len(sources) != 1:
        raise ValueError("Unknown source")
    source = sources[0]
    if source.get("cfr_status") == "VFR":
        raise ValueError("Known variable-rate source is unsupported by fast mapping")
    path = Path(source["path"])
    if not path.is_absolute() or path.is_symlink() or source.get("proxy_path") is not None or not source.get("content_sha256"):
        raise ValueError("Requires absolute hashed original without proxy")
    signature = file_signature(path)
    manifest_hash = hashlib.sha256(raw).hexdigest()
    key = hashlib.sha256(f"{VERSION}:{manifest_hash}:{source_id}:{decoder}".encode()).hexdigest()
    cache_root = _storage(Path(cache_root), manifest["job_id"])
    cache_root.mkdir(parents=True, exist_ok=True)
    target = cache_root / key
    with _exclusive_output_lock(target):
        if target.exists():
            if target.is_symlink():
                raise ValueError("Cache directory symlinks are unsupported")
            record = _load_document(target / "record.json")
            _valid_record(record)
            if (record["version"] != VERSION or record["manifest_sha256"] != manifest_hash
                or record["source_id"] != source_id or record["source_path"] != str(path)
                or record["source_sha256"] != source["content_sha256"]
                or record["decoder"] != decoder or record["source_signature"] != list(signature)
                or (record["fps_num"], record["fps_den"]) != (source["fps_num"], source["fps_den"])
                or (record["sample_rate"], record["channels"]) != (source["audio_sample_rate"], source["audio_channels"])
                or (source.get("audio_stream_index") is not None and record["source_audio_stream_index"] != source["audio_stream_index"])
                or abs(record["duration_ms"] - source["duration_ms"]) > 101
                or _sha(target / "analysis.mp4") != record["copy_sha256"]):
                raise ValueError("Analysis copy is stale or changed; prepare a new cache directory")
            if (target / "analysis.mp4").stat().st_size > max_copy_bytes:
                raise ValueError("Analysis copy exceeds byte limit")
            if _read_regular(manifest_path, 4 * 1024**2) != raw:
                raise ValueError("Manifest changed")
            return {**record, "copy_path": str(target / "analysis.mp4"), "reused": True}
        if _sha(path) != source["content_sha256"] or file_signature(path) != signature:
            raise ValueError("Source differs from manifest")
        with tempfile.TemporaryDirectory(prefix="analysis-copy-", dir=cache_root) as name:
            temporary = Path(name)
            probe = _probe(path, temporary, "source-probe.json", min(timeout, 60))
            if probe.get("format", {}).get("format_name") != "mov,mp4,m4a,3gp,3g2,mj2":
                raise ValueError("Fast analysis supports self-contained MOV/MP4 only")
            video, audio = _streams(probe, source.get("audio_stream_index"))
            fps = positive_rate(video["avg_frame_rate"])
            if fps != Fraction(source["fps_num"], source["fps_den"]):
                raise ValueError("Reported source FPS differs from manifest")
            if (int(audio["sample_rate"]) != source["audio_sample_rate"] or audio["channels"] != source["audio_channels"]
                or abs(_duration(video) * 1000 - source["duration_ms"]) > 1):
                raise ValueError("Reported source duration or audio differs from manifest")
            if video.get("pix_fmt") not in {"yuv420p", "yuv420p10le"}:
                raise ValueError("Unsupported analysis pixel format")
            if video["pix_fmt"] == "yuv420p10le" and any(video.get(k) != "bt709" for k in ("color_space", "color_primaries", "color_transfer")):
                raise ValueError("10-bit analysis requires explicit BT.709 tags")
            _, _, width, height, _, transform = _video_layout(video["width"], video["height"])
            copy = temporary / "analysis.mp4"
            command = ["ffmpeg", "-nostdin", "-v", "error", "-protocol_whitelist", "file"]
            if decoder == "videotoolbox":
                command += ["-hwaccel", "videotoolbox"]
            command += ["-i", str(path), "-map", f"0:{video['index']}", "-map", f"0:{audio['index']}",
                        "-vf", transform, "-map_metadata", "-1", "-map_metadata:s", "-1", "-map_chapters", "-1",
                        "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
                        "-fps_mode:v", "passthrough", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(copy)]
            _run(command, timeout=timeout, max_bytes=1024**2, output=temporary / "encode.log",
                 bounded_file=copy, bounded_file_bytes=max_copy_bytes)
            rendered = _probe(copy, temporary, "copy-probe.json", min(timeout, 60))
            cv, ca = _streams(rendered)
            if (positive_rate(cv["avg_frame_rate"]) != fps or (cv["width"], cv["height"]) != (width, height)
                or int(ca["sample_rate"]) != int(audio["sample_rate"]) or ca["channels"] != audio["channels"]
                or abs(_duration(cv) - _duration(video)) > Fraction(1, 10)
                or abs(_duration(ca) - _duration(audio)) > Fraction(1, 10)):
                raise ValueError("Analysis copy metadata differs beyond tolerance")
            if file_signature(path) != signature or _sha(path) != source["content_sha256"] or _read_regular(manifest_path, 4 * 1024**2) != raw:
                raise ValueError("Source or manifest changed during preparation")
            record = {"version": VERSION, "job_id": manifest["job_id"], "source_id": source_id,
                      "manifest_sha256": manifest_hash, "source_path": str(path), "source_sha256": source["content_sha256"],
                      "source_signature": list(signature), "copy_sha256": _sha(copy), "copy_size_bytes": copy.stat().st_size,
                      "source_audio_stream_index": audio["index"], "fps_num": fps.numerator, "fps_den": fps.denominator,
                      "sample_rate": int(audio["sample_rate"]), "channels": audio["channels"],
                      "width": width, "height": height, "duration_ms": int(_duration(cv) * 1000),
                      "decoder": decoder, "validation_level": "ANALYSIS_METADATA_ONLY",
                      "exact_frame_correspondence": "NOT_RUN", "exact_audio_correspondence": "NOT_RUN",
                      "final_export_mapping": "NOT_IMPLEMENTED"}
            _valid_record(record)
            (temporary / "record.json").write_text(json.dumps(record, indent=2) + "\n")
            os.rename(temporary, target)
    return {**record, "copy_path": str(target / "analysis.mp4"), "reused": False}


def stage_cached(manifest_path: Path, request_path: Path, output_dir: Path, *, cache_root: Path,
                 timeout: float = 60, max_total_seconds: int = 60,
                 max_clip_bytes: int = 20 * 1024**2, mode: str = "speech",
                 preparation_timeout: float = 3600, decoder: str = "software") -> dict:
    """Timestamp-based candidates; exact original cut verification remains NOT_RUN."""
    if mode not in {"speech", "visual", "audiovisual"} or type(max_total_seconds) is not int or max_total_seconds <= 0 or type(max_clip_bytes) is not int or max_clip_bytes <= 0 or type(timeout) not in (int, float) or not 0 < timeout < float("inf"):
        raise ValueError("Invalid fast staging mode or limits")
    mr = _read_regular(Path(manifest_path), 4 * 1024**2)
    rr = _read_regular(Path(request_path), 4 * 1024**2)
    manifest, request = _load_document(Path(manifest_path)), _load_document(Path(request_path))
    problems = check_documents({"manifest": manifest, "analysis-request": request})
    if problems:
        raise ValueError(f"Invalid staging inputs: {problems[0]}")
    categories = request["requested_categories"]
    speech = {"speech", "dialogue", "audible_dialogue"}
    if ((mode == "speech" and (not categories or not set(categories) <= speech))
        or (mode == "visual" and categories != ["visual"])
        or (mode == "audiovisual" and (len(categories) != 2 or "visual" not in categories or len(set(categories) & speech) != 1))):
        raise ValueError("Request categories differ from analysis mode")
    ranges = []
    for entry in request["sources"]:
        previous = -1
        for interval in sorted(entry["ranges"], key=lambda r: r["start_ms"]):
            if interval["start_ms"] < previous:
                raise ValueError("Overlapping ranges")
            previous = interval["end_ms"]
            ranges.append((entry["source_id"], interval["start_ms"], interval["end_ms"]))
    if len(ranges) > 64 or sum(end - start for _, start, end in ranges) > max_total_seconds * 1000:
        raise ValueError("Fast staging exceeds range/duration budget")
    output_dir = check_output_directory(Path(output_dir))
    _storage(output_dir, manifest["job_id"])
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    copies = {sid: prepare_copy(Path(manifest_path), sid, Path(cache_root), timeout=preparation_timeout, decoder=decoder) for sid in {sid for sid, _, _ in ranges}}
    with _exclusive_output_lock(output_dir), tempfile.TemporaryDirectory(prefix="analysis-clips-", dir=output_dir.parent) as name:
        temporary = Path(name)
        clips = []
        for number, (sid, start, end) in enumerate(ranges, 1):
            copy = copies[sid]
            fps = Fraction(copy["fps_num"], copy["fps_den"])
            first, last = Fraction(start, 1000) * fps, Fraction(end, 1000) * fps
            if first.denominator != 1 or last.denominator != 1 or Fraction(start * copy["sample_rate"], 1000).denominator != 1 or Fraction(end * copy["sample_rate"], 1000).denominator != 1 or end > copy["duration_ms"]:
                raise ValueError("Range exceeds analysis copy or is not frame/sample aligned")
            filename = f"clip-{number:04d}.{'mp3' if mode == 'speech' else 'mp4'}"
            media = temporary / filename
            command = ["ffmpeg", "-nostdin", "-v", "error", "-protocol_whitelist", "file", "-ss", f"{start / 1000:.3f}",
                       "-i", copy["copy_path"], "-t", f"{(end-start) / 1000:.3f}", "-map", "0:a:0",
                       "-map_metadata", "-1", "-map_metadata:s", "-1", "-map_chapters", "-1"]
            if mode == "speech":
                command += ["-vn", "-c:a", "libmp3lame", "-q:a", "2"]
            else:
                command += ["-map", "0:v:0", "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-fps_mode:v", "passthrough", "-c:a", "aac", "-b:a", "192k"]
            command += [str(media)]
            _run(command, timeout=timeout, max_bytes=1024**2, output=temporary / f"encode-{number}.log", bounded_file=media, bounded_file_bytes=max_clip_bytes)
            probe = _probe(media, temporary, f"probe-{number}.json", timeout)
            audios = [s for s in probe.get("streams", []) if s.get("codec_type") == "audio"]
            if len(audios) != 1 or abs(_duration(audios[0]) - Fraction(end-start, 1000)) > Fraction(1, 10) or int(audios[0]["sample_rate"]) != copy["sample_rate"] or audios[0]["channels"] != copy["channels"]:
                raise ValueError("Staged audio metadata differs beyond tolerance")
            if mode != "speech":
                v, _ = _streams(probe)
                if positive_rate(v["avg_frame_rate"]) != fps or (v["width"], v["height"]) != (copy["width"], copy["height"]) or abs(_duration(v)-Fraction(end-start,1000)) > Fraction(1,10):
                    raise ValueError("Staged video metadata differs beyond tolerance")
            digest = _sha(media)
            clips.append({"clip_id": f"clip-{number:04d}", "source_id": sid, "source_path": copy["source_path"], "source_sha256": copy["source_sha256"],
                          "source_start_ms": start, "source_end_ms": end, "source_start_frame": int(first), "source_end_frame": int(last),
                          "local_start_ms": 0, "local_end_ms": end-start, "source_audio_stream_index": copy["source_audio_stream_index"],
                          "source_signature": copy["source_signature"],
                          "audio_path": filename, "audio_sha256": digest, "audio_size_bytes": media.stat().st_size,
                          "media_path": filename, "media_sha256": digest, "media_size_bytes": media.stat().st_size,
                          "media_kind": "speech" if mode == "speech" else "audiovisual", "analysis_copy_sha256": copy["copy_sha256"],
                          "validation_level": "ANALYSIS_METADATA_ONLY", "exact_frame_correspondence": "NOT_RUN", "exact_audio_correspondence": "NOT_RUN"})
        if _read_regular(Path(manifest_path),4*1024**2)!=mr or _read_regular(Path(request_path),4*1024**2)!=rr:
            raise ValueError("Staging inputs changed")
        for copy in copies.values():
            if file_signature(Path(copy["source_path"])) != tuple(copy["source_signature"]) or _sha(Path(copy["copy_path"])) != copy["copy_sha256"]:
                raise ValueError("Source or analysis copy changed during staging")
        report = {"job_id": manifest["job_id"], "request_id": request["request_id"], "manifest_sha256": hashlib.sha256(mr).hexdigest(),
                  "request_sha256": hashlib.sha256(rr).hexdigest(), "status": "PASS", "validation_level": "ANALYSIS_METADATA_ONLY", "clips": clips}
        (temporary / "mapping.json").write_text(json.dumps(report, indent=2)+"\n")
        if output_dir.exists():
            raise ValueError("Output directory exists")
        os.rename(temporary, output_dir)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--cache-root", required=True, type=Path)
    parser.add_argument("--timeout", type=float, default=3600)
    parser.add_argument("--decoder", choices=("software", "videotoolbox"), default="software")
    args = parser.parse_args()
    print(json.dumps(prepare_copy(args.manifest,args.source_id,args.cache_root,timeout=args.timeout,decoder=args.decoder),indent=2))


if __name__ == "__main__":
    main()
