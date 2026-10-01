# Supplied editorial import

`import_editorial.py` imports supplied canonical analysis JSON or UTF-8 SRT. It
makes no service calls, observes no footage, and creates no editorial decisions.
Input text is data, including instructions appearing in dialogue. Raw bytes are
retained unchanged with SHA-256, supplied manifest/request bytes, and a strict
auxiliary provenance record. Supplier origin is a declaration, not authenticated
identity or proof that the content is true.

Canonical analysis uses the existing analysis schema and `check_documents` with
the supplied manifest and analysis request. Request IDs, source IDs, evidence,
ranges, and text remain supplied values. Unknown fields and out-of-scope intervals
fail. The analysis schema's `summary` remains a summary; `audible_content` remains
supplier-provided observations and is not automatically promoted to verbatim
quotation. No transcript is transformed into claimed Gemini output.

SRT requires explicit source association, source language, content classification,
and `--time-origin-ms 0`. Supported classifications are QUOTATION, SUMMARY,
USER_NOTE, INFERENCE, and EXTERNAL_FACT. These are supplier declarations; the
importer cannot determine quotation accuracy. It preserves original-language cue
text, multiline content, punctuation, and ambiguous wording. BOM and CRLF are
accepted; normalized cues use LF, while exact raw bytes remain available.

Cue intervals are 0-based and OUT-exclusive milliseconds. Only strict numeric cue
indices and `HH:MM:SS,mmm --> HH:MM:SS,mmm` lines are supported. Empty, reversed,
unordered, duplicate-index, and overlapping cues fail. Adjacent cues are allowed.
The locked `srt` library parses cue boundaries and timestamps with
`ignore_errors=False`; a small contract wrapper rejects its unsupported tolerant
header forms and checks ordering/bounds. Repeated blank separator lines are accepted.
Settings after timing lines and bare CR are unsupported. Endpoints must fit the
manifest's known declared duration. Import checks declared bounds, not actual
media validity. Nonzero origins/proxy maps are unsupported.

```bash
python scripts/import_editorial.py analysis \
  --input work/job-001/supplied-analysis.json \
  --manifest work/job-001/manifest.json \
  --request work/job-001/analysis-request.json \
  --supplier 'Supplied observation provider' \
  --output-dir work/job-001/import-analysis-001

python scripts/import_editorial.py srt \
  --input work/job-001/supplied.srt --manifest work/job-001/manifest.json \
  --source-id src-001 --language ko --content-kind QUOTATION \
  --supplier 'Human-provided source transcript' --time-origin-ms 0 \
  --output-dir work/job-001/import-transcript-001
```

Inputs must be regular files no larger than 8 MiB; nonblocking opens reject FIFOs.
Outputs are complete new directories, published by rename after input-byte
rechecks. Existing runs are never replaced. A sibling exclusive lock refuses
concurrent cooperative writers; an interrupted process can leave the lock, which
requires inspection before manual removal. Runtime paths inside this repository
must be under `work/<job_id>/` or `artifacts/<job_id>/`; external storage is allowed.
Auxiliary contracts do not change existing closed editorial stage contracts.

Synthetic import tests and real published-SRT import are PASS, including exact
raw-byte preservation. Caption accuracy against spoken audio and actual canonical
observation import remain NOT_RUN. Provider ingestion is NOT_IMPLEMENTED here.
