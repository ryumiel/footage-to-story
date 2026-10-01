# Contract and Architecture Review

**Review date:** 2026-10-01  
**Baseline:** supplied `footage-to-story-v2.zip`  
**Baseline SHA-256:** `b80a4c5cd418b8a94d27e47b9e56057e905eeb7ea4e3d61ca6442c58294d05ac`  
**Reviewed source:** repository v3 / tooling 0.3.0 / contracts 2.0.0

## Outcome

The contracts are substantially more explicit and testable, and the standard
library-backed validation path is implemented. The repository is suitable as a
version-controlled workflow foundation. **It is not ready to execute a complete
video-editing job or produce a verified Resolve timeline.**

This is a durable design review and belongs in source control. Machine test output,
environment snapshots, and packaging inventories belong in ignored
`artifacts/validation/` and are distributed separately.

## Scope and baseline findings

The source archive was inspected directly. Its seven stage schemas all allowed
additional root properties. Across the schema documents, 17 explicitly typed
objects were open or dynamic, with no `additionalProperties: false` object closure.
The only test checked schema meta-validity; it did not exercise positive/negative
instance validation or local reference resolution.

The agreed role split and canonical `.agents/skills/` location were already present
and are preserved. All four profile files remain byte-for-byte unchanged. The
revision does not add a custom schema engine, copied skill distribution layer,
web UI, workflow server, or a different editing product.

## Findings and dispositions

| ID | Finding | Disposition |
|---|---|---|
| C01 | Unknown and misspelled fields could pass at root and nested levels | Closed all concrete objects; constrained dynamic score map is the explicit exception |
| C02 | Repeated definitions could drift across stages | Added common `$defs` for identifiers, times, rates, notes, confidence, digests, and scores |
| C03 | No stable schema identity or reference-resolution policy | Added versioned absolute `$id` values and offline standard `referencing.Registry` |
| C04 | Stage-specific version fields did not identify a coherent strict contract | Introduced exact `schema_version: 2.0.0`; documented this as breaking, with no silent migration |
| C05 | Job identity and timing/unknown-value conventions were insufficiently explicit | Added `job_id`, known/null metadata rules, rational rates, and OUT-exclusive conventions |
| C06 | Evidence and content requirements were too weak for normalized observations | Required evidence, bounded confidence, and type-specific observed content |
| C07 | Request scope and consent records were ambiguous | Required explicit ranges and authorization reference when upload is enabled; genuine permission remains a runtime gate |
| C08 | Plans could describe unsupported audio behavior without an implementation | Limited current vocabulary to sequential SOURCE/MUTE cuts; unsupported operations fail the contract |
| C09 | Review did not require the digest described by the documentation | Added exact-byte SHA-256 and consistent reviewer/status fields; authenticity and hash comparison remain pending |
| C10 | CLI could fail opaquely on bad paths, refs, ambiguous JSON, or mixed error paths | Added supported parser hygiene, library error handling, explicit exit codes, and pointer formatting |
| C11 | Schema-valid could be mistaken for safe-to-export | CLI and skills explicitly separate schema conformance, integrity, authorization, and import results |
| C12 | Skill output descriptions could conflict with stricter field vocabulary | Updated all eight English skills and supplied matching fictional fixtures |

## Deliberate design choices

The schema documents are the source of truth. We did not introduce Pydantic models
or generated schemas in parallel; maintaining two independently authored contracts
would create a new synchronization problem. Existing `jsonschema`/`referencing`
implementations perform validation and reference handling.

`additionalProperties: false` is used at the actual object definitions. No object
is extended by combining an already closed shape with unrelated properties.
`unevaluatedProperties` is therefore unnecessary here, not an omitted requirement.

Unknowns remain representable, while downstream execution must refuse unsupported
unknowns. An empty analysis/select list can honestly express a completed stage with
no useful findings. Missing runtime capability must not be mislabeled as an empty
successful analysis.

The plan hash covers exact file bytes, not an unimplemented canonical JSON format.
This deliberately invalidates approval on formatting-only changes too. It does not
prove authorship, media identity, or that a human approved those bytes.

## Remaining gates - do not hide them

| Gate | Current state | Required next work |
|---|---|---|
| Cross-document integrity | NOT_IMPLEMENTED | Compare IDs/jobs/refs, key uniqueness, source bounds, approved scope, and prior locks |
| Media/timing verification | NOT_IMPLEMENTED | Actual probing/decoding, source identity, proxy mapping, FPS/frame math, and audio synchronization |
| Human approval authenticity | NOT_IMPLEMENTED | Trusted approval capture plus current revision/digest comparison |
| Antigravity media execution | NOT_IMPLEMENTED / NOT_RUN | Verify actual video/audio support and enforce bounded transmission/cost/tool permissions |
| Deterministic FCPXML export | NOT_IMPLEMENTED | Testable conversion code with explicit format/capability target |
| Actual Resolve Free import | NOT_RUN | Verify relinking, exact cuts, audio, and duration in the target application |
| Profile/state execution | NOT_IMPLEMENTED | Profile resolver, hashes, stale-stage detection, and resumable run state |
| Fully locked deployment | NOT_IMPLEMENTED | Capture tested dependency resolution for the target environment |

The test suite intentionally includes cases that are schema-valid but invalid at
the domain level. That documents the boundary; it does not indicate that domain
checks have been implemented or that the bad examples are safe to export.

## Verification approach

Run `python -m pytest -q` for meta-schema/ref checks, all stage examples, negative
cases, conditional behavior, CLI failures, offline resolution, and source/artifact
ignore rules. The negative cases use synthetic fixtures only. No user videos,
credentials, API calls, actual approval records, or remote Git operations are used.

For a separately stored machine report:

```bash
mkdir -p artifacts/validation
python -m pytest -q --junitxml=artifacts/validation/junit.xml
```

The latest executed results and environment metadata are supplied in the generated
verification artifact, not inserted into the reusable source tree as runtime logs.

## Recommended next implementation boundary

Implement the small deterministic M1 path: verified manifest + deliberate manual
frame plan -> application integrity checks -> genuine review/hash binding -> tested
FCPXML -> actual Resolve import. Only after that path works should the media-analysis
runner be integrated. Do not treat this contract-hardening revision as completion
of those later milestones.
