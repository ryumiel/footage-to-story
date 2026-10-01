"""Synthetic PCM clock and sample-boundary invariants, not acoustic sync judgments."""
from copy import deepcopy
from fractions import Fraction

import pytest

from scripts.audio_timing import analyze_pcm, sample_cut


@pytest.fixture
def pcm():
    stream = {"codec_name": "pcm_s16le", "sample_fmt": "s16", "sample_rate": "48000",
              "channels": 2, "time_base": "1/48000", "initial_padding": 0}
    frames = [{"pts": start, "duration": 1024, "nb_samples": 1024,
               "channels": 2, "sample_fmt": "s16"} for start in (0, 1024, 2048)]
    return stream, frames


def test_contiguous_pcm_exact_duration(pcm):
    result = analyze_pcm(*pcm)
    assert result["status"] == "PASS"
    assert result["sample_count"] == 3072
    assert result["duration_seconds"] == {"num": 8, "den": 125}


@pytest.mark.parametrize("case,expected", [("codec", "NON_PCM_AUDIO_UNSUPPORTED"),
                                         ("unknown-rate", "UNKNOWN_PCM_FORMAT"),
                                         ("padding", "AUDIO_PADDING_UNSUPPORTED"),
                                         ("empty", "NO_DECODED_PCM"),
                                         ("shift", "PCM_TIMESTAMP_GAP_OR_OVERLAP"),
                                         ("gap", "PCM_TIMESTAMP_GAP_OR_OVERLAP"),
                                         ("overlap", "PCM_TIMESTAMP_GAP_OR_OVERLAP"),
                                         ("duration", "PCM_DURATION_SAMPLE_MISMATCH"),
                                         ("channels", "PCM_FORMAT_CHANGE_OR_UNKNOWN"),
                                         ("format", "PCM_FORMAT_CHANGE_OR_UNKNOWN"),
                                         ("missing-pts", "MISSING_PCM_TIMING"),
                                         ("side-data", "AUDIO_SIDE_DATA_UNSUPPORTED")])
def test_unsupported_audio_never_receives_timing_pass(pcm, case, expected):
    stream, frames = pcm
    if case == "codec":
        stream["codec_name"] = "aac"
    elif case == "unknown-rate":
        stream["sample_rate"] = None
    elif case == "padding":
        stream["initial_padding"] = 1024
    elif case == "empty":
        frames.clear()
    elif case in {"shift", "gap", "overlap"}:
        frames[0 if case == "shift" else 1]["pts"] += -1 if case == "overlap" else 1
    elif case == "duration":
        frames[1]["duration"] = 1023
    elif case == "channels":
        frames[1]["channels"] = 1
    elif case == "format":
        frames[1]["sample_fmt"] = "s32"
    elif case == "missing-pts":
        frames[1].pop("pts")
    else:
        frames[1]["side_data_list"] = [{"side_data_type": "Skip Samples"}]
    result = analyze_pcm(stream, frames)
    assert result["status"] == "FAIL" and expected in result["issues"]


def test_pcm_input_preserved(pcm):
    original = deepcopy(pcm)
    analyze_pcm(*pcm)
    assert pcm == original


def timing(samples=48048):
    return {"status": "PASS", "sample_rate": 48000, "sample_count": samples}


def test_ntsc_five_frame_boundaries_align_exactly():
    result = sample_cut(timing(), 5, 30, 5, Fraction(30000, 1001))
    assert result == {"status": "PASS", "issues": [], "sample_rate": 48000,
                      "source_in_sample": 8008, "source_out_sample": 48048,
                      "timeline_in_sample": 8008, "timeline_out_sample": 48048}


@pytest.mark.parametrize("source_in,source_out,timeline_in", [(0, 1, 0), (1, 5, 0), (5, 30, 1)])
def test_fractional_samples_are_not_rounded(source_in, source_out, timeline_in):
    assert "FRACTIONAL_AUDIO_SAMPLE_CUT_UNSUPPORTED" in sample_cut(
        timing(), source_in, source_out, timeline_in, Fraction(30000, 1001))["issues"]


def test_audio_out_exclusive_bound_and_unverified_source():
    assert sample_cut(timing(48000), 0, 25, 0, Fraction(25))["status"] == "PASS"
    assert "DECODED_AUDIO_BOUND" in sample_cut(timing(47999), 0, 25, 0, Fraction(25))["issues"]
    assert "SOURCE_AUDIO_TIMING_UNVERIFIED" in sample_cut({"status": "FAIL"}, 0, 1, 0, Fraction(25))["issues"]
