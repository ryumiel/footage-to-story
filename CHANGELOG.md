# Changelog

## Unreleased - M1 execution helpers

- Added local ffprobe manifest extraction into unchanged 2.0.0 contracts.
- Preserved raw probe metadata, command/version provenance, and exact-byte hashes.
- Kept unknown metadata explicit and CFR status UNKNOWN pending timing checks.
- Added generated synthetic video/audio integration tests and failure tests.
- Documented the inventory tool's usage, evidence, and execution limits.
- Added a separate schema-first document integrity checker for job/ID/reference,
  range, declared-bound/scope, evidence, and review-link consistency.
- Preserved manual non-AI edit checks and explicit unverified media/approval gates.
- Added hash-bound MOV/MP4/WAV scans with full decoded-frame evidence, conservative
  video CFR/PTS checks, inventory comparisons, and explicit remaining audio/timeline gates.
- Rejected composite file demuxers and disabled external MOV track references so
  a wrapper hash cannot stand in for unbound dependent media.
- Extended synthetic tests to VFR, B frames, corrupted payloads, and truncated containers.
- Added fresh-media sequential video edit checks with exact CFR/FPS, decoded cut
  bounds, select-window containment, timeline continuity, rational duration, and
  document byte bindings; audio synchronization and approval remain separate.
- Captured exact Python runtime/test resolution in uv.lock and verified locked
  synchronization; documented external/build-tool deployment limits separately.

- Added decoded zero-origin contiguous PCM timing and exact SOURCE/MUTE sample
  cuts with no implicit resampling or fractional-sample rounding.
- Added external-trust OpenSSH signature verification over exact review bytes,
  binding job/revision and stored plan SHA-256. Human approval capture and signing
  authority deployment remain pending; the verifier never signs or enrolls keys.

- Added bounded FCPXML 1.7 generation with exact rational timing, encoded source
  URLs, SOURCE/MUTE mapping, fresh signed approval/media/edit gates, and
  checksum-pinned official DTD validation. Real Resolve acceptance remains NOT_RUN.

- Made SSH signing optional for trusted local conversations: live observed user
  approval binds job/revision/plan hash, and saved JSON remains insufficient to
  authorize export. Preserved independently signed verification for offline use.

## Repository v3 / tooling 0.3.0 - 2026-10-01

### Preserved
- Directly committed `.agents/skills/` with no installation/copy layer.
- ChatGPT editorial ownership and Antigravity/Gemini analysis-only boundary.
- Existing profile names, priorities, pacing, and story patterns.
- Source versus real-job-artifact separation.

### Changed
- Seven stage contracts moved to `schemas/2.0.0/`; added common `$defs`.
- Versioned `$id`, exact `schema_version`, and per-job identity.
- Closed root/nested objects and a narrowly constrained dynamic score map.
- Explicit unknown metadata, source-time conventions, evidence, and conditional rules.
- Required review digest/identity/time with status consistency and human-only approval shape.
- Standard `jsonschema` wrapper now uses an offline `referencing.Registry`, format
  checking, strict JSON input handling, and explicit schema-only result messages.
- Expanded synthetic fixtures, regression tests, and English documentation.

### Not included
- Automatic legacy-data migration, cross-document/media integrity execution,
  authentic approval capture, profile resolver, provider runner, FCPXML exporter,
  or actual Resolve import verification.
