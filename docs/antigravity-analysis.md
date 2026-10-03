# Bounded Antigravity visual and speech analysis

The M3 adapter supports separate visual, speech, and combined visual/dialogue observations through
Antigravity CLI `agy` with an
explicit Gemini model. It returns canonical analysis, not selects, a story,
a timeline, approved quotations, or final frame cuts. General sound descriptions
are excluded after synthetic tone and silence controls produced invented sounds.
Human listening, speaker identity, and precise visual/speech-boundary accuracy
remain NOT_RUN by user decision.

## Local staging

`stage_analysis_media.py` validates the actual manifest/request, scans decoded
source clocks, and extracts only explicitly requested ranges. Supported sources
are self-contained zero-origin CFR MOV/MP4 with one usable mono/stereo audio
stream and known byte hashes. Source audio may be compressed. Requests must use
speech/dialogue categories; `audible_dialogue` is also accepted. Explicit
`mode="audiovisual"` requires exactly `visual` plus one of those speech categories.
The default `mode="speech"` continues to create audio-only clips.

Both range endpoints must map exactly to integer source video frames and decoded
audio samples. Unknown clocks, internal audio gaps/resets, proxies, variable-rate
video, overlapping ranges, and mismatched hashes fail. The adapter does not round
unsupported boundaries. This deliberately bounded mapping does not implement the
general nonzero-origin/source-proxy or compressed-audio final-export gate.

```bash
python scripts/stage_analysis_media.py \
  --manifest work/JOB/manifest.json \
  --request work/JOB/analysis-request.json \
  --output-dir work/JOB/staged-analysis-001 \
  --max-total-seconds 60
```

Staging is local and does not authorize transmission. MP3 or combined MP4 clips and `mapping.json`
are published into a new directory. Verification checks exact decoded sample
counts and waveform correlation greater than 0.98 at zero offset against the
original selected samples. Temporary decoded float samples are removed; original
media stays unchanged. Source global/stream metadata and chapters are stripped
from uploaded clips; provenance stays in local records. An exclusive cooperative writer lock refuses concurrent
staging. This is analysis-extraction verification, not exact lossy-audio identity
or proof of quotation correctness.

Audiovisual staging retains all selected source frames and rational FPS. A 3.0.0
manifest binds an explicit absolute audio-stream index for multi-track sources;
extraction and sample verification use that selected stream. Legacy 2.0.0 manifests
continue to require unambiguous audio. Staging accepts 8-bit yuv420p and 10-bit
yuv420p10le; the latter requires explicit BT.709 color tags and is converted to
8-bit yuv420p in the analysis copy. Original bit depth and selected audio index
are recorded locally. This conversion is not a color-managed final master.

Audiovisual staging bounds
content to 640×360 for landscape, 360×640 for portrait, or 360×360 for square
footage, without upscaling. Aspect ratio is preserved subject to even-pixel rounding
for yuv420p. Black padding rounds both output dimensions upward to multiples of 16;
chroma-aligned offsets center the content within two pixels. Standard 16:9 content
is 640×360 inside a 640×368 output, with four pixels above and below. The local
mapping records content dimensions and each padding edge. It encodes transformed
frames as lossy H.264 at CRF18 with the medium preset and keeps compressed MP3
speech in the same MP4. Fresh zero-origin CFR checks preserve exact frame count
and rational FPS. Compression-tolerant per-frame checks compare the staged video
with the same source transform; the mapping records their method, thresholds,
and observed metrics. Per-frame SSIM minima are 0.95 for luma/combined and 0.90
for each chroma plane; mean combined SSIM must reach 0.97. Comparisons stop at the
shorter input without repeating its last frame, and must cover the requested
frame count. Similar-looking substitutions can still pass these similarity
thresholds. These establish bounded visual correspondence, not pixel
identity or proof of every fine detail. Audio sample count/correlation and shared zero origin
verify extraction synchronization. This analysis crop is not a general proxy or
export mapping; source resolution detail can be lost through resizing.

Use `--mode audiovisual` for local staging or the explicit Python API keyword for
provider execution. Only the combined clip is uploaded, not a separate audio copy.

