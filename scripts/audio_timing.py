"""Bounded decoded PCM/AAC presentation clocks and exact sample-cut arithmetic."""
from __future__ import annotations

from fractions import Fraction

try:
    from .probe_manifest import positive_integer, positive_rate, MAX_INTEGER
except ImportError:
    from probe_manifest import positive_integer, positive_rate, MAX_INTEGER


def analyze_pcm(stream: dict, frames: list[dict]) -> dict:
    issues = []
    rate = positive_integer(stream.get("sample_rate"))
    channels = positive_integer(stream.get("channels"))
    base = positive_rate(stream.get("time_base"))
    result = {"status": "FAIL", "issues": issues, "sample_rate": rate,
              "sample_count": None, "duration_seconds": None}
    if not str(stream.get("codec_name", "")).startswith("pcm_"):
        issues.append("NON_PCM_AUDIO_UNSUPPORTED")
    if rate is None or channels is None or base is None or not stream.get("sample_fmt"):
        issues.append("UNKNOWN_PCM_FORMAT")
    if stream.get("initial_padding", 0) != 0 or stream.get("trailing_padding", 0) != 0:
        issues.append("AUDIO_PADDING_UNSUPPORTED")
    if not frames:
        issues.append("NO_DECODED_PCM")
    if issues:
        return result
    expected = Fraction(0)
    samples_total = 0
    for frame in frames:
        pts = frame.get("pts")
        samples = positive_integer(frame.get("nb_samples"))
        duration = positive_integer(frame.get("duration"))
        if isinstance(pts, bool) or not isinstance(pts, int) or abs(pts) > MAX_INTEGER or samples is None or duration is None:
            issues.append("MISSING_PCM_TIMING")
            break
        if frame.get("side_data_list"):
            issues.append("AUDIO_SIDE_DATA_UNSUPPORTED")
        if frame.get("channels") != channels or frame.get("sample_fmt") != stream["sample_fmt"]:
            issues.append("PCM_FORMAT_CHANGE_OR_UNKNOWN")
        # Rate is reported by the stream; exact durations enforce its agreement
        # with the decoded sample count in every frame.
        length = Fraction(samples, rate)
        start = pts * base
        if start != expected:
            issues.append("PCM_TIMESTAMP_GAP_OR_OVERLAP")
        if duration * base != length:
            issues.append("PCM_DURATION_SAMPLE_MISMATCH")
        samples_total += samples
        expected = start + length
    if not issues:
        result.update(status="PASS", sample_count=samples_total,
                      duration_seconds={"num": expected.numerator, "den": expected.denominator})
    return result


def sample_cut(timing: dict, source_in: int, source_out: int, timeline_in: int,
               fps: Fraction) -> dict:
    """Require exact sample boundaries; never introduce implicit sample rounding."""
    if timing["status"] != "PASS":
        return {"status": "FAIL", "issues": ["SOURCE_AUDIO_TIMING_UNVERIFIED"]}
    rate = timing["sample_rate"]
    positions = [Fraction(frame * rate, 1) / fps for frame in (source_in, source_out, timeline_in)]
    if any(position.denominator != 1 for position in positions):
        return {"status": "FAIL", "issues": ["FRACTIONAL_AUDIO_SAMPLE_CUT_UNSUPPORTED"]}
    start, end, offset = [position.numerator for position in positions]
    if start < 0 or end <= start or end > timing["sample_count"]:
        return {"status": "FAIL", "issues": ["DECODED_AUDIO_BOUND"]}
    if any(value > MAX_INTEGER for value in (start, end, offset, offset + end - start)):
        return {"status": "FAIL", "issues": ["AUDIO_SAMPLE_INTEGER_BOUND"]}
    return {"status": "PASS", "issues": [], "sample_rate": rate,
            "source_in_sample": start, "source_out_sample": end,
            "timeline_in_sample": offset, "timeline_out_sample": offset + end - start}


def analyze_aac(stream: dict, frames: list[dict]) -> dict:
    """Check decoded AAC-LC presentation after demuxer priming/trim handling.

    The asset remains compressed. This does not assert that another application's
    decoder matches FFmpeg, nor support unknown offsets, resampling or profiles.
    """
    issues = []
    result = {"status": "FAIL", "issues": issues, "sample_rate": 48000,
              "sample_count": None, "duration_seconds": None,
              "mode": "AAC_NATIVE", "application_decode_sync": "NOT_RUN"}
    rate = positive_integer(stream.get("sample_rate"))
    channels = positive_integer(stream.get("channels"))
    base = positive_rate(stream.get("time_base"))
    padding = stream.get("initial_padding", 0)
    duration = positive_integer(stream.get("duration_ts"))
    if (stream.get("codec_name") != "aac" or stream.get("profile") != "LC"
            or rate != 48000 or channels not in (1, 2)
            or base != Fraction(1, 48000) or stream.get("sample_fmt") != "fltp"):
        issues.append("AAC_PROFILE_OR_FORMAT_UNSUPPORTED")
    if (type(padding) is not int or padding not in (0, 1024)
            or type(stream.get("trailing_padding", 0)) is not int
            or stream.get("trailing_padding", 0) != 0):
        issues.append("AAC_PADDING_UNSUPPORTED")
    if type(stream.get("start_pts")) is not int or stream["start_pts"] != 0 or duration is None:
        issues.append("AAC_PRESENTATION_BOUNDS_UNKNOWN_OR_NONZERO")
    if not frames:
        issues.append("NO_DECODED_AAC")
    if issues:
        return result
    expected = 0
    for number, frame in enumerate(frames):
        pts, count, ticks = frame.get("pts"), frame.get("nb_samples"), frame.get("duration")
        if (type(pts) is not int or type(count) is not int or type(ticks) is not int
                or not 0 < count <= 1024 or abs(pts) > MAX_INTEGER):
            issues.append("AAC_DECODED_TIMING_UNKNOWN")
            break
        if number < len(frames) - 1 and count != 1024:
            issues.append("AAC_INTERIOR_PARTIAL_FRAME_UNSUPPORTED")
        if pts != expected or ticks != count:
            issues.append("AAC_PRESENTATION_GAP_OVERLAP_OR_DURATION")
        if (frame.get("channels") != channels or frame.get("sample_fmt") != "fltp"
                or frame.get("side_data_list")):
            issues.append("AAC_DECODED_FORMAT_OR_SIDE_DATA_UNSUPPORTED")
        expected = pts + count
        if expected > MAX_INTEGER:
            issues.append("AAC_SAMPLE_INTEGER_BOUND")
    if expected != duration:
        issues.append("AAC_DECODED_PRESENTATION_DURATION_MISMATCH")
    if not issues:
        seconds = Fraction(expected, 48000)
        result.update(status="PASS", sample_count=expected,
                      duration_seconds={"num": seconds.numerator, "den": seconds.denominator},
                      initial_padding_samples=padding, presentation_origin_samples=0)
    return result
