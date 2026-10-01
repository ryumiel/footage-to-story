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

- [ ] Capture exact dependency resolution for the intended deployment environment.
- [x] Extract a media manifest with ffprobe and document evidence for metadata.
- [ ] Verify source identity, unique IDs, cross-job consistency, and time mappings.
- [ ] Check cross-document references, interval ordering, media bounds, and FPS.
- [ ] Check sequential timeline continuity, frame counts, and audio synchronization.
- [ ] Capture authentic human approval and verify revision plus exact plan digest.
- [ ] Implement and test a deterministic FCPXML exporter.
- [x] Generate real synthetic video/audio fixtures, not just JSON placeholders.
- [ ] Extend media fixtures to variable-rate and corrupted sources for timing gates.
- [ ] Validate XML and perform an actual DaVinci Resolve Free import test.

## M2 - Editorial stage execution

- [ ] Import actual transcripts/observations with provenance.
- [ ] Implement deterministic profile resolution and record resolved profile versions.
- [ ] Preserve prior locked decisions and invalidation rules across reruns.
- [ ] Persist job state, input hashes, run manifests, and resumable stage execution.
- [ ] Remap subtitles from source time into edited timeline time.

## M3 - Antigravity/Gemini media-analysis adapter

- [ ] Verify actual video/audio ingestion and timestamp behavior in the target runtime.
- [ ] Enforce tool-level permissions, bounded media access, and recorded upload consent.
- [ ] Implement provider-specific request/response handling without changing canonical contracts.
- [ ] Validate provider output locally and reject unsupported or fabricated fields.
- [ ] Add cost limits, retries, privacy controls, and bounded reanalysis.

Do not implement all milestones before testing the simple non-AI export path.
This revision does not imply that M1-M3 have been executed or verified.