## Upload authority and confinement

The Python `run_analysis` API in `scripts/analyze_with_agy.py` receives an observed
upload authorization from a trusted caller. The request must explicitly permit
cloud upload and contain its real authorization reference. The caller supplies
`observed: true`, that reference, and SHA-256 hashes of the exact manifest and
request bytes after observing the relevant user permission. These are caller
assertions at a trust boundary; a saved record, request label, or CLI flag alone
cannot grant authority. There is no live-run CLI or general conversation-host
adapter that reconstructs consent from stored labels.

The runner stages before uploading, pins a Gemini model, and creates a private
isolated temporary workspace for each attempt. It installs a workspace
`.agents/hooks.json` PreToolUse gate from `scripts/agy_guard.py`. The gate permits
exactly one native `view_file` of that attempt's exact hash-bound MP3 or MP4, followed by
one output-only `finish` with a strict schema-valid response. The audit binds the
completion payload hash to the final output. It denies all
other tools and paths, including commands, writes, browsers, MCP tools, and
subagents. Malformed hook inputs and audit failures return explicit deny JSON.
The runner never uses a permission-bypass flag or Gemini CLI.

The tested `agy` 1.2.14 hook transport adds optional `toolAction` and `toolSummary`
strings to `finish` arguments, while its structured output omits them. These
declared transport annotations are bounded separately; every remaining argument
must satisfy the strict provider schema. Successful completion is linked to its
tool event by the provider's step index. Other unknown fields are rejected.

Streamed tool parameters are display previews: `agy` can replace portions of long
strings with an ellipsis. The adapter checks the read/completion event sequence
and binds the guard's full-input hash directly to the final structured output.
It never expands an ellipsis or imports preview text. A changed final output,
missing audit, extra tool invocation, or invalid response still fails. Available
final usage is recorded before output acceptance, including failed process exits;
missing or inconsistent final usage remains unknown.

A zero-token `/hooks` metadata preflight must show the exact enabled guard as the
sole enabled hook, avoiding undocumented precedence with other hook configurations.
Guard, config, selected response schema, clip, request, manifest, and source hashes are rechecked. A completed
run also requires matching tool events and guard audit evidence. Denied or
unaudited activity fails the run; a model-reported PASS or process exit 0 is not
sufficient. This gate confines agent tools; it is not an OS sandbox, authentication
of Google's internal transport, or isolation from a malicious trusted local caller.

## Limits, retries, and privacy

Limits bound clip duration/bytes, total dispatched calls, cumulative uploaded
seconds attached through native media reads including retries, response bytes,
and wall-clock time. Internal provider retransmissions are not observable. The default retry
count is zero; at most one configured retry is allowed, and failed attempts are
retained. Unknown final usage, timeouts, invalid contracts, or failed guards cannot
be retried as a successful empty analysis. POSIX process groups are terminated on
limits. Live token usage stops the process at a configured observed threshold;
aggregate usage is checked before further dispatch.

Unknown final usage stops the affected attempt without retry and stops batch
dispatch by default. An explicitly authorized exploratory caller may instead
record the failed attempt as a gap and continue other untouched requests when
the user chooses to rely on a calling-side subscription cap. The caller must
retain unknown final usage and observed lower bounds; the aggregate final token
total remains unknown. Observed thresholds, call budgets, consent bindings,
tool confinement, and output rejection still apply. A user's subscription-cap
statement records their selected constraint; this adapter does not verify the
subscription's billing terms or implement that cap.

The CLI does not expose a documented hard monetary or pre-inference token cap.
Observed token limits can be reached after a model invocation has already accrued
usage, and killing the client does not prove cancellation of provider billing.
Call and duration budgets therefore limit dispatch; they are not a promised dollar
ceiling. A hard monetary ceiling remains NOT_IMPLEMENTED by this provider path.
No credentials or global settings are copied. Real inputs and response/audit logs
remain private ignored job data; raw responses can contain source dialogue.
The CLI also maintains its own local conversation logs outside the job directory;
provider-managed local and cloud retention is not controlled by this adapter.

