# Roadmap

## M0 - Reviewed workflow contracts

- [x] Canonical `.agents/skills/` committed directly.
- [x] Preserve ChatGPT editorial ownership and Antigravity analysis-only scope.
- [x] Separate source, synthetic fixtures, real jobs, and generated artifacts.
- [x] Seven strict stage schemas and common `$defs` on Draft 2020-12.
- [x] Versioned `$id`, uniform `schema_version`, explicit `job_id`.
- [x] Existing `jsonschema` validation and offline `referencing.Registry`.
- [x] Conditional constraints and enabled date-time format checks.
- [x] English instructions, migration policy, and design review.
- [x] Contract regression tests, including negative cases and validation limits.

## M1 - Deterministic non-AI execution path

- [x] Capture and verify exact Python runtime/test resolution for the local target.
- [ ] Package/pin external tools and build runtimes for a fully locked deployment.
- [x] Extract a media manifest with ffprobe and document evidence for metadata.
- [x] Check unique IDs, supplied job consistency, cross-document references, and interval ordering.
- [x] Check declared source bounds, request scope, and evidence interval coverage.
- [x] Bind supported local source scans to file hashes and check decoded video counts, PTS, and CFR.
- [x] Verify edit bounds against fresh decoded media and zero-origin CFR select-time windows.
- [x] Check exact sequential video timeline continuity, frame counts, FPS, and duration.
- [x] Verify zero-origin contiguous PCM timing and exact SOURCE/MUTE sample cuts.
- [ ] Implement general nonzero-origin/source-proxy mappings and compressed-audio final-export timing/conversion.
- [x] Verify externally trusted review signatures, job/revision, and exact plan digest.
- [x] Accept observed explicit user approval through a trusted caller, bound to exact plan bytes.
- [ ] Implement a general conversation-host adapter; optionally deploy human signing authority.
- [x] Implement and test a bounded deterministic FCPXML 1.7 exporter with fresh execution gates.
- [x] Generate real synthetic video/audio fixtures, not just JSON placeholders.
- [x] Extend media fixtures to variable-rate, corrupted, and truncated sources for timing gates.
- [x] Validate synthetic generated XML against the checksum-pinned official FCPXML 1.7 DTD.
- [x] Verify synthetic Resolve 21 import, source resolution, exact cuts/duration, and SOURCE/MUTE track structure.
- [x] Verify native Resolve PCM render tone/silence and manual moved-source relinking.
- [ ] Perform an audible listening check (rendered samples are verified).

## M2 - Editorial stage execution

- [x] Implement local supplied transcript/observation imports with preserved raw provenance.
- [x] Exercise real supplied SRT import with preserved raw bytes (published reference captions).
- [x] Exercise real canonical observations with their actual analysis request.
  A manual, explicitly authorized `agy` speech-only run imported six observations
  from two bounded Tears of Steel clips with preserved provider responses and
  verified source offsets. Candidate speech timing and quotation accuracy remain
  unverified; caption wording differences were retained.
- [x] Implement deterministic profile resolution and record resolved parent versions/hashes.
- [x] Preserve observed historical locked decisions and invalidate stale downstream records.
- [x] Persist job state, input hashes, immutable run records, and resume inspection.
  Editorial stages remain supplied by ChatGPT; resume never grants execution authority.
- [x] Remap imported quotation cues into SOURCE cuts with rational timing and SRT sidecars.
- [x] Accept original compressed audio for subtitle timing without requiring PCM intermediates.
- [x] Verify generated subtitle import in Resolve with permitted inputs.
  Caption text/line breaks and SOURCE/MUTE coverage passed; frame quantization
  can shift a subtitle boundary by less than one timeline frame.

## M3 - Antigravity/Gemini media-analysis adapter

Completed for the bounded speech-only adapter on zero-origin CFR originals.
Manual tests established coarse visual ingestion; general visual analysis and
non-speech sound descriptions are outside this adapter. Non-speech controls failed.
See [adapter scope and limits](docs/antigravity-analysis.md).

- [x] Verify actual video/audio ingestion and timestamp behavior in the target runtime.
  The reusable adapter ingested two authorized compressed speech clips, normalized
  four observations to verified source origins, and imported canonical analysis
  with raw provenance. Candidate speech timing and quotation accuracy remain NOT_RUN.
- [x] Enforce tool-level permissions, bounded media access, and recorded upload consent.
  Trusted-caller consent binds exact inputs; a sole enabled hook permits one
  hash-bound native media read and one validated output-only completion per attempt.
- [x] Implement provider-specific request/response handling without changing canonical contracts.
- [x] Validate provider output locally and reject unsupported or fabricated fields.
  Unknown fields, identities, invalid bounds, malformed transport, and mismatched
  completion payloads fail. Schema conformance does not detect invented speech.
- [x] Add cost limits, retries, privacy controls, and bounded reanalysis.
  Calls, attached duration, observed usage, output size, and process time are bounded;
  failed attempts are preserved and unknown usage forbids retry. Source metadata is
  stripped. A hard provider monetary ceiling remains NOT_IMPLEMENTED; provider
  retention is outside the adapter's control.

Do not implement all milestones before testing the simple non-AI export path.
Unchecked M1 capabilities and explicitly deferred human verification remain open.
