# Validation Strategy

## 1. Use existing standards and libraries

The canonical contracts are JSON Schema Draft 2020-12 files. `jsonschema` owns
keyword evaluation, type checking, required properties, conditionals, patterns,
bounds, and error reporting. `referencing.Registry` owns reference resolution.
No custom schema engine, custom keywords, model judge, or duplicate validation
framework is introduced.

`scripts/validate_json.py` is a CLI integration layer: read JSON, load trusted
schemas, construct the standard validator, sort library errors, and set exit codes.
Python's standard JSON decoder rejects duplicate keys and non-JSON constants
through its supported hooks. This is input hygiene, not schema reimplementation.

## 2. Offline registry and explicit dialect

Every contract declares `$schema` and a versioned absolute `$id`. Shared `$defs`
are referenced by absolute URI, so file location is not inferred from a network
request. The registry is populated from the local schema directory. No retrieval
callback is configured; an unknown `$ref` fails rather than fetching a remote file.

Each schema is checked with `Draft202012Validator.check_schema`. The chosen schema
must exactly match a registered local schema. Duplicate IDs are configuration
errors. The shared definition library cannot be selected as a standalone stage
validator. Tests resolve every committed `$ref`, including definitions not reached
by a particular example; a valid meta-schema alone would not prove that a reference
exists.

This is offline resolution, not a security sandbox. Schema files are trusted source;
untrusted model responses are data, never schemas or executable programs.

## 3. Closed objects and controlled extensibility

Every concrete root and nested object uses `additionalProperties: false`.
The shared rational-rate and millisecond-range objects are closed too. This catches
misspelled and unsupported fields instead of silently accepting them.

We reuse primitive/object definitions with `$ref` and add conditional constraints
with `allOf`; we do not extend an already closed object with new properties in a
separate branch. Therefore `unevaluatedProperties` is not needed in these schemas.
If future composition spreads properties across branches, revisit that choice at
the composition boundary rather than mechanically adding both keywords everywhere.

`scores` is the only dynamic-key map: lower-snake-case editorial criterion names,
maximum 64 characters, with numeric values from 0 through 1. There is no permissive
`metadata` or `extensions` escape hatch. Raw provider payloads remain private job
artifacts; adding normative fields requires an explicit contract revision.

## 4. Formats and unknown values

`FormatChecker` is explicitly enabled and the `date-time` checker must be present.
Dependencies use `jsonschema[format-nongpl]`; missing format support fails early.
A `format` annotation alone is not assumed to enforce anything.

Required but unmeasured manifest values use `null` where permitted. FPS numerator
and denominator must either both be positive integers or both be null; declaring
CFR requires a known positive pair. Zero is not a substitute for unknown.

IDs must be nonempty tokens; human text must contain non-whitespace characters.
Integer time/frame values are nonnegative or positive as appropriate, within
2^53-1 for exact interchange. Standard JSON Schema number semantics apply; we do
not override the library's interpretation of mathematically integral numbers.

## 5. Conditional rules implemented in schemas

- An upload-enabled request needs a nonblank authorization reference. A disabled
  request may omit that field or contain null, but not an apparent grant.
- Visual observations require visible content; audio/dialogue require audible
  content; mixed observations require both; technical observations require notes.
- A selected item cannot have an unknown role. A deferred/rejected item can.
- An empty story chapter needs an explicit coverage gap.
- APPROVED requires a HUMAN record, no ERROR issues, and no outstanding changes.
- CHANGES_REQUIRED requires at least one change; BLOCKED requires an ERROR issue.

These validate record structure, not truth or consent. An LLM can still write a
false statement that has a valid shape. Authorization and approval must be bound
to a trusted human event by future execution code.

## 6. Document integrity and media gates remain separate from schemas

The following checks cannot be replaced by passing a single-document schema:

| Invariant | Required evidence |
|---|---|
| End follows start | Comparison of sibling values |
| IDs are unique by selected key | Object-key identity across arrays |
| Source and select references exist | Manifest / analysis / selects / story documents |
| All inputs belong to the same job | Every participating `job_id` |
| Ranges remain inside approved scope and source bounds | Request + manifest + media evidence |
| Frame rate/count and proxy mappings are valid | Real media metadata and timing map |
| Timeline is sequential and audio stays synchronized | Calculated frame/time relationships |
| Locked decisions survive a replan | Previous and current artifacts |
| Approval matches this plan | Authentic human record + revision + SHA-256 |

The inventory helper rejects duplicate source IDs/file identities and checks for
ordinary source changes during probing/hashing (`docs/media-manifest.md`).
`scripts/check_integrity.py` now separately checks supplied job identity, unique
IDs, source/evidence/select references, range ordering, declared source bounds and
request scope, full select evidence coverage, and review revision/issue links.
Unknown declared bounds block range checks needing them. See
`docs/document-integrity.md` for dependencies, policies, and exact coverage.

The table describes the evidence required for complete execution, not the proof
provided by the record helpers. A separate bounded source/video scanner now checks
current hashes, decoded counts, and exact video PTS/CFR (`docs/media-verification.md`).
`scripts/verify_edit.py` now reruns that scan and checks zero-origin CFR edit bounds,
exact select-window containment, matching FPS, and sequential video timeline math
and zero-origin PCM sample cuts (`docs/edit-verification.md`). Compressed-audio
conversion, nonzero-origin/proxy maps, prior locks,
and authentic approval/hash verification remain unimplemented.

Keep these as small application invariants as M1 develops; do not build
another schema engine. Runtime failures should be explicit errors, not Python
`assert` statements that can be disabled. Assertions in test code are appropriate.

Boundary tests deliberately show examples that pass a schema but fail one of these
invariants. They document the schema validator's limit; separate tests now cover
the implemented document checker. Each CLI prints its own limitations on success.

## 7. Approval digest convention

`edit_plan_sha256` is the lowercase SHA-256 of the **exact bytes** of the stored
UTF-8 edit-plan file, including whitespace and the final newline. It excludes the
review, which is stored separately. There is no invented JSON canonicalizer.
Any byte change invalidates approval, including formatting-only changes.

Compute the hash locally with Python's `hashlib`, not with a language model:

```bash
python -c "from pathlib import Path; import hashlib; print(hashlib.sha256(Path('work/JOB/edit_plan.json').read_bytes()).hexdigest())"
```

The schema checks only digest shape. The future export gate must compare actual
bytes, revision, job identity, human authorization, and all prior gates.

## 8. Separate export gates

Schema-valid JSON is not necessarily a valid edit; a valid edit is not necessarily
valid FCPXML; structurally valid XML does not prove Resolve can import it correctly.
Keep contract validation, domain/media checks, approval authenticity, XML validation,
and actual Resolve import as separately reported results.

See `docs/references.md` for the standard and library documentation used here.
