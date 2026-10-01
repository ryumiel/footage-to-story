"""Fresh-media checks for sequential CFR edit bounds and timeline continuity."""
from __future__ import annotations

import argparse
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

from jsonschema.exceptions import SchemaError
from referencing.exceptions import Unresolvable

try:
    from .check_integrity import STAGES, IntegrityIssue, check_documents
    from .probe_manifest import MAX_INTEGER, check_output_directory, file_signature
    from .validate_json import _unique_object, _reject_constant
    from .verify_media import rational, verify_media
    from .audio_timing import sample_cut
except ImportError:
    from check_integrity import STAGES, IntegrityIssue, check_documents
    from probe_manifest import MAX_INTEGER, check_output_directory, file_signature
    from validate_json import _unique_object, _reject_constant
    from verify_media import rational, verify_media
    from audio_timing import sample_cut


def analyze_edit(documents: dict, media: dict, *, subtitle_timing: bool = False) -> dict:
    """Compare validated records with a trusted, freshly generated scan in memory.

    This is an internal calculation helper, not a saved-report validation API.
    The CLI below always regenerates the scan from current source files.
    """
    issues = check_documents(documents)
    if "edit-plan" not in documents:
        issues.append(IntegrityIssue("edit-plan", "", "MISSING_DOCUMENT", "An edit plan is required"))
    result = {"status": "FAIL" if issues else "PASS", "items": [],
              "timeline_frame_count": None, "timeline_duration_seconds": None,
              "issues": [vars(issue) for issue in issues],
              "not_checked": ["compressed-audio priming/resampling", "proxy mappings", "prior locks",
                              "permission authenticity", "approval digest/authenticity", "export"]}
    result.update(scope='SUBTITLE_TIMING' if subtitle_timing else 'EDIT_AUDIO_VIDEO',
                  audio_cut_verification='NOT_RUN' if subtitle_timing else 'CHECKED',
                  execution_authorized=False)
    if subtitle_timing:
        result['not_checked'].append('audio cut synchronization and export readiness')
    if issues:
        return result
    plan = documents["edit-plan"]

    def issue(path: str, code: str, message: str) -> None:
        result["issues"].append({"document": "edit-plan", "path": path,
                                 "code": code, "message": message})
        result["status"] = "FAIL"

    if media["job_id"] != documents["manifest"]["job_id"]:
        issue("", "MEDIA_JOB_MISMATCH", "Media scan belongs to a different job")
    if media["status"] != "PASS":
        issue("", "MEDIA_SCAN_FAILED", "Every source must pass the fresh media scan")
    measured = {source["source_id"]: source for source in media["sources"]}
    timeline_fps = Fraction(int(plan["timeline_fps"]["num"]), int(plan["timeline_fps"]["den"]))
    selects = {item["select_id"]: item for item in documents.get("selects", {}).get("items", [])}
    expected_in = 0
    source_audio_format = None
    for number, item in enumerate(plan["items"]):
        path = f"/items/{number}"
        source_in, source_out = int(item["source_in_frame"]), int(item["source_out_frame"])
        timeline_in = int(item["timeline_in_frame"])
        length = source_out - source_in
        timeline_out = timeline_in + length
        if timeline_in != expected_in:
            issue(path + "/timeline_in_frame", "TIMELINE_GAP" if timeline_in > expected_in else "TIMELINE_OVERLAP",
                  f"Expected frame {expected_in}, received {timeline_in}; array order defines the timeline")
        if timeline_out > MAX_INTEGER:
            issue(path, "TIMELINE_BOUND", "Calculated timeline OUT exceeds the contract integer limit")
        expected_in = timeline_out
        scan = measured.get(item["source_id"])
        video = scan.get("video") if scan else None
        audio_cut = {"status": "NOT_APPLICABLE", "policy": item["audio_policy"]}
        if scan is None or scan["status"] != "PASS":
            issue(path + "/source_id", "SOURCE_SCAN_FAILED", "Referenced source has no passing fresh scan")
        elif video is None:
            issue(path + "/source_id", "VIDEO_REQUIRED", "Frame cuts require a decoded video stream")
        elif video["cfr_status"] != "CFR" or video["fps"] is None:
            issue(path, "CFR_REQUIRED", "Only exact decoded CFR timing is supported")
        else:
            fps = Fraction(video["fps"]["num"], video["fps"]["den"])
            if fps != timeline_fps:
                issue(path, "MIXED_FPS_UNSUPPORTED", "Decoded source FPS must equal timeline FPS; no retiming is implemented")
            if source_out > video["decoded_frame_count"]:
                issue(path + "/source_out_frame", "DECODED_SOURCE_BOUND", "Source OUT exceeds the decoded video frame count")
            if item.get("select_ref") is not None:
                selected = selects[item["select_ref"]]
                if Fraction(source_in, 1) / fps < Fraction(int(selected["start_ms"]), 1000) or Fraction(source_out, 1) / fps > Fraction(int(selected["end_ms"]), 1000):
                    issue(path + "/select_ref", "SELECT_WINDOW_BOUND", "Exact frame cut lies outside the referenced select's millisecond window")
            if item["audio_policy"] == "SOURCE":
                audio = scan.get("audio")
                if audio is None:
                    issue(path + "/audio_policy", "SOURCE_AUDIO_MISSING", "SOURCE requires a decoded audio stream; use an explicit MUTE plan for video-only media")
                elif subtitle_timing:
                    audio_cut = {'status': 'NOT_RUN', 'policy': 'SOURCE',
                                 'reason': 'Subtitle timing does not verify audio sample cuts'}
                else:
                    audio_cut = sample_cut(audio["timing"], source_in, source_out, timeline_in, fps)
                    audio_format = (audio["sample_rate"], audio["channels"])
                    if audio["channels"] not in (1, 2):
                        issue(path + "/audio_policy", "MULTICHANNEL_AUDIO_UNSUPPORTED", "Only mono/stereo SOURCE audio is implemented")
                    if source_audio_format is not None and audio_format != source_audio_format:
                        issue(path + "/audio_policy", "MIXED_AUDIO_FORMAT_UNSUPPORTED", "SOURCE clips must have one sample rate and channel count; no conversion is implemented")
                    source_audio_format = audio_format
                    for code in audio_cut["issues"]:
                        issue(path + "/audio_policy", code, "SOURCE audio cannot be synchronized at exact decoded sample boundaries")
        result["items"].append({"edit_id": item["edit_id"], "source_id": item["source_id"],
                                "source_in_frame": source_in, "source_out_frame": source_out,
                                "timeline_in_frame": timeline_in, "timeline_out_frame": timeline_out,
                                "frame_count": length, "duration_seconds": rational(Fraction(length, 1) / timeline_fps),
                                "audio_policy": item["audio_policy"], "audio_cut": audio_cut})
    if result["status"] == "PASS":
        result["source_audio_format"] = ({"sample_rate": source_audio_format[0], "channels": source_audio_format[1]}
                                          if source_audio_format else None)
        result["timeline_frame_count"] = expected_in
        result["timeline_duration_seconds"] = rational(Fraction(expected_in, 1) / timeline_fps)
    return result


