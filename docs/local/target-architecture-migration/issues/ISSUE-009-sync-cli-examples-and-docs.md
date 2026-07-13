## Parent

[Target purpose, users, and optimization goals](../../../users-and-optimization-goals.md)

## ID

`ISSUE-009`

## Type

`AFK`

## Status

`draft`

## What to build

Add one narrow optional synchronization module, then rebuild the CLI, examples, README,
and repository skill references as thin consumers of the final public interface and
capability inventory. The synchronizer extracts only ONVIF `UtcTime` and matches it to
delivered video timing under an explicit bounded policy; it is not part of core delivery.

The CLI implements the approved two-command `stream`/`doctor` contract, inspects all
stream modes through safe summaries/JSON Lines, demonstrates synchronization, and
performs display handoff only when requested. Examples look like real applications and
contain no second GStreamer framework.

## Acceptance criteria

- [ ] The synchronizer stores immutable timing plus an application-owned token, is thread-safe for concurrent video/metadata callbacks, and never keeps a borrowed frame/view after callback return.
- [ ] Matching is online, one-to-one, consuming, and thread-safe with inclusive tolerance and deterministic absolute-delta/timestamp/insertion tie-breaking. Timestamp extraction preserves the first ONVIF `Frame@UtcTime` rule. Exact, within-tolerance, signed delta, flush/outside-tolerance, missing/malformed/non-UTC/multiple-frame timestamp, out-of-order, capacity, expiry, reset, and deterministic-clock cases return every token exactly once through typed results.
- [ ] When synchronization is unused, core/session behavior, imports, ordering, and allocation shape are unchanged.
- [ ] The installed root exposes exactly `stream` and `doctor`; root invocation shows help and performs no implicit streaming. `stream` covers every delivery mode and combined synchronization through the documented flags, while `doctor` uses the ISSUE-008 capability interface.
- [ ] Every streaming command/example supports bounded duration or item count and a supplied controlled endpoint so headless CI cannot hang or require a camera.
- [ ] Headless CLI import and execution work without NumPy/OpenCV; display behavior is tested through an injected/fake display path, with real GUI smoke explicit and manual.
- [ ] Before asynchronous display handoff, the callback retains or copies borrowed data; replacement/drop/display/shutdown paths release retained items and tests assert retention/pool counts return to zero.
- [ ] Display uses the documented single-slot latest-frame policy with retained BGR NumPy backing; replacement, mapping, GUI failure, signal, and normal shutdown close every item deterministically.
- [ ] Examples import only package public modules and contain no direct `gi` imports, pipeline construction, duplicate RTSP client, private-module access, or duplicate URL helper. At least one generated-endpoint example uses the official `axis_endpoint()` and one supplied-endpoint example proves literal URL handling.
- [ ] CLI endpoint options are mutually exclusive: `--url` passes the supplied value unchanged and rejects generated-device options, while omission of `--url` requires the documented generated address/settings. Neither path silently ignores conflicting options.
- [ ] Mode/pixel-format/synchronization/display constraints, defaults, bounded duration/count first-wins behavior, human versus versioned JSON Lines output, write failure, SIGINT/SIGTERM cleanup, and exit codes exactly match the CLI contract.
- [ ] Generated passwords come only from environment or hidden prompt, not a command-line option; supplied URL environment use is documented as safer than placing credential-bearing URLs in shell history/process arguments.
- [ ] CLI and Python API both default to 100 ms RTSP latency and document the same units/meaning; CLI tests prevent the old 100/200 ms surface divergence from returning.
- [ ] The standalone sync pipeline, three-retriever CLI dispatch, and superseded CLI/example plumbing are deleted.
- [ ] README, repository skill references, and install docs cover modes, fixed configuration, callback threads, borrow/retain/copy, failures, concurrent sessions, synchronization, capabilities, and no automatic reconnection.
- [ ] Sentinel username/password/token and raw/percent-encoded userinfo are absent from stdout/stderr, caplog, exceptions, doctor output, copied commands, and docs examples.
- [ ] README security guidance warns that user-enabled verbose `GST_DEBUG` is dependency-owned process output and may reveal the exact supplied location; normal CLI/library output remains sanitized without intercepting global GStreamer logging.
- [ ] Link/snippet checks and controlled-stream subprocess tests exercise help, errors, all headless commands, and every executable example.

## Blocked by

- [ISSUE-008](ISSUE-008-observability-capabilities-and-packaging.md)
