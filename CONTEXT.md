# Axis RTSP Streaming

This context describes one application's reception of video and Axis scene metadata
from one RTSP endpoint. Applications coordinate multiple independent sessions.

## Language

**Stream Session**:
A one-shot RTSP connection to one endpoint with a fixed video and metadata configuration.
RTSP control, RTP and RTCP share one TCP connection (interleaved); UDP is not used.
_Avoid_: Retriever, client, worker

**Receive Thread**:
The thread that reads the socket, reassembles RTP, decodes,
converts and runs every data callback, one at a time and in stream order. Nothing is
queued between receiving and delivering, so a slow callback pushes back on the camera
through TCP instead of growing memory. A separate session-owned sender keeps RTSP alive
while media reads or callbacks are blocked; it never delivers callbacks and is joined
before the connection is closed.

**Supplied RTSP URL**:
A complete RTSP URL provided by the application. Credentials in it authenticate the
session and are removed from request lines; everything else is used exactly as supplied.
Axis URL construction settings are not merged into it, and the library does not inspect
it to infer which media streams the camera will provide. Only the credential-free form
is exposed, as the session name.

**Generated Axis URL**:
A pure URL produced from structured Axis address, credential, source, and media settings
when the application does not provide a complete RTSP URL.

**Video Sample**:
One delivered video value: its data plus RTP timestamp, keyframe flag and optional
**Axis Capture Time**. The data is an **Encoded Video Unit**, a **Native Decoded Frame**
or a **NumPy Frame**, chosen by `VideoOutput` for the whole session. The receiver owns it.

**Encoded Video Unit**:
One complete Annex-B codec access unit reconstructed from the video RTP stream. The first
one starts with the SDP parameter sets.
_Avoid_: Packet, encoded frame

**Negotiated Video Codec**:
The H.264 or H.265 codec the camera announces in its SDP for the session. The application
does not request or order codecs through the public API.
_Avoid_: Requested codec, codec preference

**Native Decoded Frame**:
One `av.VideoFrame` in the decoder's native pixel format, for applications that convert
or upload frames themselves.
_Avoid_: Image, raw frame

**NumPy Frame**:
An owned `uint8` NumPy array converted by FFmpeg from a decoded frame to packed `rgb24`,
`bgr24`, `rgba`, `bgra` or `gray`. Three- and four-channel formats have shape `(height,
width, channels)`; `gray` has `(height, width)`.
_Avoid_: Processed frame, image array

**Scene Metadata Document**:
One complete strictly decoded UTF-8 Axis scene-metadata XML document reconstructed from
metadata RTP packets. The delivered `SceneMetadata` value owns the XML text together with
its RTP timestamp and optional **Axis Capture Time**. A document that lost an RTP packet
or is not valid UTF-8 is dropped, not delivered partially.
_Avoid_: Application data, event payload

**Axis Capture Time**:
The exact NTP seconds/fraction carried for a video unit by the Axis RTP header extension
(`0xABAC`), converted to Unix nanoseconds. NTP seconds below 2^31 are taken to be in NTP
era 1 (from 2036-02-07).
_Avoid_: Latest RTP time, frame datetime

**Session Ready**:
The camera answered PLAY with 200 OK after every requested track was set up. Readiness
does not require the camera to have delivered a payload.
_Avoid_: First frame, first document

**Requested Stop**:
A nonblocking, idempotent application request that ends the session by shutting down the
socket. No TEARDOWN request is sent because a socket write could block. It is safe inside stream callbacks;
synchronous waiting belongs to an external application thread.

**Startup Cancellation**:
An accepted stop while a session is still becoming ready. It does not create a stream
failure, and interrupts the blocked `start()` call with `StartCancelledError` because no
ready session exists to return.

**Callback Failure**:
An exception raised by an application data callback. The first such exception terminates
that session and is reported once with its original cause; it does not affect other
sessions.

**Adapter Failure**:
A connection, authentication, protocol, missing-stream, end-of-stream, no-data timeout or
internal failure detected by the library. It is reported as a credential-safe
`StreamError`; the raw third-party exception is neither retained nor chained. A single
undecodable access unit is skipped with a warning instead.

**Synchronization Match**:
A tolerance-bounded relation between a video unit's Axis Capture Time and the `UtcTime` extracted from a Scene Metadata Document.
_Avoid_: Synced frame, combined payload

## Relationships

- A **Stream Session** has zero or one requested video stream and zero or one requested scene-metadata stream, with at least one requested stream.
- A video stream yields either **Encoded Video Units**, **Native Decoded Frames**, or **NumPy Frames** for the whole **Stream Session**, each wrapped in a **Video Sample**.
- A **Video Sample** may carry an **Axis Capture Time**.
- A metadata stream yields many **Scene Metadata Documents** independently of video delivery.
- A **Synchronization Match** relates lightweight timing values; it does not combine or retain video data.

## Example dialogue

> **Dev:** "Should the **Stream Session** wait for a **Synchronization Match** before delivering a **Native Decoded Frame**?"
> **Domain expert:** "No. Deliver the frame immediately with its **Axis Capture Time**; the application compares it with `SceneMetadata.utc_time_ns` itself."

## Flagged ambiguities

- "frame" previously meant an encoded access unit, a decoded native buffer, or a NumPy array; these are now **Encoded Video Unit**, **Native Decoded Frame**, and **NumPy Frame**, all delivered as a **Video Sample**.
- "application data" previously meant Axis XML metadata; use **Scene Metadata Document**.
- A **Supplied RTSP URL** and a **Generated Axis URL** are mutually exclusive connection
  inputs; they are never combined.
- `StreamConfig` selects the requested streams for either connection input; stream
  availability is established by the camera's SDP, not URL inspection.
- For a **Generated Axis URL**, the presence of `video` and `metadata` in `StreamConfig`
  is the single source of truth for Axis media selection; separate media-enable flags
  are not supplied to the endpoint helper.
- On that generated path, requesting metadata selects the initial Axis scene-metadata
  query (`analytics=polygon`).
- Generated video enables the Axis ONVIF replay timestamp extension by default so video
  may carry **Axis Capture Time**; `capture_time=False` omits it. This setting never
  rewrites a supplied URL and is ignored when video is not requested.
- `StreamSession.start()` returns only at **Session Ready**. Startup timeout is a failure
  of readiness and does not wait for first video or metadata delivery.
- A **Requested Stop** never blocks a stream callback; an external application thread may
  wait for the session to end with `join()`.
- A **Startup Cancellation** is normal requested shutdown, not an adapter failure; the
  blocked starter receives `StartCancelledError` and `failure` remains unset.
- A **Callback Failure** is not retried and does not cause later data callbacks to start
  for that session.
- Only a **Callback Failure** exposes an original exception as a failure cause. An
  **Adapter Failure** has no public raw cause or exception chain.
