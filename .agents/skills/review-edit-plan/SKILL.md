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
`scripts/verify_approval.py` checks external-trust signatures and exact plan
job/revision/digest bindings (`docs/approval-verification.md`). Human approval
capture and deployment of human-controlled signing authority remain pending.
For that verifier, `reviewed_by` must be the registered signing principal.
Never create a real HUMAN approval or signature on the user's behalf.

```bash
python scripts/validate_json.py schemas/2.0.0/review.schema.json work/JOB/review.json
```

Return the review and distinguish schema results from checks actually performed.
Store it with the private job, not as reusable source or a real-data test fixture.
