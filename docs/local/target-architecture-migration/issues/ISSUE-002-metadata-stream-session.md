## Parent

[Target purpose, users, and optimization goals](../../../users-and-optimization-goals.md)

## ID

`ISSUE-002`

## Type

`AFK`

## Status

`draft`

## What to build

Evolve the existing inner GStreamer client into the one concrete adapter and make
metadata-only reception its first complete path. It owns a private GLib context/control
path, constructs only the RTSP and Axis metadata branch, uses the assembler approved in
ISSUE-001, and invokes the application callback directly on the relevant GStreamer
delivery thread.

The replacement session remains internal until the atomic public cutover in ISSUE-007.
The parallel raw-socket path and semantic XML parser are deleted once their tests have
moved to this path. The old public retriever family remains intact until ISSUE-007 so the
installed interface and CLI are not left half-migrated between slices.

## Acceptance criteria

- [ ] Metadata-only configuration creates no video, decoder, pixel-conversion, or NumPy path.
- [ ] Readiness means the requested metadata stream is negotiated, linked, and in the playing pipeline, not that the camera has already emitted an XML document; unrelated video/audio pads do not satisfy readiness. Startup timeout fails and cleans up without waiting for a document.
- [ ] Temporary startup blocking probes provide backpressure until state/event publication and are then removed, proving `SessionReady` always precedes the first metadata callback without adding a startup data queue or drop.
- [ ] The ISSUE-001 lifecycle contract is implemented with a private GLib context/control path and deterministic cross-thread stop scheduling.
- [ ] A complete `SceneMetadata` value is delivered exactly once. Its `.xml` field is one strictly decoded UTF-8 string, and the value carries RTP timestamp, SSRC, payload type, sequence range, stream identity, and byte count without duplicate retained payload bytes.
- [ ] Recoverable assembly drops follow the ISSUE-001 state machine, increment `metadata_drops`, and optionally trace safe packet facts; they do not invoke `on_error`, fail the session, or semantically validate XML.
- [ ] The callback runs directly on the GStreamer delivery thread and the package performs no queueing or worker handoff between appsink and callback.
- [ ] Metadata uses the RTSP source's configured latency/jitter handling without adding a redundant second jitterbuffer; its appsink has the same one-sample, no-drop, no-last-sample backpressure contract as video.
- [ ] Dynamic discovery binds the first compatible unbound RTP application pad and ignores/traces later application and unrelated pads without inspecting the URL. Public identity is only `(session_id, SCENE_METADATA)`; backend stream/pad identifiers cannot leak through values, logs, or failures.
- [ ] Startup failure, explicit stop, end-of-stream, and callback failure drive the pipeline to `NULL` and release bus watches, timers, pads, assembly state, and buffers.
- [ ] Completed discovery without metadata maps to `MissingStreamError`; incompatible metadata caps/linking maps to `NegotiationError`; an inconclusive readiness deadline maps to `StartupTimeoutError`.
- [ ] Requested-stream timeout begins at `STARTING`, ends at `SessionReady`, and reports a credential-safe structured `StartupTimeoutError` without retaining/chaining a raw adapter exception or reconnecting.
- [ ] The controlled local RTSP stream verifies delivery, callback thread identity, quiet-metadata readiness, timeout, and cleanup end to end.
- [ ] The raw-socket RTSP client, semantic scene parser, and their superseded tests are deleted in this slice; no second RTSP or semantic XML path remains.
- [ ] The new session is still internal; the existing retriever family/package-root exports remain the sole public streaming model until their atomic replacement in ISSUE-007.

## Blocked by

- [ISSUE-001](ISSUE-001-target-contract-and-primitives.md)
