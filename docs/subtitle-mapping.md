# Source transcript to timeline subtitles

`map_subtitles.py` produces UTF-8 SRT plus a strict auxiliary mapping document.
It supports the current zero-origin, same-FPS sequential cuts only and regenerates
`verify_edit` from source media before publishing. Saved scan reports alone never
permit publication. This helper does not change a plan, create timeline effects,
write FCPXML, capture approval, or import subtitles into Resolve.

Only imported QUOTATION transcripts are eligible. Other classifications fail
rather than appearing as spoken dialogue. One transcript per source is supported.
Transcript job/source identity, manifest-byte digest, and declared source hash
must match. The transcript must remain beside its original import bundle: raw-input.bin, manifest.json, and provenance.json. Publication checks the SRT provenance format/job/raw digest, stored manifest binding, and exact cue equality with a fresh parse of the preserved raw SRT. Missing or modified bundle files fail; all bundle files are rechecked before publication. Supplier-declared origin remains unauthenticated. Subtitle publication also validates cue IDs, order, bounds, and
nonoverlap. A transcript's source hash may be unknown at import, but a freshly
verified manifest requires a real matching hash for subtitle publication.

For each SOURCE cut, cue time is intersected with the exact source frame interval.
The intersection is shifted by `timeline_in / FPS - source_in / FPS` using Python
`Fraction`. Adjacent edits split a straddling cue; repeated source usage repeats
its cue; MUTE edits produce no dialogue subtitles. Truncated cues retain the full
supplied text and set `truncated: true` for editorial review. The tool never guesses
which words belong to a partial cue.

Mapping entries store exact rational timeline seconds plus original cue bounds,
source ID, edit ID, transcript-byte digest, cue ID, language, and text. Millisecond
serialization rounds IN upward and OUT downward (`CEIL_IN_FLOOR_OUT`), keeping
serialized subtitles within their retained cut. Any intersection collapsing to
zero milliseconds fails the operation. Every timestamp is independently derived
from absolute frame positions, so rounding cannot accumulate across cuts.

```bash
python scripts/map_subtitles.py \
  --manifest work/job-001/manifest.json \
  --edit-plan work/job-001/edit-plan.json \
  --transcript work/job-001/import-transcript-001/transcript.json \
  --output-dir artifacts/job-001/subtitles-001
```

Provide `--analysis-request`, `--analysis`, and `--selects` when non-null select
references require them. Optional story/review documents use the existing stage
checks. Subtitle generation does not authorize exporting or uploading media.
Changes to transcripts require new sidecars; the mapping binds existing plan bytes
and cannot represent new approval of a changed plan.

Output contains `subtitles.srt`, `subtitle-map.json`, transcript snapshots, and the
fresh edit report. Publication is atomic to a new runtime directory and refuses
changed input documents, changed media stat signatures, existing outputs, and
concurrent cooperative writers. The map includes the SRT SHA-256, so text/timing
changes are detectable.

Synthetic rational mapping and generated-media acceptance are PASS. Real
transcript acceptance and target-application subtitle import are NOT_RUN.
Unsupported offsets, mixed-FPS retiming, proxies, and compressed-audio conversion
remain NOT_IMPLEMENTED.
