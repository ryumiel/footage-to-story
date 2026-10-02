# Historical human lock preservation

`scripts/verify_locks.py` preserves item snapshots and source-byte bindings for
selects and edit plans. It uses the strict auxiliary `locks.schema.json`; existing
stage schemas remain unchanged. Missing, changed, removed, or unattested locks
fail. A profile change does not release a lock. Source-byte changes create a
conflict, even when an item's fields remain identical. Other unlocked items may
change. Protected fields include timing, decision, reason, audio policy, and the
locked flag. Relinking an identical source is permitted; proxy timing is not.

For a 3.0.0 manifest, capture writes a 3.0.0 lock record. Each protected item
also snapshots its source's `audio_stream_index`, or `null` when no selection is
declared. Verification rejects a changed selection even when the media bytes and
item are unchanged; the caller must explicitly unlock before capturing a new
decision. A legacy 2.0.0 lock cannot attest to a source with an explicit audio
selection and fails closed. The released 2.0.0 lock schema remains unchanged.

The trusted host supplies actual observed `LockDecision` events to
`capture_locks(paths, events, previous=..., context=...)`. Item-specific LOCK and
UNLOCK events include the exact observed message and conversation context. An
unlock must refer to an existing recorded decision. This API does not manufacture
human intent from a boolean or import alleged events from a CLI. Synthetic tests
label all events as synthetic. Runtime records belong under `work/<job_id>/` or
external storage; never commit historical human decisions.

`verify_locks(paths, record_path, TrustedLockContext(record_sha256, context_reference))`
checks exact authenticated record bytes, current strict documents, every protected
item, and actual source hashes. The trusted caller attests that the digest belongs
to genuine historical human decisions. This shares the explicit application trust
assumption of conversation approval; it is not cryptographic identity verification.
Do not reconstruct the context automatically from a saved receipt. A caller must
carry the job's complete history; an omitted historical record cannot be discovered
from a new unlocked plan alone. Local job records can bind that history as an input,
but freshness does not authenticate it.

The exporter accepts optional `lock_record` and `lock_context` API arguments. It
requires them for locked selects or edits, verifies before execution, and rechecks
immediately before publication. It still requires fresh media/edit checks and
genuine approval of the exact current plan. Lock preservation never grants export
approval. Its standalone signed CLI has no historical-lock replay switch and
therefore blocks locked inputs; a trusted host uses the API for that workflow.

Record and document reads are bounded regular-file reads. Source hashes stream
actual bytes. Rechecks detect ordinary concurrent changes; there is no atomic
storage snapshot or protection against a hostile caller that fabricates events.
