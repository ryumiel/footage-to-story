---
name: review-edit-plan
description: Review evidence, timing risks, and narrative coherence; bind a genuine human approval to exact plan bytes.
---

# Review Edit Plan

Owner: ChatGPT for review; the user for authentic approval. Read `AGENTS.md`,
`docs/validation.md`, and `schemas/2.0.0/review.schema.json` from repository root.

## Review dimensions

Check story coherence, source/evidence references, complete dialogue/event context,
repetitive coverage, explicit gaps, fact-versus-quotation handling, and unsupported
features. Verify timing and job identity from actual inputs, not schema success alone.

The schema CLI checks individual document shape. Separate document/media/edit
helpers exist within their documented scope. Missing cross-file/media
verification, an unavailable exporter, or missing genuine human approval must be
reported as execution blockers, not hidden behind a passing schema result.

## Review record

- Record the exact job and plan revision.
- Compute `edit_plan_sha256` locally over the exact saved UTF-8 file bytes. Do not
  ask a model to calculate a hash. Any byte change invalidates it.
- Set the true reviewer type, identifier/name, and actual timestamp. Do not invent
  human identity, approval time, consent, or a successful review.
- Use CHANGES_REQUIRED for concrete pending changes; include those changes.
- Use BLOCKED with an ERROR issue for missing evidence/implementation/approval.
- APPROVED is only a record of actual human approval, with no ERROR issues or
  outstanding changes. An AI cannot self-approve by writing `reviewer_type: HUMAN`.

The schema enforces record consistency, not authenticity or digest equality.
`scripts/verify_approval.py` supports live trusted-conversation approval and
optional independently verified signatures, both bound to exact plan job/revision/hash
(`docs/approval-verification.md`). A trusted caller may record HUMAN/APPROVED
only after observing the user's actual approval of the concrete displayed plan.
Never fabricate a user approval or sign with the user's key. Registered signing
principals and external key enrollment apply only to the optional SSH path.
A general conversation-host adapter remains pending. The bounded exporter
(`docs/fcpxml-export.md`) rechecks approval at execution; XML validation alone
does not establish Resolve acceptance.

```bash
python scripts/validate_json.py schemas/2.0.0/review.schema.json work/JOB/review.json
```

Return the review and distinguish schema results from checks actually performed.
Store it with the private job, not as reusable source or a real-data test fixture.

Trusted callers can now pass observed explicit human conversation approval,
bound to the exact plan job/revision/hash, without SSH setup. See
`docs/approval-verification.md`. The caller owns authenticity; a saved HUMAN label
or receipt alone is not execution authority. Optional signed verification remains.