Reanalysis requires another exact request and trusted-caller authorization, fresh
checks, and a new output directory. Runs never replace earlier observations or
widen ranges automatically. Local job resume does not grant upload authority.

## Response handling and verification boundaries

`agy-response.schema.json` is a strict auxiliary provider contract for local-clip
speech observations. `agy-av-response.schema.json` adds separate typed `visual`
and `dialogue` segments and requires both tracks to be accessible. Visual entries
require visible content and null audible content; dialogue entries require the
inverse. Mixed segments, arbitrary associations, and unknown fields are rejected.
Related observations share source-relative time windows and evidence; overlap does
not prove speaker identity or lip synchronization. It does not change canonical stage schemas. Existing
`jsonschema` and `referencing` validate it offline. Unknown fields, duplicate JSON
keys, non-finite values, invalid source-relative ranges, foreign/duplicate segment
IDs, and unavailable audio fail. No evidence, dialogue, confidence, source identity,
or permission is invented to repair a response.

Normalization preserves supplied observation fields and adds each verified clip's
source origin to candidate local milliseconds. Source/job/request IDs come from
the bound actual inputs. The canonical analysis is checked against those inputs
and imported with the existing provenance importer. Complete attempt envelopes,
request/manifest bytes, source and clip hashes, tool audits, usage, mapping, and
normalization evidence remain in the new runtime directory, including failures.
Canonical schema conformance cannot detect semantically invented speech or prove
that supplied evidence describes the media truthfully.
Provider evidence strings can retain local clip timestamps; the normalization
record supplies their source origin. Do not interpret those prose timestamps as
verified source frame cuts.

Manual acceptance already exercised real permitted speech ranges, published
caption comparison, and canonical import. It retained spelling/wording differences
and cut-off dialogue. Synthetic coarse video ingestion demonstrated sampled frame
observations, not precise motion or frame-boundary accuracy. General visual
observations are available through the explicit audiovisual mode. Human listening, quotation accuracy, and
provider speech-boundary accuracy remain NOT_RUN. The adapter has no export authority.

Speech-only reusable-adapter acceptance passed with `agy` 1.2.14 and
`gemini-3.8-flash-high`: two explicitly authorized compressed speech clips totaling
12 seconds produced four canonical observations. Local source-offset checks,
loaded-hook inspection, read/completion audit binding, usage accounting, and
provenance import passed. The run used two calls and no retries. Failed earlier
transport attempts were preserved. The full repository suite passed 679 tests;
independent source and security reviews passed. Real dialogue and run records
remain in ignored job storage.

Combined-input acceptance passed in the same target runtime: one four-second
generated clip with independent visual and speech content yielded two visual
observations and one dialogue observation. A separate generator oracle confirmed
the controlled shapes, colors, direction, spoken phrase, and coarse visual ranges.
One native MP4 read and completion, schema/media hashes, source offsets, canonical
import, and original-source preservation passed. The run used one call, no retries,
and 59,208 observed tokens. The response retained sampling and sub-second timing
uncertainty; this does not establish accuracy on arbitrary footage, speaker identity,
or precise speech/visual boundaries. The full suite passed 705 tests and independent
source/security reviews passed. Runtime evidence remains ignored job data.

