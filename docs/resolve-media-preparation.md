# Resolve source preparation

`scripts/prepare_resolve_media.py` makes a new whole-source MP4 containing one
H.264/HEVC video stream and an explicitly selected AAC-LC 48 kHz mono/stereo
audio stream. Both selected streams must have known zero presentation origins.
Unused audio, metadata, attached pictures, and embedded container timecode are
omitted from the copy. Originals remain unchanged; no video/audio encoding or
persistent PCM conversion occurs.

```sh
python scripts/prepare_resolve_media.py \
  --source /absolute/path/source.mp4 \
  --audio-stream-index 1 \
  --source-sha256 <original-file-sha256> \
  --output artifacts/<job_id>/<fresh-run-directory>
```

The helper requires the caller's expected original hash, checks it before and
after preparation, and publishes to a fresh output directory only after matching
every selected encoded packet's payload hash, rational PTS/DTS/duration, flags,
and side data. Codec configuration must also match. For HEVC, only the hvcC
VPS/SPS/PPS array-completeness bits may differ: parameter-set payloads and all
other configuration bytes remain identical. Raw configuration evidence is saved.
Per-process timeouts and packet-report size limits apply; whole-source copies
still need space comparable to their retained source streams.

The preparation report records both file hashes, selected original stream
indices, prepared stream indices, packet counts, original timecode tags, and the
command. Keep this provenance with the job. Build a fresh manifest for the
prepared file and run the normal decoded media/edit checks against it. Existing
plans and approvals bound to other file bytes do not transfer automatically.

Direct export of original multitrack/timecode containers remains unsupported.
This bounded preparation path does not implement arbitrary nonzero origins,
proxy mapping, compressed-audio conversion, or human approval capture. Packet
identity alone does not establish decoded edit validity or export readiness.
An actual final export still requires fresh checks and genuine approval bound
to the exact stored plan revision and hash.

Native source-viewer import and bounded playback have passed for a real prepared
HEVC/AAC source. That establishes application playback, not measured real-source
audio/video synchronization. Real-source render synchronization and audible
listening remain NOT_RUN. The separate synthetic AAC import/render control is
documented in [native-aac-resolve-control.md](native-aac-resolve-control.md).
