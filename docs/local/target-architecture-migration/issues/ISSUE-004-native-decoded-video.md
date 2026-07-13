## Parent

[Target purpose, users, and optimization goals](../../../users-and-optimization-goals.md)

## ID

`ISSUE-004`

## Type

`AFK`

## Status

`draft`

## What to build

Add video-only native decoded delivery to the same internal session. GStreamer selects
the decoder through normal negotiation. The callback receives the negotiated native
decoded sample/buffer and timing/identity without mandatory pixel mapping, conversion,
CPU materialization, or a second client.

Reuse the ownership interface from ISSUE-003 for callback-scoped borrowing, native
retention, and explicit copying. The library reports the selected decoder/path but does
not choose CPU/GPU/vendor policy for the application.

## Acceptance criteria

- [ ] Decoder selection uses GStreamer's normal negotiation and the approved codec matrix; no hard-coded `avdec_h264` or library-owned decoder preference framework remains.
- [ ] Normal GStreamer rank/negotiation may select either hardware or software decoding; the library neither forces nor hides a fallback and reports the concrete selected factory and processing path in `SessionInfo`.
- [ ] Native mode adds no CPU pixel converter/caps filter unless required by the approved native contract and does not map pixels merely to deliver the value.
- [ ] Each decoded value exposes negotiated memory/caps, dimensions, PTS/DTS/duration, correlated Axis/RTP timing, and stream identity.
- [ ] Native format strides/offsets come only from available `GstVideoMeta` and remain empty for opaque layouts; memory features and selected decoder/processing factory names are canonical, credential-safe facts rather than guessed layouts, pointers, element instance names, or plugin paths.
- [ ] Borrowed native values are callback-scoped, retained native buffers survive callback return without content copying, and explicit copies have documented storage/cost.
- [ ] Decoder delay, drop/reordering, discontinuity, flush, and restart tests prove timing identity resets or recovers without shifting later frames.
- [ ] Callback failure and shutdown release decoder, sample, timing, and retained-reference state deterministically.
- [ ] No decoder candidate for the negotiated codec produces credential-safe `DependencyError`; candidates that exist but cannot negotiate the selected caps/memory produce `NegotiationError`. Both fully roll back without exposing/chaining raw exceptions or applying library-owned fallback policy.
- [ ] Controlled-stream tests cover native delivery, retain/copy lifetime, callback thread identity, and pipeline element selection.

## Blocked by

- [ISSUE-003](ISSUE-003-encoded-video-delivery.md)
