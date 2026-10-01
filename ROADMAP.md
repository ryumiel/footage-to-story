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
- [ ] Implement nonzero-origin/source-proxy mappings and compressed-audio timing/conversion.
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
- [ ] Exercise real canonical observations with their actual analysis request.
- [x] Implement deterministic profile resolution and record resolved parent versions/hashes.
- [x] Preserve observed historical locked decisions and invalidate stale downstream records.
- [x] Persist job state, input hashes, immutable run records, and resume inspection.
  Editorial stages remain supplied by ChatGPT; resume never grants execution authority.
- [x] Remap imported quotation cues into SOURCE cuts with rational timing and SRT sidecars.
- [x] Accept original compressed audio for subtitle timing without requiring PCM intermediates.
- [ ] Verify generated subtitle import in Resolve with permitted inputs.

## M3 - Antigravity/Gemini media-analysis adapter

- [ ] Verify actual video/audio ingestion and timestamp behavior in the target runtime.
- [ ] Enforce tool-level permissions, bounded media access, and recorded upload consent.
- [ ] Implement provider-specific request/response handling without changing canonical contracts.
- [ ] Validate provider output locally and reject unsupported or fabricated fields.
- [ ] Add cost limits, retries, privacy controls, and bounded reanalysis.

Do not implement all milestones before testing the simple non-AI export path.
This revision does not imply that M1-M3 have been executed or verified.
