---
name: build-story
description: Organize reviewed selects into evidence-supported chapters, duration budgets, and explicit coverage gaps.
---

# Build Story

Owner: ChatGPT. Read `AGENTS.md` and the applicable profile. Paths are repository-root
relative; use the contract in `schemas/2.0.0/story-plan.schema.json`.

## Inputs

Reviewed selects, actual job objective/target duration, active profile, and optional
story bible. Preserve prior user decisions without treating a summary as a transcript.

## Procedure

1. State a thesis supported by available material, not by desired but absent shots.
2. Build ordered chapters with IDs, titles, purposes, and real select IDs.
3. Allocate positive or explicitly unknown duration budgets. Do not give every topic
   equal time automatically; follow the profile and actual story needs.
4. Record missing evidence in `coverage_gaps`. A chapter with no `select_ids` must
   have at least one gap; it cannot later become a cut without real footage.
5. Use `transition_notes` for proposed transitions/B-roll. Notes do not mean an effect
   was implemented or an insert exists. Do not add unsupported top-level fields.
6. Keep quotations faithful. Separate user notes, inference, verified background,
   information cards, and actual speech. Do not "correct" a speaker's words silently.
7. Validate:

```bash
python scripts/validate_json.py schemas/2.0.0/story-plan.schema.json work/JOB/story_plan.json
```

## Output

A schema 2.0.0 story plan for the correct job, with ordered chapters and explicit
limitations. This is narrative planning, not frame-accurate editing or export.
