"""Stage bounded, verified local speech clips from zero-origin CFR sources."""
from __future__ import annotations

import argparse
from array import array
from contextlib import contextmanager
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time

try:
    from .check_integrity import check_documents
    from .probe_manifest import check_output_directory, file_signature, positive_rate
    from .validate_json import _reject_constant, _unique_object
    from .verify_media import compare_inventory, summarize_decode
except ImportError:
    from check_integrity import check_documents
    from probe_manifest import check_output_directory, file_signature, positive_rate
    from validate_json import _reject_constant, _unique_object
    from verify_media import compare_inventory, summarize_decode


def _read_regular(path: Path, maximum: int) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0))
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > maximum:
            raise ValueError("Input must be a bounded regular file")
        chunks = []
        count = 0
        while chunk := os.read(descriptor, min(1024 * 1024, maximum + 1 - count)):
            chunks.append(chunk)
            count += len(chunk)
            if count > maximum:
                raise ValueError("Input exceeds byte limit")
        after = os.fstat(descriptor)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError("Input changed during read")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _load_document(path: Path, maximum: int = 4 * 1024 * 1024) -> dict:
    raw = _read_regular(path, maximum)
    document = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                          parse_constant=_reject_constant)
    if not isinstance(document, dict):
        raise ValueError("Input document must be an object")
    return document


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0))
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("Source must be a regular file")
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
        after = os.fstat(descriptor)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError("Source changed during hash")
    finally:
        os.close(descriptor)
    return digest.hexdigest()


@contextmanager
def _exclusive_output_lock(output: Path):
    lock = output.with_name(output.name + ".lock")
    descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    identity = os.fstat(descriptor)
    try:
        yield
    finally:
        try:
            current = lock.lstat()
            if current.st_dev == identity.st_dev and current.st_ino == identity.st_ino:
                lock.unlink()
        except FileNotFoundError:
            pass
        os.close(descriptor)


def _check_audio_contiguity(stream: dict, frames: list[dict]) -> tuple[int, int, int]:
    """Require each decoded audio PTS to match cumulative samples from origin zero."""
    rate = stream.get("sample_rate")
    channels = stream.get("channels")
    base = positive_rate(stream.get("time_base"))
    try:
        rate = int(rate)
        channels = int(channels)
    except (TypeError, ValueError) as exc:
        raise ValueError("Unknown audio rate or channels") from exc
    if rate <= 0 or channels not in (1, 2) or base is None or not frames:
        raise ValueError("Unsupported audio format or missing decoded frames")
    total = 0
    for frame in frames:
        pts, samples = frame.get("pts"), frame.get("nb_samples")
        if (isinstance(pts, bool) or not isinstance(pts, int) or isinstance(samples, bool)
            or not isinstance(samples, int) or samples <= 0):
            raise ValueError("Missing audio PTS or decoded sample count")
        if frame.get("channels", channels) != channels:
            raise ValueError("Audio channel count changes")
        if pts * base != Fraction(total, rate):
            raise ValueError("Decoded audio PTS gap, overlap, or nonzero origin")
        total += samples
    return rate, channels, total


def _run(command: list[str], *, timeout: float, max_bytes: int, output: Path,
         bounded_file: Path | None = None, bounded_file_bytes: int | None = None) -> None:
    """Capture bounded tool output and terminate its process group on limits."""
    with output.open("xb") as stdout, tempfile.TemporaryFile() as stderr:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=stdout,
                                   stderr=stderr, start_new_session=True)
        deadline = time.monotonic() + timeout
        try:
            while process.poll() is None:
                if (time.monotonic() >= deadline or stdout.tell() > max_bytes or stderr.tell() > 1024 * 1024
                    or (bounded_file is not None and bounded_file.exists()
                        and bounded_file.stat().st_size > bounded_file_bytes)):
                    raise ValueError("Media tool timed out or exceeded output limit")
                time.sleep(0.05)
            if (stdout.tell() > max_bytes or stderr.tell() > 1024 * 1024
                or (bounded_file is not None and bounded_file.exists()
                    and bounded_file.stat().st_size > bounded_file_bytes)):
                raise ValueError("Media tool exceeded output limit")
            stderr.seek(0)
            diagnostic = stderr.read(4096)
            if process.returncode or diagnostic:
                raise ValueError(f"Media tool reported errors ({process.returncode}): {diagnostic.decode(errors='replace')}")
        finally:
            # The direct tool may exit while a child remains in its process group.
            # Reap every owned group on both successful and failed paths.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()


