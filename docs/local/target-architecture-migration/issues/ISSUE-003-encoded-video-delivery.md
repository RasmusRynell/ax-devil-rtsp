## Parent

[Target purpose, users, and optimization goals](../../../users-and-optimization-goals.md)

## ID

`ISSUE-003`

## Type

`AFK`

## Status

`draft`

## What to build

Extend the same internal session with video-only encoded delivery. GStreamer handles
RTSP, depayloading, parsing, and reconstruction of complete encoded units from the
negotiated H.264/H.265 codec/caps matrix, selecting the depayloader/parser from RTP
caps, then invokes a direct callback with no decoding, pixel
conversion, NumPy materialization, or mandatory content copy.

Implement the native-buffer ownership interface approved in ISSUE-001 so callers can
borrow for the callback, explicitly retain the native buffer, or copy into independent
storage.

## Acceptance criteria

- [ ] Encoded mode constructs no decoder, raw-video converter/caps filter, NumPy mapping, or Python pixel-processing path.
- [ ] Each callback receives one complete encoded unit with codec/caps, PTS, DTS, duration, RTP/Axis timing when available, and stable stream identity.
- [ ] Every codec/caps combination approved in ISSUE-001 has an end-to-end controlled-stream test; an unsupported negotiated codec/caps path fails transactionally with `NegotiationError`, while a missing required depay/parser plugin produces `DependencyError`.
- [ ] The controlled fixture and supported CI exercise both H.264 and H.265. Parser output caps are exactly Annex-B `byte-stream`/`au`; parameter sets are present at random-access points, `key_frame` follows negotiated buffer flags, and no decoder/converter is present.
- [ ] Dynamic discovery binds the first compatible unbound H.264/H.265 video pad in source order and ignores/traces later video and unrelated pads; no URL or codec preflight chooses it. Public identity is only `(session_id, VIDEO)`, and backend stream/pad identifiers cannot leak.
- [ ] Borrowed encoded data is valid only for the callback scope and access afterward fails detectably.
- [ ] `retain()` preserves the native GStreamer sample/buffer without copying contents, and explicit release makes ownership/accounting clear.
- [ ] `copy()` returns independent storage that remains valid after callback return and session shutdown.
- [ ] Callback success/failure, retention, copying, flush, and early shutdown release adapter-owned native references exactly once.
- [ ] Appsink/backpressure settings and adapter timing-correlation state are explicit and bounded; there is no stream-data dispatch queue.
- [ ] Appsink inspection proves direct signal delivery, at most one queued sample, no retained last sample, and no silent dropping; callback delay produces upstream backpressure and application-owned queues implement any later drop policy.
- [ ] Pipeline inspection proves decode/conversion elements are absent and the callback runs on the delivery thread.
- [ ] The startup gate proves `SessionReady` precedes the first encoded callback without queueing or dropping source data.

## Blocked by

- [ISSUE-002](ISSUE-002-metadata-stream-session.md)
