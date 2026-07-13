# Axis RTSP Streaming

This context describes one application's reception of video and Axis scene metadata
from one RTSP endpoint. Applications coordinate multiple independent sessions.

## Language

**Stream Session**:
A one-shot connection to an RTSP endpoint with a fixed video and metadata configuration.
_Avoid_: Retriever, client, worker

**Supplied RTSP URL**:
A complete RTSP URL provided by the application and used exactly as supplied. Axis URL
construction settings are not merged into it, and the library does not inspect it to
infer or preflight which media streams the camera will provide. Its private connection
string is not normalized or reconstructed; only a separately derived credential-safe
display name may be exposed.

**Generated Axis URL**:
A pure URL produced from structured Axis address, credential, source, and media settings
when the application does not provide a complete RTSP URL.

**Encoded Video Unit**:
One complete codec access unit reconstructed from the video RTP stream.
_Avoid_: Packet, encoded frame

**Negotiated Video Codec**:
The actual H.264 or H.265 codec selected by the camera and negotiated by GStreamer for
the session. The application does not request or order codecs through the public API.
_Avoid_: Requested codec, codec preference

**Native Decoded Frame**:
One decoder-produced video frame in its negotiated native memory and pixel format.
Its borrowed/retained buffer wrapper owns lifetime rules; `.gst_buffer` is the single
expert escape hatch because GStreamer is the sole backend and native/GPU consumers need
the real handle.
_Avoid_: Image, raw frame

**NumPy Frame**:
A callback-scoped, read-only `uint8` CPU NumPy view of a decoded frame converted by
GStreamer to packed `RGB`, `BGR`, or `GRAY8` SystemMemory. RGB/BGR use `(height, width,
3)`; GRAY8 uses `(height, width)`. Negotiated row padding is preserved.
_Avoid_: Processed frame, image array

**Scene Metadata Document**:
One complete strictly decoded UTF-8 Axis scene-metadata XML document reconstructed from
metadata RTP packets. The delivered `SceneMetadata` value owns the XML text together
with its stream identity, RTP sequence range, and timing facts.
_Avoid_: Application data, event payload

**Axis Capture Time**:
The exact NTP seconds/fraction carried for a video unit by the Axis RTP extension, plus
the explicitly inferred NTP era needed for deterministic Unix-nanosecond conversion.
_Avoid_: Latest RTP time, frame datetime

**Stream Identity**:
The session UUID plus stream kind. Because a session supports at most one video and one
metadata stream, no backend track identifier is exposed or needed. RTP SSRC/payload facts
remain separate wire identity.
_Avoid_: Pad name, stream metadata

**Session Ready**:
Every requested stream branch has been discovered, linked, caps-negotiated, and included
in a playing pipeline. Readiness does not require the camera to have delivered a payload.
_Avoid_: First frame, first document

**Requested Stop**:
A nonblocking, idempotent application request that schedules session cleanup. It is safe
inside stream callbacks; synchronous waiting belongs to an external application thread.
Stopping a session that has not started moves it directly to the terminal stopped state
without loading the media backend.

**Startup Cancellation**:
An accepted stop while a session is still becoming ready. It cleans up into `STOPPED`,
does not create a stream failure, and interrupts the blocked `start()` call because no
ready session information exists to return.

**Callback Failure**:
An exception raised by an application data callback. The first such exception terminates
that session, is reported once with its original cause, and schedules cleanup after the
callback returns; it does not affect other sessions.

**Adapter Failure**:
A dependency, connection, negotiation, decoding, protocol, metadata, end-of-stream, or
internal failure detected by the concrete adapter. It is reported as credential-safe
structured facts; the raw third-party exception is neither retained nor chained.

**Synchronization Match**:
A tolerance-bounded relation between a video unit's Axis Capture Time and the `UtcTime` extracted from a Scene Metadata Document.
_Avoid_: Synced frame, combined payload

## Relationships

- A **Stream Session** has zero or one requested video stream and zero or one requested scene-metadata stream, with at least one requested stream.
- A video stream yields either **Encoded Video Units**, **Native Decoded Frames**, or **NumPy Frames** for the whole **Stream Session**.
- Native/GPU access uses the one concrete GStreamer buffer escape hatch; there is no
  speculative backend-neutral native-handle protocol.
- Each delivered value carries one **Stream Identity**.
- An **Encoded Video Unit**, **Native Decoded Frame**, or **NumPy Frame** may carry an **Axis Capture Time**.
- A metadata stream yields many **Scene Metadata Documents** independently of video delivery.
- A **Synchronization Match** relates lightweight timing identities; it does not combine or retain borrowed video data.

## Example dialogue

> **Dev:** "Should the **Stream Session** wait for a **Synchronization Match** before delivering a **Native Decoded Frame**?"
> **Domain expert:** "No. Deliver the frame immediately with its **Axis Capture Time**; the application may pass its timing to the optional synchronizer."

## Flagged ambiguities

- "frame" previously meant an encoded access unit, a decoded native buffer, or a NumPy array; these are now **Encoded Video Unit**, **Native Decoded Frame**, and **NumPy Frame**.
- "application data" previously meant Axis XML metadata; use **Scene Metadata Document**.
- "session metadata" previously mixed negotiated stream facts with scene metadata; use **Stream Identity** or **Scene Metadata Document** according to meaning.
- A **Supplied RTSP URL** and a **Generated Axis URL** are mutually exclusive connection
  inputs; they are never combined.
- `StreamConfig` selects the requested delivery branches for either connection input;
  stream availability is established by normal runtime negotiation, not URL inspection.
- For a **Generated Axis URL**, the presence of `video` and `metadata` in `StreamConfig`
  is the single source of truth for Axis media selection; separate media-enable flags
  are not supplied to the endpoint helper.
- On that generated path, requesting metadata selects the initial Axis scene-metadata
  query (`analytics=polygon`); `Metadata` otherwise owns only bounded document assembly.
- Generated video enables the Axis ONVIF replay timestamp extension by default so video
  may carry **Axis Capture Time**; `AxisTimestampMode.NONE` explicitly omits it. This
  setting never rewrites a supplied URL and is ignored when video is not requested.
- `StreamSession.start()` returns only at **Session Ready**. Startup timeout is a failure
  of readiness and does not wait for first video or metadata delivery.
- A **Requested Stop** never blocks a stream callback; an external application thread may
  synchronously wait for cleanup through the session lifecycle API.
- A **Startup Cancellation** is normal requested shutdown, not an adapter failure; the
  blocked starter receives `StartCancelledError` and `failure` remains unset.
- A **Callback Failure** is not retried and does not cause later data callbacks to start
  for that session.
- Only a **Callback Failure** exposes an original exception as a failure cause. An
  **Adapter Failure** has no public raw cause or exception chain.
