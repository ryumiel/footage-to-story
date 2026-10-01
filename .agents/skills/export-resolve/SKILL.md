---
name: export-resolve
description: Preflight an approved plan and invoke a real deterministic Resolve exporter only when all execution gates exist.
---

# Export Resolve

Owner: deterministic local execution, under user-approved editorial control.
Read root `AGENTS.md`, `ROADMAP.md`, and `docs/validation.md`.
Current input contracts live in `schemas/2.0.0/`.

## Present implementation status

**Document, fresh-media, sequential-video, and zero-origin PCM cut checks exist.
External-trust signature and exact plan approval-binding checks exist; human
approval capture and the FCPXML exporter remain pending.** Do not claim to export a real timeline.
This skill records the required procedure for when those components exist.

## Required gates before an export

1. Validate manifest, plan, and review with the existing JSON Schema library.
2. Verify job/source IDs, actual files, source frame counts/FPS, mappings, and bounds.
3. Check sequential timeline math, source audio behavior, and all unsupported features.
4. Verify authentic user approval for the exact revision and SHA-256 of plan bytes.
5. Confirm actual exporter/version support. VFR, mixed rates, retiming, separate audio,
   overlays, and transitions must fail unless separately implemented and tested.
6. Run the deterministic exporter; never compose final FCPXML with a language model.
7. Validate XML and test actual Resolve Free import as separate results.

Do not substitute a guessed CLI command or plausible XML when any gate is missing.
Keep originals read-only and put outputs under ignored `artifacts/<job_id>/`.

## Report

Distinguish NOT_IMPLEMENTED, NOT_RUN, BLOCKED, PASS, and FAIL for each gate. XML
structure passing does not prove clip relinking, cuts, audio synchronization, or
Resolve compatibility. Only report outputs that were actually created and checked.