def _probe_source(path: Path, ffprobe: str, timeout: float, temporary: Path,
                  audio_stream_index: int | None = None) -> tuple[dict, dict, int, dict]:
    out = temporary / "scan.json"
    _run([ffprobe, "-v", "error", "-protocol_whitelist", "file", "-enable_drefs", "0",
          "-show_frames", "-show_streams", "-show_format", "-show_entries",
          "frame=stream_index,media_type,pts,duration,nb_samples,sample_fmt,channels,side_data_list,width,height,interlaced_frame:stream=index,codec_type,time_base,start_time,sample_rate,channels,avg_frame_rate,width,height,pix_fmt,color_space,color_primaries,color_transfer,disposition:format=format_name",
          "-of", "json", str(path)], timeout=timeout, max_bytes=64 * 1024 * 1024, output=out)
    probe = _load_document(out, 64 * 1024 * 1024)
    if probe.get("format", {}).get("format_name") != "mov,mp4,m4a,3gp,3g2,mj2":
        raise ValueError("Speech staging supports self-contained MOV/MP4 only")
    decoded = summarize_decode(probe, audio_stream_index=audio_stream_index)
    video, audio = decoded["video"], decoded["audio"]
    if video is None or audio is None:
        raise ValueError("Speech staging requires video and audio")
    if video["issues"] or video["cfr_status"] != "CFR" or video["origin_seconds"] != {"num": 0, "den": 1}:
        raise ValueError(f"Unsupported video timing: {video['issues']}")
    streams = probe["streams"]
    audio_stream = next(s for s in streams if s["index"] == audio["stream_index"])
    if "start_time" not in audio_stream:
        raise ValueError("Audio origin is unknown")
    try:
        if Fraction(audio_stream.get("start_time", "0")) != 0:
            raise ValueError("Audio has a nonzero origin")
    except (TypeError, ZeroDivisionError) as exc:
        raise ValueError("Audio origin is unknown") from exc
    rate, channels, samples = _check_audio_contiguity(
        audio_stream, [frame for frame in probe["frames"] if frame["stream_index"] == audio["stream_index"]])
    if (audio["sample_rate"], audio["channels"], audio["decoded_samples"]) != (rate, channels, samples):
        raise ValueError("Audio decoded metadata disagrees with contiguous samples")
    video_stream = next(s for s in streams if s["index"] == video["stream_index"])
    return decoded, video, rate, video_stream


def _video_hashes(command: list[str], *, ffmpeg: str, timeout: float, maximum_frames: int,
                  temporary: Path, filename: str) -> list[str]:
    output = temporary / filename
    _run([ffmpeg, "-nostdin", "-v", "error", "-protocol_whitelist", "file", *command,
          "-map", "[v]" if "-filter_complex" in command else "0:v:0", "-f", "framemd5", "-"],
         timeout=timeout, max_bytes=maximum_frames * 256 + 4096, output=output)
    records = [line.rsplit(",", 1)[-1].strip() for line in output.read_text(encoding="utf-8").splitlines()
               if line and not line.startswith("#")]
    if len(records) != maximum_frames or not all(len(value) == 32 for value in records):
        raise ValueError("Video frame hashes missing or count differs from requested range")
    return records


