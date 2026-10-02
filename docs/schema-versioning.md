# Schema Identification and Versioning

## Four different version concepts

| Field or label | Meaning |
|---|---|
| Repository v3 / tooling 0.3.0 | This delivered source revision |
| `$schema` | JSON Schema dialect: Draft 2020-12 |
| Versioned `$id` and `schema_version` | Exact per-document contract: 2.0.0 or supported 3.0.0 manifest/lock contract |
| `revision` / `edit_plan_revision` | A particular job's editorial plan revision |

A data instance does not use `$schema` to select its own validator. The caller picks
a trusted local schema. `schema_version` is then checked as an exact constant.

## Identifiers

Example logical ID:

```text
https://footage-to-story.example/schemas/2.0.0/analysis.schema.json
```

The `.example` namespace is deliberate. These are stable identifiers mapped to
local files, not promises that a schema server exists. `$ref` values point to the
same version's shared definition resource. The registry never downloads a missing
resource. If the project later adopts a published namespace, that is an explicit
identity migration, not a silent replacement behind existing IDs.

## Compatibility policy

Released schema IDs are immutable. Keep old versions available in their own
versioned directories when future versions are added. Do not edit a released
contract's meaning in place or map a new payload onto an older ID.

Use a new major contract for required-field changes, renamed fields, altered time
semantics, removed/narrowed enum values, closed-object policy changes, or any
vocabulary change that existing closed consumers cannot safely interpret.
A minor release may add an independent companion contract without changing existing
payload meaning. Patches are documentation/annotation clarifications, not hidden
validation changes. If acceptance changes, do not call it a documentation patch.

All producers and consumers explicitly agree on an exact version. Semantic version
labels do not make a closed older validator accept new fields. Adding an "optional"
field is not automatically safe for old readers. Do not rely on tolerant parsing,
field stripping, ignored errors, or a generic `additionalProperties: true` escape.

## Why 2.0.0 here

Repository v2 used several stage-specific integer fields such as `analysis_version:
1` and had no versioned `$id`. It accepted unknown properties. The revised contracts
unify version identity, close the object vocabulary, and introduce required identity,
evidence, timing, and review fields. That is an intentional breaking change.

No automatic migration tool is included. Preserve old job files, migrate copies,
and obtain genuinely missing inputs. A document must not be labeled 2.0.0 merely
because the old version field was renamed. See `migration-from-v2.md`.

## Explicit audio selection manifest 3.0.0

The independently versioned 3.0.0 manifest adds an absolute `audio_stream_index`.
Released 2.0.0 schema files remain unchanged. The inventory builder emits 3.0.0
when explicit selections are supplied; otherwise it preserves legacy 2.0.0 output.
Updated integrity/media/staging, job-state, and historical-lock readers explicitly
accept these two manifest versions. Job records bind the new manifest schema bytes
for freshness checks. Requests and editorial stage documents remain 2.0.0: version identity
is checked per document, while job/source references bind their relationships.
Older readers must reject the new manifest instead of stripping the selection.
Validate the new schema with `--schema-dir schemas` to register its 2.0.0 shared
definitions. Multiple audio tracks remain unsupported by the final exporter.

Historical lock records also have an independent 3.0.0 contract. A lock captured
against a 3.0.0 manifest stores the selected audio stream index per protected
source, including `null` for no explicit selection. Readers validate exact 2.0.0
or 3.0.0 lock schemas; a 2.0.0 record cannot protect a source with an explicit
selection. Changing a protected source's selection requires an observed unlock
before a new lock can be captured.
