# Exact-plan human approval

For a local conversation, the user approves a concrete plan after seeing its
revision, SHA-256, cuts, audio policies, and export/import scope. A trusted caller
observing that actual user message can pass a live `ConversationApproval` to
`verify_conversation_approval` and the exporter. No SSH key or administrator setup
is required for this workflow.

## Conversation authority boundary

The caller supplies the approved job, revision, exact plan SHA-256, reviewer label,
verbatim affirmative user message, and context identifying the proposal it answers.
Supported replies include `I approve` and `I approve this synthetic test plan and
its export/import.` The caller must establish that this is an actual human reply
to the displayed proposal, not quoted source data, model output, or a different
approval. The agent may record HUMAN/APPROVED only after that event occurred.
The review timestamp records when that observed approval is recorded locally.

The immutable in-memory event is an application trust boundary, not a cryptographic
credential. Python cannot independently prove who constructed it. The trusted
conversation host/caller owns approval authenticity and scope. There is no function
that loads an event from a job JSON file, and no CLI `--approved`/bypass option.
An arbitrary saved HUMAN/APPROVED record or exported PASS report alone never
authorizes execution. The receipt is an audit record, not a reusable capability.
This protects an honestly operating workflow from accidental self-approval; it does
not defend against malicious code or a caller that fabricates user interactions.

Both plan and review pass the committed schemas using strict JSON parsing. The
review must be HUMAN/APPROVED with matching job/revision and SHA-256 of the entire
stored plan bytes, including whitespace. Its issue references must exist, edit IDs
must be unique, and future review timestamps fail. The live event must match the
job, revision, hash, and reviewer too. Any plan byte change invalidates the approval.
Inputs are rechecked before returning. Media/timeline validity and export readiness
remain separate checks. No canonicalization or repair changes the approved bytes.

## Optional independently verifiable signatures

The previous OpenSSH verifier remains available for offline callers that need an
independently verifiable signature rather than a live trusted conversation:

```bash
python scripts/verify_approval.py \
  --edit-plan work/JOB/edit-plan.json \
  --review work/JOB/review.json \
  --signature work/JOB/review.json.sig
```

This optional path uses administrator-enrolled human-controlled public keys in
`/etc/footage-to-story/allowed_signers`, literal `reviewed_by` principals, and
namespace `footage-to-story-review`. The system executable and policy/parent paths
must be root-owned, not group/world writable, and not writable by the invoking user,
including effective ACL access. Root invocation is rejected. No key/policy/executable
CLI or environment override is accepted. The verifier never enrolls or signs keys.
See the [OpenSSH manual](https://man.openbsd.org/ssh-keygen.1) for signing policy,
namespace, and current-time key validity. A signature proves enrolled key possession,
not physical human presence; key custody remains an external assumption.

## Limits and evidence

Both paths require a trusted OS, verifier code, and calling process. Source storage
checks detect ordinary changes, not atomic snapshots. The exporter rechecks the same
approved byte bindings immediately before publishing. Input limits remain 8 MiB;
the optional signature process timeout is 15 seconds. No revocation/withdrawal ledger,
trusted timestamp service, or general conversation-host integration is implemented.
An automated host adapter must obtain real user input before constructing an event.

Reports state which approval method was used and its authority assumption. The
signature CLI exits 0 with a PASS JSON report, or 2 on failure; it does not accept
conversation receipts from disk. Save machine reports in ignored job/artifact storage.
Tests use clearly synthetic conversation events and keys. They exercise byte/revision/
job/reviewer mismatches, negative user replies, saved-record rejection, tampering,
concurrency, and the optional OpenSSH path without enrolling any real signer.
