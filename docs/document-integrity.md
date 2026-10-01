# Document Integrity Checks

`scripts/check_integrity.py` checks relationships among supplied 2.0.0 documents.
It first validates each input using the committed schemas and the existing
offline `jsonschema`/`referencing` integration. It then compares record values
with ordinary application code, separately from schema keyword validation.
Inputs are never repaired or rewritten. Media paths are not opened.

```bash
source .venv/bin/activate
python scripts/check_integrity.py \
  --manifest examples/contracts/manifest.json \
  --analysis-request examples/contracts/analysis-request.json \
  --analysis examples/contracts/analysis.json \
  --selects examples/contracts/selects.json \
  --story-plan examples/contracts/story-plan.json \
  --edit-plan examples/contracts/edit-plan.json \
  --review examples/contracts/review.json
```

The example is deliberately synthetic. For real jobs, supply explicitly
authorized records under `work/<job_id>/` or external storage. The checker is
read-only and writes no report file; redirect machine reports only to ignored
`artifacts/` or external storage.

## Supplied documents and dependencies

The manifest is always required. Other flags are optional so the checker can run
at intermediate stages. Success covers only supplied branches, not a complete
job. Dependencies cannot be omitted for a supplied branch:

| Supplied document | Required upstream input |
|---|---|
| Analysis request | Manifest |
| Analysis | Analysis request and manifest |
| Selects | Analysis, analysis request, and manifest |
| Story plan | Selects and their upstream inputs |
| Edit plan with a non-null `select_ref` | Selects and their upstream inputs |
| Manual edit plan without select references | Manifest only |
| Review | Edit plan and its required upstream inputs |

An edit plan need not have a story plan: manual non-AI edits are supported.
A review is optional and is checked only for record relationships; supplying an
APPROVED record does not authenticate approval or permit execution.

## Implemented comparisons

- Every supplied document's `job_id` must match the manifest.
- Source, requested-source, segment, select, chapter, and edit IDs must be unique
  within their own collections. Identifier namespaces remain separate.
- Every source reference must exist in the manifest. Analysis `request_id` must
  match the supplied request.
- Millisecond and source-frame ranges must have OUT strictly greater than IN.
  They are 0-based and OUT-exclusive. OUT may equal the declared source bound.
- Request, observation, and select millisecond ranges must fit declared manifest
  `duration_ms`. Edit source frames must fit declared `frame_count`. An unknown
  bound blocks a check that needs it; inventory alone can retain unknowns.
- Observations and selects must be fully covered by the declared request's ranges
  for the same source. Adjacent/overlapping ranges can jointly cover an interval;
  gaps cannot be bridged by treating their outer bounds as a single range.
- Every select evidence reference must name an analysis segment from the same
  source. The union of referenced segment intervals must cover the whole select
  interval, including REVIEW and REJECT candidates. This is a conservative
  application policy for normalized evidence, not a schema keyword or proof of
  factual truth. A candidate needing unobserved handles must be reanalyzed or
  retained outside an integrity-valid normalized select record.
- Story select IDs and non-null edit select references must exist and have decision
  SELECT. An edit and its referenced select must name the same source.
- Review plan revision must match the edit plan; non-null review issue `edit_id`
  references must exist in that plan.

All input schemas are validated before any comparison runs. Schema violations
stop the domain pass. Missing required documents also stop it. Otherwise multiple
issues are returned without altering the records or inventing missing evidence.

## Results

Exit codes:

- **0:** `DOCUMENT_INTEGRITY_VALID` for supplied documents and declared bounds.
- **1:** Schema, missing-dependency, or relationship violation. Diagnostics name
  the document, JSON Pointer, issue code, and specific failure.
- **2:** Input reading/parsing or schema configuration failure.

Duplicate JSON keys and non-JSON numeric constants fail through the same strict
parser used by `scripts/validate_json.py`. Unknown fields fail schema validation.
The schema-only validator and its exit codes retain their previous meaning.

## Separate media and execution gates

A passing result does not verify media existence/content hashes, decoded source
bounds, actual FPS/CFR, proxy maps, timeline continuity, audio synchronization,
or the frame-to-millisecond relationship between an edit and its referenced select.
It does not establish factual accuracy, authenticate request permissions, compare
review SHA-256 to stored plan bytes, authenticate human approval, check prior locked
decisions, resolve profiles, or authorize export. These limitations are printed
on every successful CLI invocation. `scripts/verify_media.py` now separately checks
current source hashes and supported decoded video counts/PTS/CFR; see
`docs/media-verification.md`. Its scan does not complete the remaining timeline,
audio, proxy, approval, or export gates.

In particular, a forged approval with a correctly shaped digest or a mismatched
but correctly shaped digest can pass this record checker. Authentic approval
binding and hash verification remain a later execution gate. Reported manifest
duration/frame counts are inventory claims, not verified decoded media bounds.

## Testing

`tests/test_integrity.py` uses only synthetic documents. It covers valid full and
manual branches, immutability, duplicate IDs, job/request mismatches, missing
dependencies/references, declared bounds, half-open scope unions, evidence gaps,
story/edit/review links, schema-first behavior, strict parser/CLI failures, and
explicit tests that pending gates remain unverified.
