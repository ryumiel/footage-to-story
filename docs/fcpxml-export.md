# Bounded deterministic FCPXML export

`scripts/export_fcpxml.py` implements sequential FCPXML **1.7** serialization and
execution preflight. A bounded synthetic Resolve 21 import passed structural checks;
PCM render and moved-source relinking also passed; listening remains **NOT_RUN**. A passing
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

Obtain actual human approval of the exact plan through the trusted conversation
workflow described in `docs/approval-verification.md`. A trusted caller invokes
`export(paths, None, dtd_path, output, conversation_approval=event)` with that live
approval. The standalone CLI below retains the optional independently signed path.
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
synthetic approvals as actual authority. Conversation approval needs no key enrollment. A job review JSON alone cannot
authorize the API, and the CLI cannot replay a conversation receipt.

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
  retained sample rates are unsupported by this exporter. MUTE emits an explicit FCPXML `video` item, omitting an audio component.
  Resolve 21 imported enabled audio despite `asset-clip srcEnable="video"` in the
  first synthetic test, so that implicit-component representation is not used.
- Asset references follow first use in plan order; repeated sources share a
  resource. These are local XML IDs, not invented source/evidence identities.
  Assets reference percent-encoded absolute file URLs. Time values use exact reduced
  rational seconds. Names are XML-escaped; invalid XML characters fail validation.
- The sequence starts at zero with NDF timecode display; this does not convert
  source timing. Timeline format derives from the shared verified raster and FPS.
  Color management is not verified or converted; no color-space claim is invented.
- Locked selects/edits require a byte-bound historical lock record and trusted caller
  context (`docs/lock-preservation.md`). Changed or missing protected decisions fail.
  No conversion for proxies, nonzero origins, VFR, mixed rasters, separate audio,
  transitions, overlays, J/L-cuts, or multichannel routing is performed.

## Fresh execution boundary

The exporter snapshots exact document/signature bytes into a private temporary
run. It verifies the live conversation approval or optional signed review, runs the live `verify_edit` decoder checks on
those same document bytes, and compares the approval/edit plan and review digests.
It never consumes an arbitrary saved PASS report or exposes a gate-bypass flag.
All inventory sources must pass the media scan, even unused sources.

It generates XML with Python's standard XML serializer, then validates against the
checksum-pinned official DTD with system `/usr/bin/xmllint --nonet --dtdvalid`.
The DTD is copied privately; unpinned DTDs are refused before parser execution.
The system validator must pass the same root-ownership/path-write checks used by
approval verification. Validation is bounded to 15 seconds. POSIX system tools,
non-root execution, and actual human approval are required;
complete external-tool deployment pinning remains pending.

Before creating output and again after copying evidence, immediately before XML
publication, the exporter rechecks original document/signature/DTD bytes,
reruns approval verification against the same live event or current signing authority, and compares source
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

An explicitly approved synthetic Resolve 21 project imported the generated XML
and resolved its local source. Native OTIO export confirmed zero timeline origin,
25 FPS, source cuts [10,35) and [45,70), and 50 frames total. SOURCE imported
as an enabled audio clip for the first 25 frames; MUTE imported as an audio gap
for the final 25 frames. The initial implicit MUTE mapping failed this check;
the explicit `video` mapping passed on re-import without manual clip edits.
The importer initially suggested a one-hour origin, which was explicitly changed
to zero. This verifies imported structure for this fixture, not general compatibility.
A two-second native Resolve render contained 96000 stereo sample frames at 48000 Hz.
The first second retained the synthetic tone (RMS approximately 0.062499 per
channel); the final 48000 sample frames were exactly zero. Resolve applied
mono-to-stereo gain and brief edge fades, so SOURCE does not imply bit-for-bit
rendered PCM preservation. Listening remains **NOT_RUN**.

For relinking, an identical source copy was placed in a different folder. The
synthetic original path was temporarily renamed and the project reopened: Resolve
reported one missing clip. Selecting the relocated folder restored the source.
Native OTIO export referenced that folder for both video clips and retained audio,
with unchanged source ranges. The original path was then restored. This tests
manual missing-source relinking for an identical file, not proxy mapping or
automatic relinking in the exporter. Runtime evidence is kept in ignored artifacts. A general conversation-host adapter and optional human-key custody acceptance
remain outside this implementation.
Do not call all of M1 complete based on generated XML or synthetic signatures.
