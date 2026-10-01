# Migration from Repository v2

This is a source/contract migration guide, not an automatic data converter.
The original v2 archive and private job data should be retained unchanged.

## Preserved design

The canonical `.agents/skills/` directory remains committed directly. There is no
install/copy step. ChatGPT remains the editor, Antigravity/Gemini remains the media
analyzer, and Resolve Free remains the target. Existing YAML profile values and
story patterns are preserved. No new custom validation framework is introduced.

## Contract changes

| v2 source contract | 2.0.0 contract / action |
|---|---|
| `manifest_version`, `request_version`, `analysis_version`, `selects_version`, `story_version`, `edit_plan_version`, `review_version` | Replace with exact `schema_version: "2.0.0"` only after the entire payload is migrated |
| No job identity required | Require the correct `job_id`; do not mix shoots |
| Unknown properties generally accepted | Every concrete object is closed; review extra fields rather than deleting them silently |
| Repeated inline type definitions | Shared common `$defs`, versioned `$id`, explicit offline registry |
| Optional/partial FPS and absent frame count | Explicit positive or null FPS pair and frame count; preserve unknowns, do not manufacture measurements |
| Unbounded/implicit analysis source scope | Explicit ranges, request ID, runner/provider, and authorization reference when uploads are enabled |
| Optional observation evidence | Require evidence and type-appropriate content descriptions |
| Arbitrary numeric select scores | Use a documented [0,1] scale; never rescale old scores without confirming their meaning |
| Free-form selected role | Supported role vocabulary; uncertain roles remain REVIEW/REJECT |
| Narrative chapter without evidence | Select IDs or an explicit coverage gap |
| Underspecified edit audio | SOURCE/MUTE sequential cuts only; unsupported separate audio must block, not disappear |
| Revision-only review | Exact stored-plan SHA-256, reviewer type/name/time, and status consistency |

## Safe job migration

1. Copy a private job into a new private working directory. Keep original bytes.
2. Inspect extra fields and recover any information that would otherwise be lost.
   Keep raw provider responses outside the canonical normalized document.
3. Establish the real job/source identities and source-time mappings.
4. Supply genuinely measured metadata; use null where the contract permits unknowns.
5. Create a bounded request and normalized observation records from real evidence.
6. Rebuild selections/plans where old meanings are ambiguous; preserve human intent.
7. Run the schema validator for each document. Domain/media checks are still required.
8. Compute the new plan digest after serialization, then obtain fresh human approval
   through a trusted mechanism. Do not carry an old approval into changed bytes.

If evidence, authority, or timing is missing, stop the affected stage. Do not fill
required fields with guesses solely to pass validation.

## Source paths

Schema files move from `schemas/*.schema.json` to `schemas/2.0.0/*.schema.json`.
Update callers explicitly. Shared skills and docs already reference the new paths.
The CLI still accepts a schema file and data file; it now resolves local `$ref`
resources and reports that its result is schema-only.
