## Parent

[Target purpose, users, and optimization goals](../../../users-and-optimization-goals.md)

Approved contract: [Complete public interface](../PUBLIC-INTERFACE.md)

## ID

`ISSUE-001`

## Type

`HITL`

## Status

`ready`

## What to build

Define and approve the concrete contract that later slices will implement, then move the
repository's proven pure stream behavior behind deep modules. This includes immutable
session configuration, credential-safe endpoint handling, typed delivery/error values,
callback-scoped borrow/retain/copy semantics, Axis metadata assembly, and bounded
video-unit timing correlation.

The HITL checkpoint approves the exact synchronous lifecycle, initial encoded codec/caps
matrix, supported CPU NumPy format matrix, and deletion map. The implementation portion
extracts the existing RTP/XML loss recovery and the useful Axis NTP/frame-association
logic into GI-independent modules with focused tests. It does not integrate them into a
temporary legacy path or introduce a generic media framework.

## Acceptance criteria

- [ ] The approved lifecycle states which method blocks, when startup is ready, how another application thread requests synchronous stop, and how callback-thread failure schedules cleanup without tearing down from the streaming callback itself.
- [ ] Startup readiness means every requested branch is discovered, linked, caps-negotiated, and in a playing pipeline; it never waits for the first payload. `startup_timeout_s` begins at `STARTING`, expires into `StartupTimeoutError`, and cleans up before `start()` raises.
- [ ] `startup_timeout_s` defaults to 15.0 consistently in Python and CLI, validates as finite and positive, and replaces legacy connection-only timeout meanings with the one full-readiness deadline.
- [ ] `request_stop()` is nonblocking, thread-safe, idempotent, and legal inside callbacks; `wait()`/`stop()` synchronously wait only from an external application thread and raise `SessionContextError` before changing state if called from any data/event/error/control callback context.
- [ ] Stopping an unstarted session transitions directly from `CREATED` to `STOPPED` without importing GI; waiting before start is a state error, while repeated stop and terminal-state cleanup are idempotent according to the public lifecycle table.
- [ ] An accepted stop during `STARTING` cleans up into `STOPPED`, leaves `failure` unset, emits stopping/stopped rather than failed, and unblocks `start()` with `StartCancelledError` because no ready `SessionInfo` can be returned.
- [ ] The first application callback exception accepted before another terminal action is terminal for that session, is reported once with its original cause, prevents new data callbacks, and schedules cleanup after callback unwinding on the control thread; other sessions remain independent. If requested stop already won, a late exception from an in-flight callback is counted and safely logged but does not replace `STOPPED`.
- [ ] Event/error observers are nonterminal: the first exception from either emits one sanitized type-only log, disables that observer, and cannot create or replace the selected lifecycle outcome. Failure notification order is cleanup, `SessionFailed`, then one `on_error` call with the same report.
- [ ] Only callback failures retain and chain an original application exception. Every adapter, dependency, camera, GStreamer, and other system failure has `StreamFailure.cause is None`, has no raw exception chain, and exposes only credential-safe structured facts.
- [ ] The approved initial encoded matrix is the negotiated H.264/H.265 outcome with Annex-B byte-stream and access-unit alignment; there is no public codec request, preference, or retry order. The small CPU pixel-format matrix is explicit, unsupported media fail clearly, and no decoder/vendor policy framework is designed.
- [ ] Closed choices use enums or equally explicit value types, configuration is immutable, and invalid combinations fail without importing GI.
- [ ] No one-value `StopReason` or equivalent placeholder is introduced: stopping/stopped events mean requested shutdown, while terminal failures have their own typed event/report.
- [ ] `Metadata()` directly selects the sole scene-metadata kind and owns only assembly limits; no zero-value `axis_scene()` factory or speculative metadata-kind hierarchy is added.
- [ ] Transport defaults to `AUTO`, preserving GStreamer's current UDP/TCP negotiation; explicit `TCP` and `UDP` force only that transport, and ready `SessionInfo` reports the actual selected transport rather than `AUTO`.
- [ ] `latency_ms` defaults to 100 in both API and CLI, validates as a nonnegative integer, and maps to the one GStreamer RTSP jitter/latency owner rather than creating another queue.
- [ ] The pure Axis URL helper is used only for Generated Axis URLs; complete user-supplied URLs preserve their original private connection string unchanged and are never normalized, reconstructed, or merged with helper/session URL settings. Parsing supplied input is limited to basic type/scheme/control-character safety and deriving a redacted display name. `StreamConfig.video` and `StreamConfig.metadata` are the single source of truth for generated media selection and select the requested delivery branches for either input; duplicate media-enable flags are not accepted. Media availability is left to normal runtime negotiation rather than URL inspection. Generated credentials/query values are encoded correctly, and secrets are absent from endpoint representations and validation errors.
- [ ] The generated initial metadata selection is fixed and explicit: `metadata is not None` renders `analytics=polygon`, while `Metadata` controls only bounded assembly limits. Supplied URLs never receive this query or any other helper setting.
- [ ] Generated Axis rendering has exact-string tests for video-only, metadata-only, combined, timestamp-disabled, resolution, source, port, credentials, hostname/IPv4/bracketed-IPv6, fixed query ordering, and encoding/redaction cases. Its initial inputs exclude frame rate, compression, codec, and arbitrary query injection.
- [ ] The generated helper emits only canonical `rtsp://` Axis URLs, validates its documented address/source/port/resolution/credential constraints, renders explicit port 554, and percent-encodes generated userinfo. Nonstandard/TLS camera URLs use the unchanged supplied-URL path.
- [ ] Generated video defaults to `AxisTimestampMode.ONVIF_REPLAY`, `NONE` omits the extension, metadata-only generation ignores video options, and neither setting inspects or rewrites a supplied URL.
- [ ] Borrowed, retained, copied, metadata, video, session-information, and error values have documented lifetime/ownership contracts before GStreamer-specific implementation begins.
- [ ] `BorrowedNativeBuffer.gst_buffer`/`RetainedNativeBuffer.gst_buffer` are the sole expert native escape hatch and obey the same scope/close guards. No public pipeline, arbitrary element access, backend protocol, generic native handle, or NumPy import is introduced.
- [ ] `StreamIdentity` contains only session UUID and stream kind because one session has at most one stream of each kind; RTP identity is separate, and no backend pad/stream identifier enters the public or credential-safe diagnostic surface.
- [ ] Metadata assembly accepts only plain RTP packet facts and implements the exact documented marker/timestamp/modulo-sequence state machine. Recoverable gaps, timestamp changes, limits, missing XML start, invalid UTF-8, and reset return typed drops, increment counters, recover at the defined boundary, and never become terminal stream failures.
- [ ] A GStreamer-adapter test separately proves full RTP packet extraction removes header extensions and padding before packet facts reach the assembler; RTP parsing is not reimplemented in Python.
- [ ] Incomplete metadata assembly has explicit byte/packet bounds plus typed reset/drop results; all 12 current focused RTP/XML cases remain covered through the correct two test surfaces.
- [ ] Frame timing uses the fixed 512-unit per-stream bound and exact RTP-timestamp then output-PTS keys. Missing timing/PTS, duplicate PTS, decoder reordering, overflow, flush, discontinuity, and stream replacement never silently shift a neighboring capture time onto a later unit.
- [ ] `AxisCaptureTime` validates exact wire ranges, infers/stores the nearest NTP era from packet-arrival realtime, and converts to Unix nanoseconds with the documented integer-floor formula; tests cover ordinary values, fractions, pre-epoch values, and the 2036 era boundary without float/datetime loss.
- [ ] Timing correlation stores only identity/timing keys and facts, not packet payloads or full stream buffers, and exposes explicit reset/overflow results for adapter counters and diagnostics.
- [ ] The contract names one concrete GStreamer adapter and no abstract backend protocol, factory, compatibility shim, or duplicate configuration path.
- [x] Human review approved the contract, supported matrices, and deletion map on 2026-07-13; this makes ISSUE-001 ready to implement but does not complete its implementation criteria.
- [ ] Public annotations and implementation remain compatible with the declared Python 3.10 minimum; the contract does not accidentally require `typing.Self` from Python 3.11.

## Blocked by

None - can start immediately.
