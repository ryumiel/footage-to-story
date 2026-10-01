# Footage to Story

A reusable, source-traceable video editing workflow with **ChatGPT as the primary
editorial orchestrator**, **Antigravity + Gemini for bounded video/audio analysis
only**, and **DaVinci Resolve Free as the target editing environment**.

**Repository revision:** v3 / tooling 0.3.0. **Stage contracts:** 2.0.0.
This is a reviewed skills-and-contracts foundation, not a finished automatic editor.

## What is available

- Eight committed project-local skills in `.agents/skills/`; no skill-copy or
  installation script is needed for repository-local use.
- The four editorial profiles from v2, unchanged in meaning and values.
- Seven strict stage contracts plus a shared `$defs` resource.
- Offline JSON Schema validation using `jsonschema` and `referencing`.
- Reviewed Python runtime/test resolution in `uv.lock`.
- Local ffprobe manifest extraction with exact-byte hashes and raw metadata evidence.
- Cross-document record checks for IDs, references, ranges, and declared bounds/scope.
- Bound source-byte checks and conservative decoded video timing scans for MOV/MP4 and WAV.
- Fresh-media sequential video edit checks for source bounds, exact FPS, and timeline continuity.
- Exact zero-origin PCM sample cuts and SOURCE/MUTE checks in the fresh edit gate.
- External-trust OpenSSH review verification bound to exact plan bytes and revision.
- Bounded deterministic FCPXML 1.7 export with fresh gates and pinned official DTD validation.
- Synthetic positive fixtures, negative tests, and explicit validation-boundary tests.
- English instructions, migration guidance, architecture, and a design review.

Compressed-audio timing/conversion, nonzero-origin/proxy maps, genuine
approval capture, prior-lock verification, and live Gemini analysis remain unimplemented.
A `SCHEMA_VALID` result is not approval to upload media or export a timeline.

## Responsibility split

| Component | Responsibility |
|---|---|
| ChatGPT | Analysis requests, selects, narrative, edit plans, editorial review |
| Codex | Local development and explicitly delegated ChatGPT/user-side execution |
| Antigravity + Gemini | Observe approved media and return analysis; no independent editorial decisions |
| Deterministic code | Schema, inventory, document, source/video, and sequential video-edit checks now; PCM sample cuts and signature-bound approval verification and bounded FCPXML export now |
| Human editor | Confirm facts, authorize uploads, approve exact plans, finish in Resolve |

The same committed skills can be read by local agents. Visibility is not an access
control boundary. The analysis-only scope is an instruction and must later be
reinforced by tool permissions. A browser ChatGPT Project does not gain access to
an arbitrary local directory simply because that directory exists; share or expose
the repository through an actually available tool or environment.

## Repository layout

```text
.agents/skills/             COMMIT: canonical workflow instructions
chatgpt/                    COMMIT: thin project-level instructions
profiles/                   COMMIT: editorial preferences
schemas/2.0.0/              COMMIT: seven contracts + common definitions
scripts/validate_json.py    COMMIT: standard-library integration and CLI
scripts/probe_manifest.py   COMMIT: local reported inventory and evidence
scripts/check_integrity.py  COMMIT: document relationships and declared bounds
scripts/verify_media.py     COMMIT: source hashes and decoded video timing evidence
scripts/verify_edit.py      COMMIT: live source bounds and sequential video timeline math
scripts/verify_approval.py  COMMIT: external-trust signatures and exact plan approval binding
scripts/export_fcpxml.py    COMMIT: gated deterministic FCPXML 1.7 serialization
scripts/fetch_fcpxml_dtd.py COMMIT: explicit official DTD retrieval with checksum pin
examples/contracts/        COMMIT: deliberately synthetic test documents
tests/                      COMMIT: automated contract tests
docs/                       COMMIT: design, compatibility, migration, review
work/                       IGNORE: real per-shoot inputs and intermediates
artifacts/                  IGNORE: exports and machine-generated test reports
cache/, logs/               IGNORE: derived runtime data
```

Raw media can remain outside this repository. Do not move originals to make the
example paths work; example paths are intentionally fictional.

## Run the implemented checks

Use Python 3.11 or newer. Install dependencies once in an isolated environment;
this is Python environment setup, not a project-skill deployment process.

```bash
python -m venv .venv
# macOS / Linux:
source .venv/bin/activate
# Windows PowerShell alternative:
# .venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pytest -q
python scripts/validate_json.py \
  schemas/2.0.0/analysis.schema.json \
  examples/contracts/analysis.json
```

Dependency installation may need network access. Validation itself resolves only
registered local schemas and does not fetch references over the network.
For locked Python package setup use `uv sync --locked --extra dev`; see
`docs/dependencies.md`. The pip command above does not enforce that lock. External
tools and complete deployment packaging remain separate from Python resolution.

Exit codes: **0** schema-valid; **1** data-contract violation; **2** input/schema
configuration error. The validator does not coerce, repair, insert defaults, or
rewrite the input document.

## Intended workflow

```text
manifest -> analysis request -> Antigravity/Gemini observations
         -> ChatGPT selects -> story -> frame-based edit plan
         -> human review bound to exact plan bytes
         -> integrity/media gate -> deterministic exporter -> Resolve Free
```

This describes the intended workflow. Contract validation, local reported-manifest
extraction, document relationship checks, bounded video timing scans, and sequential
video edit checks are implemented. Full stage execution remains pending.
Read `ROADMAP.md` before asking an agent to run it.

## Contract policy

Every stage document carries `schema_version: "2.0.0"` and `job_id`. Each schema
has a versioned, absolute `$id`. Concrete objects reject unknown properties.
`scores` is the sole intentional dynamic-key object and constrains both keys and
values. Unknown metadata is explicit `null` where permitted, not guessed.

The schema IDs under `https://footage-to-story.example/` are logical identifiers,
not a hosted service. The validator maps them to repository files offline.

Changing a closed contract is a compatibility decision, not a cosmetic edit.
Legacy v2-repository documents are not silently accepted or migrated. See
`docs/schema-versioning.md` and `docs/migration-from-v2.md`.

## Start reading here

- `docs/review.md`: findings, fixes, and unresolved execution gates.
- `docs/media-manifest.md`: ffprobe CLI usage, evidence, and limitations.
- `docs/document-integrity.md`: supplied-document checks and separate execution gates.
- `docs/media-verification.md`: supported formats, decoded timing, identity, and scan limits.
- `docs/edit-verification.md`: fresh source-bound checks and sequential video timeline rules.
- `docs/approval-verification.md`: trust setup, exact-byte signature checks, and authority limits.
- `docs/fcpxml-export.md`: supported export mapping, official validation, and acceptance limits.
- `docs/schema-catalog.md`: the field-level contract decisions.
- `docs/validation.md`: exactly what the validator does and does not prove.
- `docs/repository-policy.md`: source versus real job data versus build outputs.
- `docs/references.md`: the external documentation used for this revision.
