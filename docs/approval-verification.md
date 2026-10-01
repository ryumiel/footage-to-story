# Signature-bound approval verification

`scripts/verify_approval.py` verifies a supplied review and detached OpenSSH
signature against the exact stored edit-plan bytes. It never writes a review,
signs an approval, reads private keys, enrolls a signer, or configures trust.

```bash
python scripts/verify_approval.py \
  --edit-plan work/JOB/edit-plan.json \
  --review work/JOB/review.json \
  --signature work/JOB/review.json.sig
```

## Authority boundary

The fixed trust anchor is `/etc/footage-to-story/allowed_signers`. An administrator
must independently enroll a public key controlled by a human reviewer and bind it
to a literal principal matching `reviewed_by`. Use a dedicated key, an exact
principal, and the `namespaces="footage-to-story-review"` allowed-signers option.
Keep signing keys inaccessible to the agent; a human-controlled external signing
device or process is preferable to a private key in the shared workspace.

The verifier requires root ownership and no group/world write permission for the
anchor, the system `/usr/bin/ssh-keygen`, and their parent paths. It also rejects
paths writable by the invoking user, including effective ACL access. It rejects
root invocation and checks both resolved paths and original symlink parents.
There is no CLI or environment override for policy, executable, principal,
namespace, verification time, or a job-supplied public key. Missing or unsafe
trust configuration blocks verification. The program does not install policy.

This boundary assumes a trusted OS, administrator, verifier source, and execution
process. It cannot resist an agent with administrator access, a modified Python
process, or stolen signing keys. A signature proves possession of an enrolled key,
not physical human presence or careful review. Enrollment and key custody establish
the human authority assumption. This implementation does not capture a human
approval event; authentic capture and real deployment acceptance remain pending.

## Human signing workflow

The human reviews the concrete saved plan, computes its SHA-256 locally, and writes
a truthful HUMAN/APPROVED review with the exact job/revision/hash, registered
principal, and actual approval time. The human's separate signing environment then
signs the **review file bytes**, using OpenSSH namespace `footage-to-story-review`.
Return that review and its detached `.sig` file to the job. The verifier uses
`ssh-keygen -Y verify`, supplying those exact review bytes on stdin. See the
[official OpenSSH manual](https://man.openbsd.org/ssh-keygen.1) for signing,
allowed-signers configuration, namespace constraints, and key validity options.
An agent must not perform real signing on the human's behalf.

## Checks and result limits

Both documents must pass the committed schemas with strict JSON parsing. The
review must be HUMAN/APPROVED and bind the same job, revision, and SHA-256 of the
entire plan file, including whitespace. Its issue edit references must exist;
duplicate plan edit IDs fail. `reviewed_by` must be a literal principal, not a
pattern. Future timestamps fail. The declared timestamp is signed data, not a
trusted timestamp service. OpenSSH checks signer validity at current verification
time; removing a signer from the policy invalidates subsequent checks. No separate
revocation-list or approval-withdrawal ledger is implemented.

The verifier snapshots input and trust bytes and rechecks them before returning.
It uses a private temporary copy of the policy/signature and a bounded 15-second
verification process without a shell or SSH agent. Each input is limited to 8 MiB.
These checks detect ordinary concurrent changes, not an atomic filesystem snapshot.
An eventual exporter must rerun approval and media/edit checks at execution, using
the same input bytes; a saved PASS report is not an execution credential.

Exit **0** emits a JSON PASS result on stdout with plan, review, signature, and
policy digests. Exit **2** reports an input, trust, signature, or execution error;
there is no successful result. The command does not create a failure bundle.
Save machine output only under ignored job/artifact storage. Media validity,
timeline/audio integrity, prior locks, upload consent, and export readiness are
outside this command. Approval binds the plan, not unsupplied inventory/evidence.

## Synthetic verification

Tests create explicitly synthetic keys/reviews in temporary directories and
substitute the external trust-loading boundary only inside the test process.
No test key is enrolled in `/etc`, and no synthetic PASS represents real approval.
Tests exercise real OpenSSH verification, document/signature mutations, job and
revision mismatches, untrusted keys, wrong namespaces, expired authority, unsafe
trust, future timestamps, unknown fields/references, concurrency, and timeout.
