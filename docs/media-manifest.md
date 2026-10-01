# Local Media Manifest

`scripts/probe_manifest.py` reads explicitly supplied local files and writes a
2.0.0 manifest plus raw ffprobe evidence. It does not upload, rewrite, or transcode
sources. ffprobe is an external executable; install FFmpeg separately and ensure
`ffprobe` is on PATH, or supply `--ffprobe /absolute/path/to/ffprobe`.

```bash
source .venv/bin/activate
python scripts/probe_manifest.py \
  --job-id JOB \
  --source camera-001 /absolute/path/to/clip.mov \
  --source audio-001 /absolute/path/to/recording.wav \
  --output-dir work/JOB/inventory-001
```

Repeat `--source ID PATH` for each source; IDs are assigned by the caller, not
generated from filenames or metadata. Relative input paths resolve against the
current working directory. Each output directory must be new. Repository-local
outputs must be below `work/` or `artifacts/`; external directories are allowed.
The tool does not capture upload consent or human plan approval.

## Evidence and conversion rules

The manifest is validated with the existing local JSON Schema registry before
writing. `probe-0001.json`, etc. retain exact ffprobe stdout and stderr, command
arguments, executable version, source path, stat signature, and SHA-256. They are
private implementation evidence, not a new stage contract. Manifest `notes` link
each source to its evidence file. The [official ffprobe documentation](https://ffmpeg.org/ffprobe.html)
describes the JSON writer and stream/format metadata used here.

| Manifest field | Rule |
|---|---|
| `duration_ms` | Selected video duration, or audio duration for audio-only input; fallback to format duration; round positive seconds up using exact rational arithmetic |
| `fps_num`, `fps_den` | Reduced positive rational `avg_frame_rate` of selected video; unavailable/invalid becomes a null pair |
| `frame_count` | Positive reported video `nb_frames`; never inferred by multiplying duration and FPS |
| `cfr_status` | Always UNKNOWN; matching nominal and average FPS does not verify timing |
| Audio fields | Selected audio `sample_rate` and `channels`, or null |
| `time_base` | Selected video's reported time base, or audio's for audio-only input |
| `source_start_timecode` | Selected stream's `tags.timecode`, preserved as text; no assumed offset or format verification |
| `content_sha256` | SHA-256 of exact source file bytes |
| `proxy_path` | Null; no proxy generation or mapping |

Cover-art streams marked `attached_pic` are excluded from video selection. Files
with multiple remaining video streams or multiple audio streams fail because this
manifest cannot specify a selected stream. Files without audio/video also fail.
Identical paths, symlinks, and hard links to one file fail as duplicate source
identities; distinct files with identical content are allowed and retain their IDs.

## Failures and limits

Exit 0 means a schema-valid reported inventory was written; exit 2 means invalid
input, tool failure, timeout, or write failure. The default timeout is 30 seconds
per ffprobe invocation, configurable with `--timeout`. Hashing reads the whole
file and is not subject to that subprocess timeout. Probe commands use argument
arrays without shell evaluation and allow only the `file` protocol. This prevents
network retrieval but is not a filesystem sandbox for locally referenced media.

Source stat signatures are compared before and after probing/hashing and again
after the batch. This detects ordinary concurrent changes; it is not a snapshot,
an approval mechanism, or an enduring identity guarantee after the run. Raw tags
are untrusted data and are never executed as instructions. Raw probe evidence may
contain private paths and metadata and belongs alongside private job records.

Complete files are published without replacing existing destinations; the
manifest is published last. Publication uses same-directory hard links, so the
output filesystem must support them; unsupported filesystems fail explicitly.
No output is created on input/probe/schema failure.
An I/O failure while writing
may leave an incomplete bundle; treat a failed run as failed, choose a fresh
directory, and never consume a partial bundle as verified evidence.

Reported duration can include offsets or other streams, particularly when using
the format fallback. Reported frame count is not a decoded count. This tool does
not verify presentation timestamps, CFR/VFR, decodability, source-frame bounds,
audio synchronization, cross-document references, or export readiness. Those
remain separate execution gates.

## Tests

```bash
python -m pytest -q --junitxml=artifacts/validation/junit.xml
```

Unit tests cover unknown metadata, exact rational conversion, stream ambiguity,
duplicate identities, invalid IDs, changed inputs, failure handling, and evidence.
Integration tests generate short video/audio signals with ffmpeg in external
temporary directories and invoke the real CLI and ffprobe. They skip explicitly
if ffmpeg or ffprobe is unavailable; a skipped test is NOT_RUN, not PASS.
