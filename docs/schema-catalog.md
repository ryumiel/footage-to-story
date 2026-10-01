# Schema Catalog - Contract 2.0.0

All schemas live in `schemas/2.0.0/`. All stage documents require
`schema_version: "2.0.0"` and a nonblank token `job_id`. No instance-level `$schema`
or unknown convenience fields are accepted. Select the schema explicitly at the
validation call; do not let untrusted data choose a remote schema.

## Shared definitions

`common.schema.json` centralizes schema version, identifiers, nonblank human text,
nonnegative/positive safe integers, confidence, SHA-256, date-time, rational rate,
millisecond range, identifier lists, notes, and constrained score maps. It is a
reference resource rather than a stage document schema.

## Seven stage documents

| Contract | Required stage fields | Important constraints |
|---|---|---|
| Manifest | `sources` | At least one source; stable ID/path; explicit known or null duration/FPS/frame count; CFR/VFR/UNKNOWN status |
| Analysis request | `request_id`, `runner`, `provider`, `sources`, `questions`, `cloud_upload_allowed` | Runner is antigravity; provider is gemini; every source has explicit nonempty ranges; enabled upload needs authorization reference |
| Analysis | `request_id`, `segments` | Evidence descriptions and confidence required; conditional visible/audible/technical content; zero findings is permitted after a genuine completed analysis |
| Selects | `profile`, `profile_version`, `items` | Traceable evidence IDs; explicit decision, reason, role, and lock state; scores in [0,1] |
| Story plan | `thesis`, `chapters` | Ordered chapters with title/purpose/select IDs; empty coverage requires a recorded gap |
| Edit plan | `revision`, `timeline_name`, `edit_mode`, `timeline_fps`, `items` | Sequential cuts only; frame-based source/timeline positions; SOURCE or MUTE audio; explicit reason and lock state |
| Review | `edit_plan_revision`, `edit_plan_sha256`, `reviewer_type`, `reviewed_by`, `reviewed_at`, `status`, `issues` | Digest shape; real date-time syntax; status consistency; only a human record can represent approval |

## Field interpretation

### Manifest

`source_id` is not inferred from a basename alone. `content_sha256`, time base,
source start timecode, proxy path, and audio metadata are optional explicit fields.
The contract does not calculate them or verify file existence. A source with
unknown duration/count can be inventoried but must not be exported without evidence.

`proxy_path` identifies an optional full-length analysis proxy only. Any cropping,
concatenation, speed change, or uncertain synchronization requires a separately
verified mapping before timestamps can be used. General proxy mapping is not
implemented. M3 supports only its freshly verified zero-origin speech extracts;
see `antigravity-analysis.md`.

### Analysis request and observations

Ranges are source-relative milliseconds. There is no omitted-range shortcut that
implicitly means "upload everything." A full source must still be explicitly
bounded. `authorization_ref` points to a real user permission record outside the
source repository; its existence/authenticity is not established by this validator.

`summary` and `audible_content` are descriptions of what was heard. They are not a
canonical verified verbatim transcript. Supplied SRT transcripts and local import
provenance have separate auxiliary contracts; see `editorial-import.md`.
`evidence` strings describe the actual source basis; they must not claim a file was
watched when it was not. Segment IDs remain stable within the combined job analysis.

An empty `segments` array means an actual analysis completed with no usable
findings. It must not disguise missing media, unavailable video capability, or a
failed provider call; those cases are operationally BLOCKED and produce no invented
analysis artifact.

### Antigravity provider response

`agy-response.schema.json` is a strict auxiliary provider-format contract, not a
canonical stage document. Its candidate ranges are local to one bounded clip.
It requires audio availability, speech observations with evidence/confidence, and
warnings. Unknown fields fail. The trusted runner binds source/job/request IDs
from verified inputs and normalizes offsets before canonical analysis validation.
Schema validity is not semantic validation of words or evidence; human quotation
and candidate speech-boundary verification remain NOT_RUN.

### Selects and story

`evidence_refs` identify analysis segment IDs in the same job. The implemented
document integrity gate verifies resolution. External facts and story-bible references
must not be inserted as if they were observed footage segment IDs.

`profile_version` refers to the existing integer version in the YAML profiles.
Scores are editorial values, not objective truth or calibrated probabilities.
No numeric score should alter the underlying observations. The profile resolver
stores settings and exact-byte hashes for the full parent chain in a separate
resolved-profile contract; see `profile-resolution.md`.

`transition_notes` are intentions, not proof that an effect or B-roll exists.
A story can list missing coverage; an executable cut cannot point to missing footage.

### Edit plan and review

`select_ref` can be null or omitted for a deliberately manual M1 test plan. That
does not bypass the need to verify source identity and frame ranges. Frame duration
is calculated as `source_out_frame - source_in_frame`; it is not duplicated in a
second stored duration field.

SOURCE/MUTE is the first target capability, not a claim of implemented export.
Separate audio, overlaps, J/L-cuts, transitions, and retiming need a later contract
and tested implementation. Reject them rather than dropping them silently.

An AI review that is otherwise satisfied but lacks authentic human approval remains
BLOCKED with an explicit issue. A human approval may retain acknowledged warnings,
but not ERROR issues or required changes. Changing plan bytes invalidates the hash.
