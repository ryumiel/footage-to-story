# Bounded deterministic FCPXML export

`scripts/export_fcpxml.py` implements sequential FCPXML **1.7** serialization and
execution preflight. Resolve import compatibility has **NOT_RUN** status. A passing
export means the supported gates and official DTD validation passed; it does not
mean the application imported or played the timeline correctly.

## Obtain the validation specification

An explicit, separate helper fetches the DTD published on
[Apple's FCPXML 1.7 reference page](https://developer.apple.com/library/archive/documentation/Miscellaneous/Conceptual/LegacyDTDsFinalCutPro/FCPXMLDTDv1.7/FCPXMLDTDv1.7.html):

```bash
python scripts/fetch_fcpxml_dtd.py --output-dir artifacts/spec/fcpxml-001
```

The helper extracts the page's `pre` text, concatenates it in publication order,
strips outer whitespace, appends one newline, and encodes UTF-8. Its reviewed
SHA-256 is `89b8eddaedc75ee941bd1aef9cb7e237324174c5b2db84e70fdfc45d780204dd`.
Changed publication content fails checksum validation; do not silently replace the
pin. The official DTD retains its copyright comments in runtime storage and is
not vendored in Git. This download requires network access; exporting is offline
and never fetches a DTD automatically.

## Execution command

Obtain an actual human-reviewed, signed plan approval through the externally
administered authority described in `docs/approval-verification.md` first.
Invoking the following command generates an export from the supplied job:

```bash
python scripts/export_fcpxml.py \
  --manifest work/JOB/inventory-001/manifest.json \
  --edit-plan work/JOB/edit-plan.json \
  --review work/JOB/review.json \
  --signature work/JOB/review.json.sig \
  --dtd artifacts/spec/fcpxml-001/FCPXMLv1_7.dtd \
  --output-dir artifacts/JOB/export-001
```

When the plan references selects, also supply `--selects`, `--analysis`, and
`--analysis-request`. Optional `--story-plan` is checked if supplied. Do not use
synthetic approvals as actual authority. No real key enrollment, human approval
capture, or real-media export was performed to develop this implementation.

The output must be a new external directory or `artifacts/<job_id>/<new-run>`.
Repository `work/` is not an export destination. The command does not modify media
or job documents, invoke Resolve, upload data, or make editorial choices.

## Supported mapping

- Nonempty sequential cuts, 0-based and OUT-exclusive, with exact source/timeline
  FPS equality and zero-origin decoded CFR media. No gaps, overlaps, or retiming.
- Every used source must have the same known raster. Every decoded video frame
  must preserve that raster and be progressive. Pixel aspect ratio must be 1:1.
- Rotation/video stream or decoded frame side data, embedded source timecode, cover art, and extra
  data/subtitle tracks are rejected until explicit mappings exist. Source PTS zero
  does not establish that embedded source timecode is zero.
- SOURCE retains verified zero-origin contiguous PCM with exact integer sample
  cut boundaries, one common mono/stereo layout, and 48000 Hz sample rate. Other
  retained sample rates are unsupported by this exporter. MUTE uses the FCPXML
  `srcEnable="video"` attribute to discard source audio.
- Asset references follow first use in plan order; repeated sources share a
  resource. These are local XML IDs, not invented source/evidence identities.
  Assets reference percent-encoded absolute file URLs. Time values use exact reduced
  rational seconds. Names are XML-escaped; invalid XML characters fail validation.
- The sequence starts at zero with NDF timecode display; this does not convert
  source timing. Timeline format derives from the shared verified raster and FPS.
  Color management is not verified or converted; no color-space claim is invented.
- Any `locked: true` item blocks export while prior-decision verification is absent.
  No conversion for proxies, nonzero origins, VFR, mixed rasters, separate audio,
  transitions, overlays, J/L-cuts, or multichannel routing is performed.

## Fresh execution boundary

The exporter snapshots exact document/signature bytes into a private temporary
run. It verifies the signed review, runs the live `verify_edit` decoder checks on
those same document bytes, and compares the approval/edit plan and review digests.
It never consumes an arbitrary saved PASS report or exposes a gate-bypass flag.
All inventory sources must pass the media scan, even unused sources.

It generates XML with Python's standard XML serializer, then validates against the
checksum-pinned official DTD with system `/usr/bin/xmllint --nonet --dtdvalid`.
The DTD is copied privately; unpinned DTDs are refused before parser execution.
The system validator must pass the same root-ownership/path-write checks used by
approval verification. Validation is bounded to 15 seconds. POSIX system tools,
non-root execution, and the externally configured signing authority are required;
complete external-tool deployment pinning remains pending.

Before creating output and again after copying evidence, immediately before XML
publication, the exporter rechecks original document/signature/DTD bytes,
reruns approval verification against current signing authority, and compares source
stat signatures with the fresh scan. These detect ordinary concurrent changes;
they do not provide atomic storage snapshots or guarantee source identity after
publication. Resolve relinking later requires the original sources to remain intact.
The approval binds the plan, not independently unsigned inventory or evidence.

Output contains `check/` with fresh media/edit evidence, `export-report.json` with
XML/DTD/approval bindings, and `timeline.fcpxml` published last by hard link.
Hard-link support is required. Exit **0** means all implemented gates passed;
exit **2** is an input, gate, tool, or publication failure. Failures before
publication create no final export; publication I/O failures can leave an incomplete
bundle. Use a new directory for retries and never consume incomplete output.

## Synthetic verification and remaining acceptance

`tests/test_export_fcpxml.py` verifies exact rational cuts/offsets, resource reuse,
file URL encoding, SOURCE/MUTE attributes, XML escaping, unsupported scope,
DTD rejection, and publication-boundary changes. Integration tests generate PCM
video at 25 and 30000/1001 FPS and use explicitly synthetic signing keys with a
substituted test-only external trust boundary. No keys are enrolled in `/etc`.

Fetch the pinned DTD explicitly before running the integration tests. Set
`FCPXML_DTD_PATH` to its path for tests, or use the default ignored
`artifacts/fcpxml-spec/FCPXMLv1_7.dtd`. Tests without that file are marked SKIP,
which is **NOT_RUN**, not proof of XML validation. The exporter itself always
requires and validates the actual DTD.

Actual Resolve import/relinking, cut positions, total duration, and SOURCE/MUTE
playback must be checked in a separately authorized synthetic project. Human-key
custody and genuine approval acceptance also remain unverified in deployment.
Do not call all of M1 complete based on generated XML or synthetic signatures.
