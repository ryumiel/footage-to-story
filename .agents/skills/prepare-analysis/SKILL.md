---
name: prepare-analysis
description: Create a bounded Gemini observation request with explicit source ranges and upload policy; do not select the edit.
---

# Prepare Analysis

Owner: ChatGPT. Read `AGENTS.md` and `docs/schema-catalog.md`. All paths below are
repository-root relative; current contracts are in `schemas/2.0.0/`.

## Inputs

A schema-valid manifest, an editorial profile, the analysis objective, actual
source-time mappings, and any real user upload permission. A story bible can guide
questions but is not evidence that a shot or spoken line exists.

## Procedure

1. Verify source/job identity and known durations from accessible evidence. The
   current schema validator does not perform those cross-document checks.
2. Choose the smallest source ranges needed. Each source must have a nonempty
   `ranges` list with explicit source-relative millisecond bounds; no implied full upload.
3. Set `request_id`, `runner: antigravity`, and `provider: gemini`. Do not use Gemini CLI.
4. Keep `cloud_upload_allowed` false unless the user has authorized the specific
   transmission. For true, include a real `authorization_ref`; never invent one.
5. Ask for observations, audible/visible content, uncertainty, and candidate times.
   Do not ask the analyzer to choose final selects, pacing, or narrative order.
   For the implemented `agy` runner, use speech/dialogue or `audible_dialogue`
   categories in default speech mode, or exactly `visual` plus one of those categories
   in explicit audiovisual mode. Both paths require exact frame/sample-aligned
   ranges on verified zero-origin CFR sources. Combined input uses one synchronized
   video clip with compressed speech audio. Non-speech descriptions remain excluded.
6. Retain known facts, notes, and hypotheses as context, not manufactured observations.
7. Write the request and run the existing validator:

```bash
python scripts/validate_json.py schemas/2.0.0/analysis-request.schema.json work/JOB/analysis_request.json
```

Unknown duration/mapping or missing consent blocks the affected request. Do not
create arbitrary bounds solely to satisfy the schema.

## Output

`analysis_request.json` with `schema_version: "2.0.0"` and the correct `job_id`.
Report schema result separately from scope/permission checks and runner availability.

## Explicit separate visual pass

Use `mode="visual"` with exactly the `visual` request category for visible content
only. The strict auxiliary visual response contract rejects dialogue and
audio-availability claims; combined mode still requires both modalities.
Visual staging retains a synchronized MP4 with compressed primary audio, so
explicit upload consent must cover the actual MP4 bytes even though the provider
is asked for visuals only. A speech pass uses its own exact request, MP3, consent
binding, call budget and provenance. Do not infer speaker identity or verified
boundaries when comparing the passes.

An explicit positive source-scan timeout can permit a longer full source decode
without extending provider or other staging deadlines. All source clocks, exact
frame/sample checks, 64 MiB scan-output and 20 MiB clip limits still apply.
A longer deadline or a RUNNING record is not source acceptance.

## User-selected fast exploratory analysis

A user may explicitly choose reusable resized analysis copies with lightweight
checks. In that path, use reported zero-origin matching frame rates, selected
audio and aligned candidate ranges; full decoded source proof is `NOT_RUN`.
Plan with approximate candidate timestamps and retain the original source IDs.
Use `analysis_cache_dir` on the trusted-caller runner API as documented in
`docs/antigravity-analysis.md`. The existing strict path above remains available.
Do not treat an analysis-copy record as a general proxy/export mapping or final
frame verification. Upload permissions and budgets remain unchanged.