def _video_layout(width: int, height: int) -> tuple[int, int, int, int, dict, str]:
    """Fit content within the orientation's 360p box, then pad to 16 pixels."""
    box_width, box_height = ((640, 360) if width > height else
                             (360, 640) if height > width else (360, 360))
    scale = min(Fraction(1), Fraction(box_width, width), Fraction(box_height, height))
    content_width = max(2, 2 * (width * scale // 2))
    content_height = max(2, 2 * (height * scale // 2))
    output_width = 16 * ((content_width + 15) // 16)
    output_height = 16 * ((content_height + 15) // 16)
    left = 2 * ((output_width - content_width) // 4)
    top = 2 * ((output_height - content_height) // 4)
    padding = {"left": left, "right": output_width - content_width - left,
               "top": top, "bottom": output_height - content_height - top}
    transform = (f"scale={content_width}:{content_height}:flags=lanczos,"
                 if (content_width, content_height) != (width, height) else "") + "format=yuv420p"
    transform += f",pad={output_width}:{output_height}:{left}:{top}:color=black"
    return content_width, content_height, output_width, output_height, padding, transform


def _decode_samples(command: list[str], *, timeout: float, count: int, channels: int,
                    temporary: Path, filename: str) -> array:
    path = temporary / filename
    _run(command + ["-f", "f32le", "-acodec", "pcm_f32le", "-"], timeout=timeout,
         max_bytes=count * channels * 4 + 4, output=path)
    if path.stat().st_size != count * channels * 4:
        raise ValueError("Decoded audio sample count does not match requested interval")
    samples = array("f")
    samples.frombytes(path.read_bytes())
    if sys.byteorder != "little":
        samples.byteswap()
    if not all(math.isfinite(value) for value in samples):
        raise ValueError("Decoded audio contains nonfinite samples")
    return samples


def _correlation(left: array, right: array) -> float:
    if len(left) != len(right):
        raise ValueError("Decoded source and clip lengths differ")
    mean_a = sum(left) / len(left)
    mean_b = sum(right) / len(right)
    cross = power_a = power_b = 0.0
    for a, b in zip(left, right):
        a -= mean_a
        b -= mean_b
        cross += a * b
        power_a += a * a
        power_b += b * b
    if power_a < 1e-12 and power_b < 1e-12:
        return 1.0
    if power_a < 1e-12 or power_b < 1e-12:
        return 0.0
    result = cross / math.sqrt(power_a * power_b)
    if not math.isfinite(result):
        raise ValueError("Nonfinite audio correlation")
    return result


def stage_media(manifest_path: Path, request_path: Path, output_dir: Path, *,
                ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe", timeout: float = 60,
                max_total_seconds: int = 60, max_clip_bytes: int = 20 * 1024 * 1024,
                mode: str = "speech") -> dict:
    """Publish immutable speech or audiovisual clips with exact local provenance."""
    if (not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0
        or not isinstance(max_total_seconds, int) or isinstance(max_total_seconds, bool) or max_total_seconds <= 0
        or not isinstance(max_clip_bytes, int) or isinstance(max_clip_bytes, bool) or max_clip_bytes <= 0):
        raise ValueError("Invalid timeout or staging limits")
    output_dir = check_output_directory(output_dir)
    manifest_path = manifest_path.absolute()
    request_path = request_path.absolute()
    manifest_raw = _read_regular(manifest_path, 4 * 1024 * 1024)
    request_raw = _read_regular(request_path, 4 * 1024 * 1024)
    manifest = json.loads(manifest_raw.decode("utf-8"), object_pairs_hook=_unique_object,
                          parse_constant=_reject_constant)
    request = json.loads(request_raw.decode("utf-8"), object_pairs_hook=_unique_object,
                         parse_constant=_reject_constant)
    if not isinstance(manifest, dict) or not isinstance(request, dict):
        raise ValueError("Input documents must be objects")
    original_signatures = {p: file_signature(p) for p in (manifest_path, request_path)}
    if (_sha(manifest_path) != hashlib.sha256(manifest_raw).hexdigest()
        or _sha(request_path) != hashlib.sha256(request_raw).hexdigest()):
        raise ValueError("Input document changed during staging")
    issues = check_documents({"manifest": manifest, "analysis-request": request})
    if issues:
        raise ValueError(f"Invalid request/manifest: {issues[0].code}: {issues[0].message}")
    for root in (Path(__file__).resolve().parents[1] / "work", Path(__file__).resolve().parents[1] / "artifacts"):
        if root == output_dir or root in output_dir.parents:
            if output_dir != root / manifest["job_id"] and root / manifest["job_id"] not in output_dir.parents:
                raise ValueError("Repository runtime output must be under work/<job_id>/ or artifacts/<job_id>/")
    categories = set(request["requested_categories"])
    speech_categories = {"speech", "dialogue", "audible_dialogue"}
    if mode == "speech":
        if not categories or not categories <= speech_categories:
            raise ValueError("Speech staging requires speech/dialogue categories only")
    elif mode == "audiovisual":
        if (len(request["requested_categories"]) != 2 or "visual" not in categories
            or len(categories & speech_categories) != 1):
            raise ValueError("Audiovisual staging requires both visual and speech/dialogue categories only")
    else:
        raise ValueError("Unsupported staging mode")
    executable = {name: shutil.which(value) for name, value in (("ffmpeg", ffmpeg), ("ffprobe", ffprobe))}
    if any(value is None for value in executable.values()):
        raise ValueError("ffmpeg and ffprobe must be available")
    executable = {name: str(Path(value).resolve()) for name, value in executable.items()}
    sources = {source["source_id"]: source for source in manifest["sources"]}
    ranges = []
    total_ms = 0
    for entry in request["sources"]:
        prior_end = -1
        for interval in sorted(entry["ranges"], key=lambda item: item["start_ms"]):
            start, end = interval["start_ms"], interval["end_ms"]
            if start < prior_end:
                raise ValueError("Overlapping or duplicate ranges are unsupported")
            prior_end = end
            total_ms += end - start
            ranges.append((entry["source_id"], start, end))
    if total_ms > max_total_seconds * 1000:
        raise ValueError("Requested duration exceeds staging limit")
    if len(ranges) > 64:
        raise ValueError("Requested clip count exceeds staging limit")
    source_paths = {}
    for source_id in {sid for sid, _, _ in ranges}:
        source = sources[source_id]
        path = Path(source["path"])
        if not path.is_absolute() or source.get("proxy_path") is not None or source.get("content_sha256") is None:
            raise ValueError("Absolute original paths, hashes, and no proxies are required")
        if path.is_symlink():
            raise ValueError("Source symlinks are unsupported")
        path = path.absolute()
        signature = file_signature(path)
        if _sha(path) != source["content_sha256"] or file_signature(path) != signature:
            raise ValueError("Source hash mismatch or source changed")
        source_paths[source_id] = (path, signature)
    clips = []
    with _exclusive_output_lock(output_dir), tempfile.TemporaryDirectory(prefix="footage-stage-", dir=output_dir.parent) as tmp_name:
        temporary = Path(tmp_name)
        scans = {}
        for source_id, (path, _) in source_paths.items():
            scan_dir = temporary / f"scan-{source_id}"
            scan_dir.mkdir()
            decoded, video, rate, video_stream = _probe_source(
                path, executable["ffprobe"], timeout, scan_dir,
                audio_stream_index=sources[source_id].get("audio_stream_index"))
            issues = compare_inventory(sources[source_id], decoded)
            if issues:
                raise ValueError(f"Manifest differs from freshly decoded source: {issues}")
            scans[source_id] = (video, rate, decoded["audio"]["channels"],
                                decoded["audio"]["decoded_samples"], video_stream,
                                decoded["audio"]["stream_index"])
        for number, (source_id, start_ms, end_ms) in enumerate(ranges, 1):
            path, _ = source_paths[source_id]
            video, rate, channels, source_samples, video_stream, audio_index = scans[source_id]
            fps = Fraction(video["fps"]["num"], video["fps"]["den"])
            start_frame, end_frame = Fraction(start_ms, 1000) * fps, Fraction(end_ms, 1000) * fps
            start_sample, end_sample = Fraction(start_ms, 1000) * rate, Fraction(end_ms, 1000) * rate
            if any(value.denominator != 1 for value in (start_frame, end_frame, start_sample, end_sample)):
                raise ValueError("Range boundaries must align with source video frames and audio samples")
            if end_frame > video["decoded_frame_count"] or end_sample > source_samples:
                raise ValueError("Range exceeds freshly decoded source")
            first, last = int(start_sample), int(end_sample)
            count = last - first
            if count * channels * 4 > 256 * 1024 * 1024:
                raise ValueError("Decoded verification interval is too large")
            if mode == "audiovisual":
                width, height = video_stream.get("width"), video_stream.get("height")
                source_pix_fmt = video_stream.get("pix_fmt")
                if (source_pix_fmt not in {"yuv420p", "yuv420p10le"} or isinstance(width, bool) or isinstance(height, bool)
                    or not isinstance(width, int) or not isinstance(height, int) or width < 2 or height < 2
                    or width % 2 or height % 2):
                    raise ValueError("Audiovisual staging requires even-sized yuv420p or yuv420p10le video")
                if source_pix_fmt == "yuv420p10le" and any(
                    video_stream.get(field) != "bt709" for field in ("color_space", "color_primaries", "color_transfer")
                ):
                    raise ValueError("10-bit audiovisual staging requires explicit BT.709 source color tags")
                (content_width, content_height, staged_width, staged_height,
                 padding, transform) = _video_layout(width, height)
                video_filter = (f"trim=start_frame={int(start_frame)}:end_frame={int(end_frame)},"
                                f"setpts=PTS-STARTPTS,{transform}")
            name = f"clip-{number:04d}.{'mp4' if mode == 'audiovisual' else 'mp3'}"
            clip_path = temporary / name
            audio_filtergraph = f"[0:{audio_index}]atrim=start_sample={first}:end_sample={last},asetpts=PTS-STARTPTS[a]"
            filtergraph = audio_filtergraph
            if mode == "audiovisual":
                filtergraph = f"[0:v:0]{video_filter}[v];" + filtergraph
            encode = [executable["ffmpeg"], "-nostdin", "-v", "error", "-protocol_whitelist", "file", "-i", str(path),
                      "-filter_complex", filtergraph]
            if mode == "audiovisual":
                encode += ["-map", "[v]", "-map", "[a]", "-map_metadata", "-1",
                           "-map_metadata:s:v", "-1", "-map_metadata:s:a", "-1", "-map_chapters", "-1",
                           "-c:v", "libx264", "-preset", "ultrafast", "-crf", "0",
                           "-pix_fmt", "yuv420p", "-fps_mode:v", "passthrough"]
                if source_pix_fmt == "yuv420p10le":
                    encode += ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                               "-x264-params", "colorprim=bt709:transfer=bt709:colormatrix=bt709"]
            else:
                encode += ["-map", "[a]", "-vn", "-map_metadata", "-1",
                           "-map_metadata:s:a", "-1", "-map_chapters", "-1"]
            encode += ["-codec:a", "libmp3lame", "-q:a", "2", "-y", str(clip_path)]
            log = temporary / f"encode-{number:04d}.log"
            _run(encode, timeout=timeout, max_bytes=1024 * 1024, output=log,
                 bounded_file=clip_path, bounded_file_bytes=max_clip_bytes)
            if not clip_path.is_file() or clip_path.stat().st_size == 0 or clip_path.stat().st_size > max_clip_bytes:
                raise ValueError("Encoded clip is absent or exceeds byte limit")
            if mode == "audiovisual":
                clip_scan = temporary / f"clip-scan-{number:04d}"
                clip_scan.mkdir()
                staged_decoded, staged_video, staged_rate, staged_stream = _probe_source(
                    clip_path, executable["ffprobe"], timeout, clip_scan)
                if (staged_video["decoded_frame_count"] != int(end_frame - start_frame)
                    or Fraction(staged_video["fps"]["num"], staged_video["fps"]["den"]) != fps
                    or staged_rate != rate or staged_decoded["audio"]["decoded_samples"] != count
                    or staged_decoded["audio"]["channels"] != channels
                    or (staged_stream.get("width"), staged_stream.get("height")) != (staged_width, staged_height)):
                    raise ValueError("Staged audiovisual clocks, frames, or audio samples differ")
                source_frames = _video_hashes(["-i", str(path), "-filter_complex", f"[0:v:0]{video_filter}[v]"],
                                              ffmpeg=executable["ffmpeg"], timeout=timeout,
                                              maximum_frames=int(end_frame - start_frame), temporary=temporary,
                                              filename=f"source-video-{number:04d}.md5")
                staged_frames = _video_hashes(["-i", str(clip_path)], ffmpeg=executable["ffmpeg"], timeout=timeout,
                                              maximum_frames=int(end_frame - start_frame), temporary=temporary,
                                              filename=f"staged-video-{number:04d}.md5")
                if source_frames != staged_frames:
                    raise ValueError("Staged video decoded pixels differ from selected source frames")
            reference_cmd = [executable["ffmpeg"], "-nostdin", "-v", "error", "-protocol_whitelist", "file", "-i", str(path),
                             "-filter_complex", audio_filtergraph, "-map", "[a]", "-vn"]
            clip_cmd = [executable["ffmpeg"], "-nostdin", "-v", "error", "-protocol_whitelist", "file", "-i", str(clip_path), "-map", "0:a:0", "-vn"]
            reference = _decode_samples(reference_cmd, timeout=timeout, count=count, channels=channels,
                                        temporary=temporary, filename=f"source-{number:04d}.f32")
            rendered = _decode_samples(clip_cmd, timeout=timeout, count=count, channels=channels,
                                       temporary=temporary, filename=f"clip-{number:04d}.f32")
            correlation = _correlation(reference, rendered)
            if correlation <= 0.98:
                raise ValueError(f"Staged audio differs from source interval (correlation {correlation:.4f})")
            clip_record = {"clip_id": f"clip-{number:04d}", "source_id": source_id,
                          "source_path": str(path), "source_sha256": sources[source_id]["content_sha256"],
                          "source_size_bytes": path.stat().st_size,
                          "source_start_ms": start_ms, "source_end_ms": end_ms,
                          "source_start_frame": int(start_frame), "source_end_frame": int(end_frame),
                          "local_start_ms": 0, "local_end_ms": end_ms - start_ms,
                          "audio_path": name, "audio_sha256": _sha(clip_path),
                          "audio_size_bytes": clip_path.stat().st_size,
                          "decoded_samples": count, "sample_rate": rate, "channels": channels,
                          "source_audio_stream_index": audio_index,
                          "waveform_correlation": correlation, "encode_command": encode}
            if mode == "audiovisual":
                clip_record.update({"media_kind": "audiovisual", "media_path": name,
                                    "media_sha256": clip_record["audio_sha256"],
                                    "media_size_bytes": clip_record["audio_size_bytes"],
                                    "video_width": staged_width, "video_height": staged_height,
                                    "video_content_width": content_width,
                                    "video_content_height": content_height,
                                    "video_padding": padding,
                                    "source_video_pix_fmt": source_pix_fmt,
                                    "video_conversion": ("bt709_10bit_to_yuv420p8" if source_pix_fmt == "yuv420p10le"
                                                         else "yuv420p8_to_yuv420p8"),
                                    "video_frame_count": int(end_frame - start_frame),
                                    "video_fps_num": fps.numerator, "video_fps_den": fps.denominator,
                                    "video_transform": transform,
                                    "video_decoded_frames_match": True,
                                    "audio_decoded_samples_match": True})
            clips.append(clip_record)
        for path, signature in original_signatures.items():
            if file_signature(path) != signature:
                raise ValueError("Input document changed during staging")
        if (_sha(manifest_path) != hashlib.sha256(manifest_raw).hexdigest()
            or _sha(request_path) != hashlib.sha256(request_raw).hexdigest()):
            raise ValueError("Input document bytes changed during staging")
        for source_id, (path, signature) in source_paths.items():
            if file_signature(path) != signature or _sha(path) != sources[source_id]["content_sha256"]:
                raise ValueError("Source changed during staging")
        report = {"job_id": manifest["job_id"], "request_id": request["request_id"],
                  "manifest_sha256": hashlib.sha256(manifest_raw).hexdigest(),
                  "request_sha256": hashlib.sha256(request_raw).hexdigest(),
                  "status": "PASS", "clips": clips}
        (temporary / "mapping.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        for path in temporary.iterdir():
            if path.name != "mapping.json" and path.suffix not in {".mp3", ".mp4"}:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
        if output_dir.exists():
            raise ValueError("Output directory already exists")
        os.rename(temporary, output_dir)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--max-total-seconds", type=int, default=60)
    parser.add_argument("--max-clip-bytes", type=int, default=20 * 1024 * 1024)
    parser.add_argument("--mode", choices=("speech", "audiovisual"), default="speech")
    args = parser.parse_args(argv)
    try:
        report = stage_media(args.manifest, args.request, args.output_dir, timeout=args.timeout,
                             max_total_seconds=args.max_total_seconds, max_clip_bytes=args.max_clip_bytes,
                             mode=args.mode)
    except (OSError, ValueError) as exc:
        print(f"STAGING_ERROR: {exc}", file=sys.stderr)
        return 2
    print(f"STAGED: {len(report['clips'])} clips at {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
