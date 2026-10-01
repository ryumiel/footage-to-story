# Architecture

## Scope preserved from repository v2

The seven-stage data flow, eight project-local skills, four editorial profiles,
role split, and separation of source from job artifacts are retained. This revision
hardens contracts and their existing library-backed validation path. It does not
replace the design with a new orchestration framework or implement a video editor.

## Roles and boundaries

ChatGPT plans and reviews the edit. Codex is a local implementation/execution
surface on the ChatGPT/user side when explicitly delegated. Antigravity invokes
available Gemini media-analysis capabilities only for a bounded observation task.
The user remains responsible for authentic authorization and editorial approval.

A shared `.agents/skills/` directory avoids copied definitions. It is not an ACL:
both local agents may discover all instructions. The adapter skill restricts its
scope in prose, and a future runner must restrict actual tools, files, network
access, and writes. No automatic ChatGPT-to-local-runner bridge is implemented.

## Data flow

| Stage | Contract | Primary owner |
|---|---|---|
| Media inventory | `manifest.schema.json` | Deterministic local code / verified user input |
| Analysis scope | `analysis-request.schema.json` | ChatGPT |
| Media observations | `analysis.schema.json` | Antigravity + Gemini |
| Candidate selection | `selects.schema.json` | ChatGPT |
| Narrative structure | `story-plan.schema.json` | ChatGPT |
| Exact proposed cuts | `edit-plan.schema.json` | ChatGPT with verified deterministic timing |
| Review record | `review.schema.json` | AI review followed by authentic human approval |

All schema paths in this table are under `schemas/2.0.0/`. `common.schema.json`
contains shared definitions, not an eighth runtime stage.

Observations remain separate from profile-dependent scoring. Switching from
`winery` to `cycling` should reuse compatible observations, then repeat selection
and planning. Missing kinds of observation may require bounded reanalysis.
This cache/invalidation behavior is a requirement, not implemented runtime logic.

## Time model

Analysis/request/select ranges use integer milliseconds relative to the original
source start. They are 0-based and OUT-exclusive: `[start_ms, end_ms)`.
They locate candidate content, not verified frame cuts.

Edit plans use 0-based source and timeline frame indices with OUT-exclusive
source ranges. Frame rates are positive rational pairs; do not round 30000/1001
to 30. Source start timecode is metadata, not an offset to add indiscriminately.

A concatenated review video or cropped proxy needs a verified map back to source
IDs and offsets. This revision does not define that mapping artifact or perform
the conversion. A `proxy_path` alone is not a timing map. Unknown mappings block
execution; they must not be silently treated as identity transforms.

## Contracts versus execution

Executable helpers provide schema validation, ffprobe reported inventories with
raw evidence (`docs/media-manifest.md`), and supplied-document comparisons
(`docs/document-integrity.md`), and hash-bound decoded video scans
(`docs/media-verification.md`). Edit/timeline/audio and proxy mapping gates remain pending.
A schema can
require `job_id`, but cannot establish that two separately supplied job IDs match.
It can require a digest-shaped string, but cannot prove that the bytes were approved.

Sequential cuts with SOURCE/MUTE audio describe the first intended exporter
capability. Their presence in a valid plan does not mean that an exporter exists.
Unsupported overlays, J/L-cuts, transitions, separate audio, VFR conversion, and
mixed-FPS retiming remain out of scope until explicitly implemented and tested.
