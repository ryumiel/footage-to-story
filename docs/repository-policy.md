# Repository Policy: Source, Job Data, and Generated Outputs

**The Git repository contains the reusable method. A job contains one shoot. A
build artifact contains something generated from source or job data.** Do not
classify a file solely by its extension or whether an AI helped write it.

| Category | Examples | Default treatment |
|---|---|---|
| Reusable source | `.agents/skills/`, profiles, schemas, code, dependency configuration | Commit |
| Durable design records | Architecture, migration policy, reviewed decisions, changelog | Commit |
| Deliberate synthetic test inputs | Fictional JSON plans and observations under `examples/contracts/` | Commit |
| Real shoot inputs and intermediates | Job YAML, story bible, transcript, observations, selects, plans, review/consent | Private `work/` or external workspace; do not commit here |
| Generated outputs | FCPXML, subtitles, renders, skill ZIPs, test reports | `artifacts/`, `dist/`, or external output storage; do not commit |
| Transient/secret data | Cache, logs, credentials, tokens, local environment files | Ignore; protect and apply retention policy |

## Canonical skills

`.agents/skills/<name>/SKILL.md` is source and must remain trackable. No mirror tree,
installer, copying script, or generated skill bundle is needed for local Codex and
Antigravity use. If a separate distribution package is requested in the future,
its source stays here and its generated archive stays outside Git.

## Why a fixture edit plan is committed

`examples/contracts/edit-plan.json` is intentionally fictional test input, not a
plan for a real shoot. It is therefore source. A real `work/JOB/edit_plan.json` is
private runtime data and stays out of this repository. Do not use a blanket JSON
ignore rule that would hide schemas and test fixtures.

## Storage layout

```text
footage-to-story/             reusable source repository
  work/JOB/                  optional ignored private working directory
  artifacts/JOB/             optional ignored render/export directory
footage-to-story-work/        optional external private workspace
media-archive/                original files and backups
editorial-archive/            optional separate private long-term job archive
```

An ignored file is not necessarily disposable. Back up valuable originals,
transcripts, editorial decisions, approved plans, permission records, and source
mappings under a separate retention policy. This repository does not delete them.

`.gitignore` is not a confidentiality guarantee and does not untrack files already
committed. Inspect `git status` and the staged diff before committing. Remove an
already tracked runtime file from the index deliberately, retaining the local file
when appropriate. Do not silently run destructive cleanup or history rewriting.

## Verification artifacts

Automated run logs, JUnit XML, environment snapshots, and machine inventories go
under ignored `artifacts/validation/`. A maintained prose design review belongs in
`docs/review.md`. The delivered verification ZIP is a generated artifact and must
not be added to the source repository. No actual Git commit or remote push is
performed by producing a source archive.
