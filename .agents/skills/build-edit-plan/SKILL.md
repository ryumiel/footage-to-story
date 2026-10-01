---
name: build-edit-plan
description: Specify verified source-frame cuts for a sequential timeline; reject unsupported effects or uncertain timing.
---

# Build Edit Plan

Owner: ChatGPT with deterministic timing support. Read `AGENTS.md` and
`docs/architecture.md`. Paths are repository-root relative; current contracts are
in `schemas/2.0.0/`.

## Inputs

Reviewed story/selects, verified manifest/time mapping, requested timeline FPS,
and prior user decisions. A deliberate manual M1 test may omit select links but
still needs genuine source identity and frame-boundary evidence.

## Procedure

1. Resolve every intended cut to an accessible source. Candidate milliseconds must
   not be presented as exact frames without timing evidence.
2. Use 0-based `source_in_frame`, OUT-exclusive `source_out_frame`, and 0-based
   `timeline_in_frame`. Preserve rational FPS as num/den, not rounded decimals.
3. Set `edit_mode: SEQUENTIAL_CUTS`, a timeline name, and a new plan revision.
4. Use SOURCE or MUTE audio only. Do not invent support for SEPARATE audio,
   overlaps, retiming, J/L-cuts, overlays, or transitions.
5. Include a reason and explicit lock state for every item. Link known selects;
   use null/omission only for an intentional manual plan with separately verified evidence.
6. Calculate, rather than duplicate, duration from OUT minus IN. Check source bounds,
   timeline continuity, FPS, and audio assumptions before claiming readiness.
   `docs/edit-verification.md` describes implemented fresh-media video and exact
   zero-origin PCM SOURCE/MUTE checks. Compressed-audio conversion, authentic
   approval, and export remain separate gates.
   Use the implemented checks within their documented scope; passing video
   checks alone does not establish audio synchronization or export readiness.
7. If a necessary boundary is unknown, report BLOCKED or a non-executable note;
   do not fabricate values to force a schema-valid final plan.
8. Validate the saved proposal:

```bash
python scripts/validate_json.py schemas/2.0.0/edit-plan.schema.json work/JOB/edit_plan.json
```

## Output

A declarative proposed plan, not FCPXML. Every byte change requires fresh approval
binding. No unsupported transformation is silently dropped or reported as applied.
