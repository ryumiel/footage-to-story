# Local Media Verification

`scripts/verify_media.py` binds a scan to the exact manifest and source file bytes,
decodes media with ffprobe, and conservatively checks video frame timing. It reads
only explicitly supplied local job sources, does not modify the manifest or media,
and does not create an edit or export.

```bash
source .venv/bin/activate
python scripts/verify_media.py \
  --manifest work/JOB/inventory-001/manifest.json \
  --output-dir work/JOB/media-check-001
```

Supply a new output directory. Repository-local output must be below `work/` or
`artifacts/`; external storage is allowed. Source paths in the manifest must be
absolute and point to regular files. IDs and job identity are retained. Distinct
source IDs pointing to the same file identity are rejected.

## Supported scope

The initial scanner supports the MOV/MP4 demuxer family and WAV only. The decode
command restricts demuxers to `mov,wav`, network protocols are disabled, and MOV
external track references are disabled explicitly with `-enable_drefs 0`.
Composite/playlist files such as ffconcat are rejected before decoding dependent
assets: hashing a playlist would not bind the bytes of its referenced clips.
This is a bounded format policy, not a general filesystem sandbox.

The same inventory stream policy applies: at most one usable video stream and
one audio stream, excluding cover art from video selection. The scanner requires
actual decoded video PTS and positive frame durations in the reported integer
time base. It does not substitute `best_effort_timestamp`, advertised average
FPS, or a duration-times-FPS estimate.

The [official ffprobe documentation](https://ffmpeg.org/ffprobe.html) describes
`-show_frames`, stream metadata, and JSON output. Some tool/container combinations
omit required timing fields; those inputs fail rather than receive guessed timing.

## Identity and observed video timing

The manifest must first pass its committed JSON Schema and local ID checks.
`content_sha256` is required for every source and must match its exact file bytes.
The scanner records the manifest's exact-byte SHA-256. It compares source stat
signatures before/after decoding and again at the end of the batch, including the
manifest. This detects ordinary concurrent changes; it is not a filesystem
snapshot or a permanent identity guarantee after the scan. A later execution gate
must recheck current bytes instead of trusting a previously saved PASS report.

Each supported video's decoded frames are counted in presentation order. The
scanner checks:

- Actual PTS must exist and increase strictly. Duplicate or backward PTS fail.
- The first video PTS must be zero. Nonzero/negative origins fail until explicit
  source-time mappings are implemented; no implicit shift is applied.
- At least two frames and all frame durations must be available.
- CFR requires one exact PTS delta and every frame duration, including the last,
  to equal it. FPS is derived as the reciprocal of delta times time base, retaining
  exact rational arithmetic, including 30000/1001.
- Irregular deltas with a spread greater than one tick are labeled observed VFR.
  One-tick variation or inconsistent frame durations remain UNKNOWN because
  container quantization may be involved. Both states fail the initial CFR gate.
- The observed span is `(last PTS + last duration - first PTS) * time_base`.
  Non-null inventory frame count, FPS, CFR declaration, selected-stream time base,
  and video duration rounded up to milliseconds must agree with the observation.
  Unknown inventory values can be measured in the report without rewriting them.
- A non-null proxy path fails until proxy/source mappings are implemented.

These verify the decoded presentation structure reported by the installed decoder,
not visual truth or a universal guarantee that every codec defect is detectable.
Any ffprobe nonzero exit or error-level stderr fails, even if some frames were
returned. Frame count mismatches can also reveal silent incomplete decodes.

## Audio and remaining gates

Audio evidence records decoded audio frame/sample counts and compares reported
stream sample rate/channels with inventory claims. A separate `audio.timing`
result checks zero-origin contiguous PCM timestamps, sample-count durations,
stable decoded channels/sample format, and absence of padding or side data.
Unsupported or failing audio timing does not itself fail the general media scan:
a MUTE edit can discard that audio. A general media PASS therefore does not prove
SOURCE audio readiness. Audio-only PASS covers identity, decoded sample presence,
and reported format comparisons; inspect the separate timing result for PCM.

The scanner does not consume an edit plan, verify edit cut bounds, convert select
milliseconds into frames, check timeline continuity, or verify audio alignment.
`scripts/verify_edit.py` now reruns the scan and checks supported CFR cut bounds,
select-window containment, sequential video math, and retained SOURCE PCM sample cuts
(`docs/edit-verification.md`).
Document references are checked separately by `scripts/check_integrity.py`.
Proxy maps, prior locks, permission authenticity, authentic human approval and
plan-digest verification, XML export, and actual Resolve import remain separate
gates. No result from this helper authorizes export.

## Reports and failure behavior

The output contains raw `decode-0001.json`, etc., command/version/hash/stat
provenance files, and `media-report.json`. These are machine evidence, not new
stage contracts; store them as private job artifacts, not Git source. The report
records PASS/FAIL per source, observed rational timing, issue codes, the manifest
digest, and an explicit `not_checked` list. Raw metadata remains untrusted data.

Exit codes:

- **0:** A PASS scan report was written within the scope above.
- **1:** A FAIL report was written, for example VFR/unknown timing or mismatched
  inventory metadata. Raw evidence is retained alongside that report.
- **2:** Input/schema, identity, decoder, resource-limit, or I/O failure. No complete
  successful report is produced. Source/hash/decode failures occur before creating
  output; I/O failures during publication may leave an incomplete bundle.

The default timeout is 60 seconds per ffprobe subprocess. `--timeout` can change
it. Hashing is outside that subprocess timeout. `--max-output-bytes` defaults to
64 MiB per raw frame JSON file. Output is spooled to temporary disk rather than
unbounded capture in memory; the size cap is checked after decoding, before loading
JSON. It is not a disk quota during the subprocess. Budget temporary disk space
for the decode and adjust limits deliberately for long clips.

Evidence is copied into a newly created run directory. The complete report is
published last using a same-directory hard link, so the output filesystem must
support hard links. Existing run directories are refused. As with inventory,
treat a failed run as failed and use a fresh directory for retry.

## Synthetic verification

`tests/test_verify_media.py` exercises exact and fractional CFR, B-frame decode
ordering, generated NTSC video with audio, VFR, audio-only files, decoder-damaged
payloads, truncated containers, and composite-file rejection. Unit tests cover
missing/estimated PTS, durations, nonzero origins, unknown/ambiguous streams,
inventory mismatches, hash binding, input preservation, batch mutations, and
timeout/size/error handling. Generated media stays in external temporary storage.
Run `python -m pytest -q` and store machine reports under `artifacts/validation/`.
