# Native AAC Resolve control

On 2026-10-04, DaVinci Resolve 21 imported a deterministic FCPXML control
referencing unchanged H.264/AAC-LC MP4 media. This is a synthetic application
check, not a real-job export or editorial approval.

The source has zero-origin 48 kHz stereo AAC with 1024 encoder priming samples.
At 25 FPS, three 10-frame clips use SOURCE, MUTE, SOURCE policies. Source ranges
are [5,15), [25,35), [30,40); the timeline is 30 frames, or 1.2 seconds.
The native audio-only QuickTime render uses 24-bit PCM at 48 kHz, stereo bus,
without normalization, proxies or source conversion.

| Check | Result |
| --- | --- |
| Native import and render | PASS |
| Rendered length | PASS: exactly 57600 stereo sample frames |
| Left tone center | PASS: 0.005538421 s, expected 0.005 s |
| Right tone center | PASS: 0.805513445 s, expected 0.805 s |
| Center tolerance | Both within 3 ms; maximum error 0.539 ms |
| Middle MUTE interval [19200,38400) | PASS: exact zero samples |
| Source byte preservation | PASS |
| Audible listening | NOT_RUN |
| Real-source synchronization, mono and fractional-FPS native render | NOT_RUN |
| General nonzero-origin/proxy mapping and compressed conversion | NOT_IMPLEMENTED |

Generated evidence and the native render live under ignored
`artifacts/synthetic-aac-native-003/`. Source SHA-256 is
`21b62f4e8a047463d95a7f1926851017ae20917b567227c86e68a7141446884a`.
The first import attempts lacked sandbox folder access. Explicit source import
and access to this fixture folder resolved that blocker. Earlier fixture attempts
are retained; they do not establish a video codec failure.

These observations establish bounded decoder-delay handling, channel assignment,
source offsets and SOURCE/MUTE behavior. They do not prove bit-identical decoding,
arbitrary AAC compatibility, real dialogue boundaries or human listening quality.
