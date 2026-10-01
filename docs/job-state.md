# Local job state

`record_run(state_dir, job_id, stage, inputs, outputs, status='PASS')` records
supplied local artifacts. `inspect_job(state_dir, job_id)` reports FRESH, STALE,
MISSING, FAIL, NOT_RUN, NOT_IMPLEMENTED, or INTERRUPTED and the earliest stage needing attention.
The `resume` CLI operation is the same inspection; it never runs an editorial
stage, uploads media, calls a provider, or authorizes export.

Use an ignored directory such as `work/<job_id>/state/`. Job IDs are restricted identifiers.
Input and output maps use canonical schema stems for structured artifacts
(`manifest`, `analysis-request`, `analysis`, `resolved-profile`, `transcript`,
`selects`, `story-plan`, `edit-plan`, `review`, `subtitle-map`, `locks`). Other names
bind raw evidence, source profile YAML files, and generated sidecars by file hash.
All profile-chain files must be explicitly supplied whenever a resolved profile
is included. A profile snapshot alone cannot hide changed parent bytes.

PASS requires a canonical stage output (export accepts supplied generated files),
strict schema validity, matching jobs, and the existing cross-document integrity
checks. Supply the manifest and the complete upstream canonical document context
needed by those checks. Conventional parent runs and explicitly supplied stage
inputs must be fresh. An input belonging to a recorded stage must match that
stage's recorded output. The manifest's actual source files are hashed even if
manifest bytes are unchanged. Missing or unsupported files fail recording.

Each complete run records immutable inputs, outputs, source hashes, dependency
record hashes, and current script/schema hashes. A new run replaces only the
small latest index; older records remain available. A nonblocking local `flock`
refuses concurrent writers. Records are flushed before atomic index replacement;
an interrupted publication can leave an unindexed record, never a fresh stage.
Inspection rejects corrupted index/record files and rechecks file bytes and
recursive dependency freshness. Changed profile files invalidate profile and
select descendants while compatible analysis remains reusable. Changed plans
invalidate review, subtitle mapping, and export.

```bash
python scripts/job_state.py inspect work/synthetic-demo/state synthetic-demo
python scripts/job_state.py record work/synthetic-demo/state synthetic-demo --stage manifest \
  --output manifest=work/synthetic-demo/manifest.json
python scripts/job_state.py resume work/synthetic-demo/state synthetic-demo
```

Recorded PASS means supplied evidence is consistent; saved records are local
mutable files, not an authentication system. Review/lock labels and approval
receipts never become genuine human authorization through recording. Export
still needs fresh media checks and observed exact-plan approval. This helper does
not decode media, establish provider authenticity, perform missing analysis, or
fill coverage gaps. Schema/tool changes conservatively invalidate recorded work.
