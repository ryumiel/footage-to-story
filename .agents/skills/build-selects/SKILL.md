---
name: build-selects
description: Turn actual observations into evidence-linked candidate selects using the active editorial profile.
---

# Build Selects

Owner: ChatGPT. Read `AGENTS.md` and `docs/schema-catalog.md`. Current schemas:
`schemas/2.0.0/`; all paths are repository-root relative.

## Inputs

Actual `analysis.json`, manifest, selected profile and version, and any prior
locked decisions. A transcript or story bible can aid review, but `evidence_refs`
currently reference analysis segment IDs, not arbitrary external documents.

## Procedure

1. Check source/job identities, segment references, and candidate time bounds.
   Use the implemented supplied-document checks described in `docs/document-integrity.md`.
   Report declared-record consistency separately from actual media verification.
2. Apply editorial weighting without changing the observations. Keep complete spoken
   thoughts and adequate event context; avoid misleading cuts and fabricated facts.
3. Use supported roles: dialogue, broll, action, atmosphere, transition, context, unknown.
   An unknown role can only remain REVIEW or REJECT, not SELECT.
4. Record SELECT/REJECT/REVIEW, a concrete reason, nonempty evidence IDs, and explicit
   `locked`. Preserve genuine prior user locks; do not assume a lock without evidence.
5. Optional score keys identify profile criteria; values are relative numbers in [0,1].
   Do not treat them as calibrated probabilities or silently normalize old score scales.
6. Identify repetitive coverage and uncertainty. No usable candidates is a legitimate
   empty list after actual analysis, not an invitation to invent content.
7. Validate using the existing helper:

```bash
python scripts/validate_json.py schemas/2.0.0/selects.schema.json work/JOB/selects.json
```

## Output

`selects.json` with exact schema/job identity, profile name/integer version, and
traceable candidate items. Do not set narrative order or final frame boundaries here.

Resolve the active profile with `scripts/resolve_profile.py` and preserve its full
parent-chain version/byte bindings. Before reuse, call `check_selects_binding`
against current profile files. Historical locked items require the trusted caller
context in `docs/lock-preservation.md`; a saved flag alone is not a human decision.
