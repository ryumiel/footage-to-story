---
name: footage-pipeline
description: Route a Footage to Story job to the next missing or stale stage; do not bypass review or execution gates.
---

# Footage Pipeline

Read root `AGENTS.md`, `README.md`, and `ROADMAP.md`. Paths here are repository-root
relative. Use this skill for broad requests to process, continue, or review a shoot.
Do not interpret BUILD work as a successfully edited video.

## Determine the stage

Inspect real accessible job artifacts, then locate the earliest missing or stale
stage: manifest -> analysis request -> observations -> selects -> story -> edit
plan -> review -> deterministic export. Current contracts are `schemas/2.0.0/`.

Before selecting a stage, confirm the job identity, accessible inputs, desired
profile, user authorizations, and implementation status. Preserve prior locked
human decisions. Profile changes alter editorial choices, not observed facts;
reanalysis is needed only where actual observation coverage is missing.

## Delegate by responsibility

- `prepare-analysis`: ChatGPT defines a bounded observation request.
- `analyze-footage-gemini`: Antigravity/Gemini analyzes permitted media only.
- `build-selects`, `build-story`, `build-edit-plan`: ChatGPT editorial stages.
- `review-edit-plan`: review against evidence; human approval is a separate event.
- `export-resolve`: preflight and call an implemented deterministic exporter only.

Codex may perform delegated local development/execution. Sharing these skills does
not authorize Antigravity to make editorial choices or grant tools/network access.

## Current execution limit

Only schema validation is implemented. Refer to the roadmap for media ingestion,
referential integrity, approval verification, and export. Do not invent a command
for a missing implementation. Missing execution capability is BLOCKED, not PASS.

## Report

State the job, stage, chosen skill, existing outputs, missing inputs, whether real
media analysis is needed, and tests actually run. Store real artifacts under
`work/<job_id>/` or an external private workspace, never as source fixtures.