def verify_edit(paths: dict[str, Path], output: Path, ffprobe: str = "ffprobe",
                timeout: float = 60, max_bytes: int = 64 * 1024 * 1024) -> dict:
    """Fresh video and exact audio-cut verification for the exporter."""
    return _verify_edit(paths, output, ffprobe, timeout, max_bytes, subtitle_timing=False)


def verify_subtitle_timing(paths: dict[str, Path], output: Path, ffprobe: str = "ffprobe",
                           timeout: float = 60, max_bytes: int = 64 * 1024 * 1024) -> dict:
    """Fresh video geometry/source identity; audio cuts remain explicitly NOT_RUN."""
    return _verify_edit(paths, output, ffprobe, timeout, max_bytes, subtitle_timing=True)


def _verify_edit(paths: dict[str, Path], output: Path, ffprobe: str,
                 timeout: float, max_bytes: int, *, subtitle_timing: bool) -> dict:
    """Snapshot supplied documents, rerun decoding, then publish exact calculations."""
    if set(paths) - set(STAGES):
        raise ValueError("Unknown document stages")
    if not {"manifest", "edit-plan"} <= set(paths):
        raise ValueError("Manifest and edit plan paths are required")
    output = check_output_directory(output)
    resolved = {stage: path.expanduser().resolve(strict=True) for stage, path in paths.items()}
    signatures = {stage: file_signature(path) for stage, path in resolved.items()}
    raw = {stage: path.read_bytes() for stage, path in resolved.items()}
    documents = {stage: json.loads(data.decode("utf-8"), object_pairs_hook=_unique_object,
                                  parse_constant=_reject_constant) for stage, data in raw.items()}
    # Fail before reading media if schemas or record relationships are invalid.
    issues = check_documents(documents)
    if issues:
        raise ValueError(f"Invalid edit inputs: {issues[0].document}{issues[0].path}: {issues[0].code}: {issues[0].message}")
    hashes = {stage: hashlib.sha256(data).hexdigest() for stage, data in raw.items()}
    with tempfile.TemporaryDirectory(prefix="footage-edit-check-") as temporary:
        scan_directory = Path(temporary) / "media"
        media = verify_media(resolved["manifest"], scan_directory, ffprobe, timeout, max_bytes)
        if media["manifest_sha256"] != hashes["manifest"]:
            raise ValueError("Manifest changed between document validation and media scan")
        result = analyze_edit(documents, media, subtitle_timing=subtitle_timing)
        result.update(job_id=documents["manifest"]["job_id"], revision=documents["edit-plan"]["revision"],
                      input_sha256=hashes)
        # Recheck all documents and sources after calculations, before publication.
        if any(file_signature(path) != signatures[stage] or hashlib.sha256(path.read_bytes()).hexdigest() != hashes[stage]
               for stage, path in resolved.items()):
            raise ValueError("An input document changed during edit verification")
        for number, source in enumerate(media["sources"], 1):
            path = Path(source["path"])
            provenance = json.loads((scan_directory / f"decode-{number:04d}-provenance.json").read_text(encoding="utf-8"))
            if list(file_signature(path)) != provenance["stat_signature"]:
                raise ValueError("A source changed after the fresh media scan")
        output.mkdir(parents=True, exist_ok=False)
        shutil.copytree(scan_directory, output / "media")
        pending = output / "edit-report.json.tmp"
        pending.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        os.link(pending, output / "edit-report.json")
        pending.unlink()
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for stage in STAGES:
        parser.add_argument(f"--{stage}", type=Path, required=stage in {"manifest", "edit-plan"})
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--max-output-bytes", type=int, default=64 * 1024 * 1024)
    args = parser.parse_args(argv)
    paths = {stage: path for stage in STAGES if (path := getattr(args, stage.replace("-", "_"))) is not None}
    try:
        report = verify_edit(paths, args.output_dir, args.ffprobe, args.timeout, args.max_output_bytes)
    except (OSError, ValueError, SchemaError, Unresolvable) as exc:
        print(f"EDIT_ERROR: {exc}", file=sys.stderr)
        return 2
    print(f"EDIT_SCAN_{report['status']}: {args.output_dir.resolve() / 'edit-report.json'}")
    print("Compressed audio/resampling, proxy maps, prior locks, approval, and export NOT_CHECKED")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
