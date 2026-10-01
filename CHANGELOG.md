# Changelog

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
