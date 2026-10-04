---
name: export-resolve
description: Preflight an approved plan and invoke a real deterministic Resolve exporter only when all execution gates exist.
---

# Export Resolve

Owner: deterministic local execution, under user-approved editorial control.
Read root `AGENTS.md`, `ROADMAP.md`, and `docs/validation.md`.
Current input contracts live in `schemas/2.0.0/`.

## Present implementation status

**Document, fresh-media, sequential-video, zero-origin PCM and bounded native
AAC-LC 48 kHz mono/stereo presentation/sample-cut checks exist.
External-trust signature and exact plan approval-binding checks exist; a general
conversation-host adapter remains pending. A bounded deterministic FCPXML 1.7 exporter
and official DTD validation exist (`docs/fcpxml-export.md`).** Bounded synthetic
Resolve 21 import, exact cut structure, PCM tone/silence render, and manual
moved-source relinking have passed. Audible listening remains NOT_RUN.
Do not infer general application compatibility from these fixture checks.
Native AAC serialization retains unchanged encoded assets; Resolve
import/render synchronization passed a bounded synthetic stereo control at 25 FPS.
Bounded zero-origin source preparation can select one AAC stream and omit unused
tracks/timecode in a new packet-identical copy; see
`docs/resolve-media-preparation.md`. Build a fresh prepared-file manifest and run
fresh gates; preparation does not transfer an existing plan approval.
Native source-viewer playback passed on a prepared real HEVC/AAC source.
Audible listening and measured real-source synchronization remain NOT_RUN. Other AAC profiles, nonzero
origins, unexplained padding, mixed formats and general conversion remain blocked.

## Required gates before an export

1. Validate manifest, plan, and review with the existing JSON Schema library.
2. Verify job/source IDs, actual files, source frame counts/FPS, mappings, and bounds.
3. Check sequential timeline math, source audio behavior, and all unsupported features.
4. Verify authentic user approval for the exact revision and SHA-256 of plan bytes.
5. Confirm actual exporter/version support. VFR, mixed rates, retiming, separate audio,
   overlays, and transitions must fail unless separately implemented and tested.
6. Run `scripts/export_fcpxml.py` within the documented supported scope; never
   compose final FCPXML with a language model. Fetch the checksum-pinned official
   DTD explicitly with `scripts/fetch_fcpxml_dtd.py` before offline validation.
7. Validate XML and test actual Resolve Free import as separate results.

Do not substitute a guessed CLI command or plausible XML when any gate is missing.
Keep originals read-only and put outputs under ignored `artifacts/<job_id>/`.

## Report

Distinguish NOT_IMPLEMENTED, NOT_RUN, BLOCKED, PASS, and FAIL for each gate. XML
structure passing does not prove clip relinking, cuts, audio synchronization, or
Resolve compatibility. Only report outputs that were actually created and checked.

Trusted callers can now pass observed explicit human conversation approval,
bound to the exact plan job/revision/hash, without SSH setup. See
`docs/approval-verification.md`. The caller owns authenticity; a saved HUMAN label
or receipt alone is not execution authority. Optional signed verification remains.

For locked selects or edits, the trusted API caller supplies `lock_record` and
`lock_context` as documented in `docs/lock-preservation.md`. Verification runs
before execution and again before publication. The standalone signed CLI blocks
locked inputs because it does not replay historical human authority from disk.
