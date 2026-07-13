## Parent

[Target purpose, users, and optimization goals](../../../users-and-optimization-goals.md)

## ID

`ISSUE-006`

## Type

`AFK`

## Status

`draft`

## What to build

Complete the internal session's use-case matrix by allowing Axis scene metadata and
any encoded/native/NumPy video mode in one fixed pipeline while keeping their delivery independent. Both
callbacks carry enough RTP/Axis timing and stream identity for a later caller-owned
synchronizer, but the core does not parse ONVIF timestamps, match values, or wait for one
stream before delivering the other.

## Acceptance criteria

- [ ] Encoded+metadata, native-decoded+metadata, and NumPy-decoded+metadata each use one RTSP session/pipeline with two independent direct callbacks.
- [ ] Metadata-only and all video-only configurations keep their specialized low-work paths; enabling one stream does not initialize transformations used only by another.
- [ ] Core metadata retains XML plus RTP/stream identity only; it does not semantically parse ONVIF `UtcTime` or add synchronization storage.
- [ ] Video timing is associated by unit/frame identity rather than a mutable latest-timestamp slot and survives the reset/discontinuity cases approved in ISSUE-001.
- [ ] A slow callback can stall only its relevant GStreamer delivery path as documented; the library does not hide buffering, dispatch work, or a cross-stream queue.
- [ ] If one requested stream is missing or fails negotiation, startup fails transactionally and releases the already linked branch.
- [ ] The controlled RTSP fixture emits deterministic video timing/identity and metadata RTP identity so their preservation is asserted independently without matching them in core.
- [ ] End-to-end tests cover every metadata-only, video-only, and combined mode plus missing-stream and branch-failure cleanup.
- [ ] Audio and unrelated pads are ignored without satisfying readiness or affecting requested paths.

## Blocked by

- [ISSUE-002](ISSUE-002-metadata-stream-session.md)
- [ISSUE-003](ISSUE-003-encoded-video-delivery.md)
- [ISSUE-004](ISSUE-004-native-decoded-video.md)
- [ISSUE-005](ISSUE-005-numpy-video-delivery.md)