Official provider contracts: [CLI hooks](https://antigravity.google/docs/hooks/),
[headless mode](https://antigravity.google/docs/cli/headless/), and
[media prompting](https://antigravity.google/docs/cli/prompting/).

### Local staging resources

The runner accepts `staging_timeout` separately from its provider `timeout`. Use a
bounded longer staging timeout for slow original decoding, such as 300 seconds
per local subprocess for the Ceretto smoke test. Default staging timeout is 60
seconds. The encoded clip and media guard share the unchanged 20 MiB limit;
lossy encoding reduces size but does not guarantee that every clip fits.

## Separate visual and speech passes

The explicit `mode="visual"` accepts exactly the `visual` request category and
uses the strict auxiliary `agy-visual-response.schema.json`. It returns only
visual observations; audio-availability fields and dialogue entries fail.
`mode="speech"` remains a separate MP3 dialogue pass. Canonical request and
analysis schemas are unchanged. Combined `mode="audiovisual"` still requires
both modalities to be accessible and does not silently degrade to visual-only.

Visual staging uses the same synchronized MP4, including compressed primary
audio for extraction verification. Upload permission must therefore cover that
MP4's actual bytes, even though the provider is asked for visuals only. Each pass
needs its own exact request/manifest consent binding, call budget, guarded media
read and immutable provenance. Two passes on one source range are two calls and
two attached-duration charges to dispatch budgets; shared time windows do not
establish speaker identity or verified dialogue boundaries.

### Long-source scan controls

Local source scanning uses four decoder threads and the existing full decoded
frame/audio clock checks. `stage_media(..., source_scan_timeout=3600)` and CLI
`--source-scan-timeout 3600` can explicitly bound a longer source decode without
extending other staging subprocess deadlines. The provider runner forwards this
optional limit independently of `staging_timeout` and provider `timeout`; absent
it, source scanning uses the staging timeout as before. Invalid, non-finite or
non-positive limits fail. The existing 64 MiB scan-output and 20 MiB clip ceilings
remain unchanged. A longer deadline is not a long-source acceptance result.

In the strict path, whole-source scans and trim-based staging can still repeat
decoding across requests. Efficient reuse of decoded-source proof remains
unimplemented. The metadata-only fast path below avoids those scans for
exploratory analysis; no saved scan or resume record authorizes an upload.

## Fast exploratory analysis copies

An explicitly selected fast path prepares one reusable resized MP4 per recording
and checks reported metadata rather than decoding every original frame. Use
`python -m scripts.analysis_cache --manifest work/JOB/manifest.json --source-id ID
--cache-root work/JOB/analysis-cache --decoder videotoolbox` on a compatible macOS
FFmpeg installation, or omit the decoder option for software decoding. Hardware
support must work in the actual conversion; tool failures are preserved rather
than accepted. Preparation is local and does not upload anything.

`run_analysis(..., analysis_cache_dir=Path('work/JOB/analysis-cache'),
analysis_decoder='videotoolbox', preparation_timeout=3600)` explicitly selects
this path. The existing strict `stage_media` path remains the default for API
compatibility. For local clips, call `scripts.analysis_cache.stage_cached`.
Copies retain 360p content in padded dimensions, selected audio only, H.264 CRF18
and compressed AAC audio. Sources and stage contracts are unchanged.

The closed auxiliary `analysis-cache.schema.json` records exact source/manifest
and copy byte bindings, source file signatures and selected audio stream.
Preparation checks original bytes once. Reuse checks the original file signature
and cached-copy bytes; changes fail rather than silently reusing stale media. New source/manifest bytes select a different cache key.
Clip preparation uses timestamp seeking in the small copy, not repeated full
original decodes. It checks reported zero origins, FPS, durations within 100 ms,
audio rate/channels, dimensions, successful conversion and the 20 MiB clip ceiling.
Original reported FPS must agree with the manifest and r_frame_rate; explicitly
known VFR sources are rejected. Matching reported rates do not establish decoded
CFR. Source header duration/audio must match the manifest.

Results are labeled `ANALYSIS_METADATA_ONLY`; exact frame/audio correspondence
remains `NOT_RUN` and final export mapping remains `NOT_IMPLEMENTED`. No SSIM,
waveform-correlation or full-source frame scan runs in this path. Candidate
millisecond offsets refer to the nominal original clock, but are approximate;
resizing, timestamp repair, encoding and seeking may lose details or introduce
small shifts. AAC followed by MP3 for speech is another lossy generation.
This is an analysis copy, not a verified general proxy or final-edit source.
Use the originals and existing fresh edit/export gates for exact approved cuts.

Upload consent, exact request binding, provider native-read/finish confinement,
modalities, clip/call/time/observed-token limits and provenance remain required.
During a fast batch, source signatures are checked between attempts and before
publication; unchanged originals are not repeatedly hashed. Cached-copy and
uploaded-clip byte hashes remain checked. This relies on local file identity,
size, mtime and ctime for routine original freshness, not a new decoded proof.
The cache cannot authorize uploads or establish quotation accuracy. There is
no general nonzero-origin/proxy export mapping implemented by this feature.
