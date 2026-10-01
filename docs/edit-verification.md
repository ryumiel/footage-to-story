# Sequential Video Edit Verification

`scripts/verify_edit.py` validates supplied documents, reruns the supported media
scan, and checks frame-based source cuts and sequential video timeline math.
It does not modify inputs, select an edit, capture approval, or export a timeline.

```bash
source .venv/bin/activate
python scripts/verify_edit.py \
  --manifest work/JOB/inventory-001/manifest.json \
  --edit-plan work/JOB/edit-plan.json \
  --output-dir work/JOB/edit-check-001
```

This minimal command supports a manual non-AI plan whose `select_ref` values are
absent or null. If a plan references selects, also supply `--selects`, `--analysis`,
and `--analysis-request`. Optional `--story-plan` and `--review` are checked when
provided. All supplied records must pass their committed schemas and the
relationships documented in `docs/document-integrity.md`. Unknown declared bounds
needed by that record pass block preflight; the helper does not fill in or rewrite
unknown manifest metadata. Use an accurate inventory for the supported path.

## A fresh scan, not a cached PASS

The gate reads exact bytes of every supplied document and records their SHA-256.
It invokes `verify_media` on the current sources each time; there is no flag for
passing a saved media report as proof. The scan must bind the same manifest bytes
used by the document pass. Every inventory source must pass, including sources
not used in the edit. Supported formats, limits, and concurrent-change checks are
described in `docs/media-verification.md`.

The gate rechecks document stat signatures and hashes after calculations and
rechecks the scanned source stat signatures before publication. These detect
ordinary changes during the run; they do not provide an atomic filesystem snapshot
or prove that files remain unchanged after the check. A future exporter must
revalidate current inputs at its own execution boundary.

`analyze_edit` is an internal pure calculation helper for a trusted, freshly
generated in-memory scan. It is not a public validator for arbitrary saved report
JSON. Synthetic unit tests supply synthetic scan data explicitly; the real CLI
always performs the live scan.

## Supported frame and timeline rules

- A referenced source must have decoded video and a passing CFR scan. Audio-only,
  irregular, unknown, nonzero-origin, or proxy-mapped timing is unsupported here.
- The source's exact decoded rational FPS must equal timeline FPS. Equivalent
  rational pairs are accepted; mixed FPS and retiming are rejected.
- Source cuts use 0-based, OUT-exclusive frames. IN must precede OUT, and OUT may
  equal but not exceed the actual decoded frame count.
- Array order defines the timeline. The first item starts at frame 0; each next
  item's `timeline_in_frame` equals the previous item's calculated OUT. Gaps,
  overlaps, and unsorted arrays fail; items are never reordered or repaired.
- Each clip length is `source_out_frame - source_in_frame`. At identical source
  and timeline FPS, timeline OUT is IN plus that exact integer length.
- Calculated timeline OUT must stay within the contract's integer bound, 2^53-1.
- If a cut has a `select_ref`, the entire exact frame-time interval must fit that
  select's declared millisecond window. Times are compared as rational seconds;
  no rounded nominal FPS or rounding tolerance expands evidence coverage.
- On PASS, the report includes total timeline frame count and exact rational
  timeline duration. On FAIL, those total fields remain null rather than imply a
  verified timeline length.

This implements the identity source-time map for decoded zero-origin CFR video.
It does not add timecode offsets, nonzero origins, proxies, subtitles, or retiming.
Millisecond candidates still do not specify final cuts: the submitted frame-based
plan must choose supported boundaries and pass the exact containment comparison.

## Audio, approval, and export remain separate

SOURCE/MUTE policies are retained in the report. No audio synchronization, sample
cut rounding, priming/trimming, per-frame format stability, or source-audio timeline
mapping is verified. SOURCE can therefore receive a video-check PASS while audio
verification remains outstanding. Neither audio presence nor the policy label is
evidence of synchronization.

Prior locked decisions, permission authenticity, human approval capture, the
review's stored plan digest comparison, FCPXML conversion, and actual Resolve
import remain separate gates. The edit report's input SHA-256 values identify
the checked bytes; they are not a human approval record. Even a submitted APPROVED
review does not make this helper an approval or export gate.

## Outputs and exit codes

Choose a new run directory under `work/`, `artifacts/`, or external storage.
Existing directories are refused. Output contains the fresh scan/evidence bundle
in `media/` and a complete `edit-report.json` published last. Reports and raw data
are runtime evidence, not new stage contracts or Git source. Hard-link support is
required for final report publication, as with the media scanner.

- **0:** `EDIT_VIDEO_SCAN_PASS`; supported video/source/timeline checks passed.
- **1:** `EDIT_VIDEO_SCAN_FAIL`; a complete failure report and fresh scan evidence
  were written, for example a timeline gap or failed CFR media scan.
- **2:** Input/schema/document preflight, source identity/decoder/resource-limit,
  concurrent-change, or I/O error; no complete successful result is produced.

Invalid record relationships fail before media reads and output creation. I/O
failure during publication may leave an incomplete bundle. Retrying requires a
fresh directory; a failed run must not be consumed as verified evidence.
`--ffprobe`, `--timeout`, and `--max-output-bytes` are forwarded to the media scan.
Every successful CLI invocation prints the outstanding audio/approval/export gates.

## Synthetic tests

`tests/test_verify_edit.py` covers manual and evidence-linked plans, exact FPS and
fractional durations, start/adjacency/order, actual source bounds, unsupported
sources/rates, exact select-window containment, final integer limits, schema-first
rejection, byte hashes, input preservation, changes between phases, failure reports,
and real generated 25/30000/1001 FPS video through the CLI. Run
`python -m pytest -q`; machine reports belong under `artifacts/validation/`.
