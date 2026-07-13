## Parent

[Target purpose, users, and optimization goals](../../../users-and-optimization-goals.md)

## ID

`ISSUE-007`

## Type

`AFK`

## Status

`draft`

## What to build

Harden the approved lifecycle and failure-isolation behavior across every mode, then
atomically expose the new session and delete the remaining legacy streaming model.
Multiple sessions run in application-owned threads with private control contexts and no
global state or package-owned data dispatch.

The cutover includes every already-exposed core behavior from the approved contract:
session information, lifecycle/error events, structured failures, cheap statistics,
retention accounting, and all `DiagnosticsConfig` fields. ISSUE-008 aligns these with
the offline capability inventory, doctor, packaging, and installation surfaces; it does
not activate placeholder fields left by this issue.

A minimal CLI migration keeps the installed entry point functional at cutover; the full
CLI redesign remains ISSUE-009. This slice removes the retriever/process/queue/mixin
architecture only after the new path passes the complete reliability matrix.

## Acceptance criteria

- [ ] Startup, ready/running, stopping, stopped, and failed states enforce the ISSUE-001 transitions for every delivery mode.
- [ ] Stop during startup is covered as clean `StartCancelledError` cancellation into `STOPPED`, not as a terminal `StreamFailure`; readiness, stop, callback failure, and adapter failure use one first-accepted-action rule so exactly one terminal outcome wins. Errors after accepted stop are counted/sanitized where applicable but cannot upgrade `STOPPED` to `FAILED`.
- [ ] Wait/stop timeouts are finite nonnegative caller timeouts: expiry leaves running cleanup intact, creates no terminal failure, and permits a later wait. State/info/failure/statistics properties obey their documented pre-start, ready, stopping, and terminal semantics.
- [ ] The first raising data-callback invocation accepted as terminal reports its original exception once, prevents later data-callback entry, and schedules cleanup safely outside the streaming callback without deadlock.
- [ ] Raising event/error observers are sanitized and disabled without changing stream state or failure; terminal failure cleanup and notification ordering exactly follow the public contract.
- [ ] Connection loss, timeout, EOS, negotiation failure, stop-during-startup, and repeated stop each release all adapter-owned resources and report one stable credential-safe structured failure without retry/reconnect, a retained raw cause, or a chained third-party exception.
- [ ] Two or more sessions run concurrently; failing/stopping one leaves the others delivering, and no process-global GLib context, multiprocessing start method, mutable registry, or dispatcher couples them.
- [ ] Concurrent first starts safely share only idempotent GI/GStreamer initialization and the dependency plugin registry; package code stores no session/application state there, and every control context/watch/timer/pipeline/counter remains session-owned.
- [ ] Library-owned appsink/timing/control state is bounded; application-retained buffers remain application policy while outstanding retention counts are observable later.
- [ ] Teardown follows the documented callback-inhibition/watch-signal/map-sample/NULL/pad-element/state/context-thread order. It never waits for or force-closes application-retained buffers, and those handles remain valid after session shutdown.
- [ ] Every reachable endpoint/log/error path in the replacement core is tested with raw and percent-encoded credentials, including exception chaining, and leaks none.
- [ ] Package-root exports, tests, and the minimally migrated CLI change to the new session in one commit so no released state exposes two streaming interfaces or a broken entry point.
- [ ] `SessionInfo`, lifecycle/error events, structured failures, cheap statistics, retention counts, and enabled callback-time/pipeline-trace/allocation diagnostics all work at public cutover; no accepted `StreamConfig` field is ignored, deferred, or implemented as a placeholder.
- [ ] At cutover the library already uses only namespaced standard loggers and installs/configures no handler, file, queue listener, formatter, directory, or global level. Legacy logging/dependency helpers no longer activate handlers, workarounds, or eager GI checks; ISSUE-008 supplies their read-only capability replacement.
- [ ] `rtsp_data_retrievers.py`, all retriever subclasses, subprocess/queue dispatch and `mp.set_start_method`, the old mixin client shape, duplicate GStreamer runner, `video_processing_fn`/`shared_config`, queue logging, dictionary payloads, broad superseded utility surface, and superseded tests are deleted rather than wrapped. The raw-socket RTSP client was already removed by ISSUE-002 and must not reappear.
- [ ] Repository-wide searches and clean import/controlled-stream smoke tests prove no legacy public name, compatibility alias, or duplicate connection/lifecycle implementation remains.
- [ ] Clean-environment imports of the package root and every public module perform no GI/GStreamer/NumPy import, initialization, host probing, logging setup, environment mutation, or filesystem/network work; selected mode startup owns lazy dependency activation.

## Blocked by

- [ISSUE-006](ISSUE-006-combined-delivery.md)
