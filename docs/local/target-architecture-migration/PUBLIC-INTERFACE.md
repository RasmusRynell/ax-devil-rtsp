# Complete Public Interface Draft

Status: approved for ISSUE-001 implementation on 2026-07-13.

Parent: [Target purpose, users, and optimization goals](../../users-and-optimization-goals.md)

## Recommendation

Expose a one-shot `StreamSession` module with immutable configuration and direct
callbacks. Use `Video.encoded()`, `Video.native()`, and `Video.numpy()` to make work and
ownership visible at construction time. Keep synchronization and host diagnostics in
optional public modules. Hide pipeline construction behind one concrete GStreamer
adapter; do not expose a backend protocol, low/high client split, pull client, or asyncio
variant.

This design deliberately chooses:

- explicit media selection rather than inferring requested streams from callbacks;
- keyword callbacks rather than a shallow callback-bundle object;
- synchronous `start`, `wait`, `run`, and `stop` methods;
- one private control thread/context per running session, used only for lifecycle and bus
  work, while stream callbacks remain on GStreamer delivery threads;
- callback-scoped borrowed values with explicit native retention and independent copying;
- one guarded GStreamer-buffer escape hatch for native/GPU consumers;
- H.264 and H.265 encoded access units initially;
- packed `RGB`, `BGR`, and `GRAY8` NumPy output initially;
- unexpected EOS as a failure for a live RTSP stream;
- no automatic reconnection, semantic scene model, or library-owned stream-data queue.

The signatures below target the repository's Python 3.10 minimum. Forward references
use postponed annotations or quoted class names in implementation; no Python 3.11-only
`typing.Self` dependency is implied.

## Designs considered

### Minimal stream

A single constructor inferred requested media from callback presence and exposed only
`Stream`, `axis_url()`, and `TimeMatcher`. It maximized depth but made configuration
conditional, weakened callback typing, and allowed an omitted callback to silently
change pipeline shape.

### Explicit configuration

Separate request/configuration values, callback bundles, and rich session reports gave
excellent locality. The callback bundle failed the deletion test: deleting it simply
moved the same fields to `StreamSession` without spreading complexity.

### Common-caller session

Mode factories plus `start`/`wait`/`run`/`stop` made normal call sites clearest. This
draft adopts that shape, combined with the stronger endpoint, ownership, failure, and
capability values from the explicit-configuration design.

## Public module layout

```text
ax_devil_rtsp
├── endpoint       # safe endpoints and pure Axis endpoint construction
├── stream         # fixed configuration, session lifecycle, callbacks
├── values         # delivered data, timing, identity, ownership
├── errors         # configuration, lifecycle, ownership, stream failures
├── sync           # optional Axis timing matcher
└── diagnostics    # read-only host capability inspection
```

Implementation-only modules live under `ax_devil_rtsp._gstreamer` plus private metadata
assembly and timing-correlation modules. There is no public pipeline object or adapter
selection seam.

The package root re-exports only the common path:

```python
__all__ = [
    "AxisVideoOptions",
    "Credentials",
    "RtspEndpoint",
    "axis_endpoint",
    "StreamConfig",
    "StreamSession",
    "Video",
    "Metadata",
    "Transport",
    "VideoCodec",
    "PixelFormat",
    "EncodedUnit",
    "NativeFrame",
    "NumpyFrame",
    "SceneMetadata",
    "SessionInfo",
    "SessionEvent",
    "SessionState",
    "SessionStatistics",
    "AxDevilRtspError",
    "ConfigurationError",
    "StreamError",
]
```

Detailed event, failure, ownership, synchronization, and capability types remain public
from their owning modules without crowding the package root.

Importing `ax_devil_rtsp`, `endpoint`, `stream`, `values`, `errors`, `sync`, or
`diagnostics` imports neither GI/GStreamer nor NumPy and performs no initialization or
host checks. Public annotations for `Gst.Buffer` and `numpy.ndarray` use postponed/type-
checking-only references. The concrete adapter imports GI only when a session starts;
NumPy is imported only when NumPy mode starts or a NumPy-specific operation executes.
Missing selected dependencies become the documented capability/config/startup result,
not a package-import failure.

## Endpoint interface

```python
from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True, slots=True, repr=False)
class Credentials:
    username: str
    password: str

    def __repr__(self) -> str:
        return "Credentials(username='***', password='***')"


class AxisTimestampMode(Enum):
    NONE = "none"
    ONVIF_REPLAY = "onvif-replay"


@dataclass(frozen=True, slots=True)
class AxisVideoOptions:
    resolution: tuple[int, int] | None = None
    timestamps: AxisTimestampMode = AxisTimestampMode.ONVIF_REPLAY


class RtspEndpoint:
    @classmethod
    def parse(cls, url: str) -> RtspEndpoint: ...

    @property
    def display_name(self) -> str: ...


def axis_endpoint(
    address: str,
    *,
    credentials: Credentials | None = None,
    port: int | None = None,
    source: int = 1,
    video: AxisVideoOptions | None = None,
) -> RtspEndpoint: ...
```

`RtspEndpoint.parse()` accepts a nonempty complete `rtsp://` or `rtsps://` URL and keeps
the original string unchanged as its private connection value. It rejects control
characters and a missing RTSP scheme, but does not normalize, reconstruct, or otherwise
validate camera-specific authority, path, query, or fragment syntax. It parses only the
minimum needed to derive a credential-safe display name, and validation never echoes the
input. A parsed endpoint is a complete Supplied RTSP URL: the unchanged private value is
passed to GStreamer, and no Axis helper or `StreamConfig` URL setting is merged into it.
The adapter does not inspect it to infer or preflight media capabilities; `StreamConfig`
only determines which requested delivery branches and callbacks are built.

`axis_endpoint()` is pure and is used only when the application does not provide a
complete URL. It stores the structured facts needed to produce a Generated Axis URL;
the adapter renders that URL immediately before connection. It is never combined with a
parsed endpoint. When video is requested and `AxisVideoOptions` is omitted, it is
equivalent to `AxisVideoOptions()`: camera resolution remains the Axis default while the
proven timestamp extension remains enabled. For a Generated Axis URL,
`StreamConfig.video` and `StreamConfig.metadata` are
the single source of truth for requested media: the adapter derives the Axis media query
from their presence and does not accept duplicate media-enable flags. In the initial
matrix, `metadata is not None` adds the fixed Axis scene-metadata selection
`analytics=polygon`; `Metadata` otherwise controls only bounded document assembly.
Runtime negotiation, rather than URL inspection, establishes whether a requested branch
is available.

The initial generated helper deliberately produces `rtsp://` only and supports only proven settings: address,
credentials, port, camera source, optional resolution, and Axis timestamp extension.
It has no frame-rate, compression, codec, or arbitrary-query option. `address` is a
nonempty hostname/IP without a URL scheme or control characters; `port` is `1..65535`;
`source >= 1`; and resolution dimensions are positive integers. Generated rendering uses
`/axis-media/media.amp`, always disables audio, adds `video=0` only when video is not
requested, adds `analytics=polygon` only when metadata is requested, adds
`onvifreplayext=1` only for requested video with `ONVIF_REPLAY`, applies resolution only
to requested video, and always adds the selected `camera` source. Query ordering is
the fixed `video`, `audio`, `onvifreplayext`, `resolution`, `analytics`, `camera` order
with absent keys skipped, and is covered by exact-string tests. IPv6 literals are
bracketed during generated rendering.
`AxisVideoOptions.timestamps` defaults to `ONVIF_REPLAY`; `NONE` omits the query key.
Timestamp and other video options are ignored when `StreamConfig.video is None` rather
than causing a metadata-only generated URL to request video behavior.
`Credentials` supplied to the generated helper require a nonempty username; an empty
password is allowed, and both components are percent-encoded with no userinfo-safe
characters. `port=None` omits the authority port while an explicitly supplied port,
including 554, is rendered. Resolution renders as `WIDTHxHEIGHT`. Applications needing
camera-specific TLS or any nonstandard URL form provide a complete `rtsps://` Supplied
RTSP URL, which remains unchanged.

`display_name`, `repr`, `str`, equality diagnostics, logs, failures, and capability
reports expose at most `rtsp[s]://host[:port]`; they omit userinfo, path, query, and
fragment entirely. If even that authority cannot be derived safely, the display name is
the constant `<rtsp-endpoint>`. Only the concrete adapter can read the private connection representation. Structured credentials and query values are
percent-encoded only when rendering a Generated Axis URL; a Supplied RTSP URL is never
decoded and re-encoded.

## Immutable stream configuration

```python
from dataclasses import dataclass
from enum import Enum


class Transport(Enum):
    TCP = "tcp"
    UDP = "udp"
    AUTO = "auto"


class VideoCodec(Enum):
    H264 = "h264"
    H265 = "h265"


class PixelFormat(Enum):
    RGB = "RGB"
    BGR = "BGR"
    GRAY8 = "GRAY8"


class VideoMode(Enum):
    ENCODED = "encoded"
    NATIVE = "native"
    NUMPY = "numpy"


@dataclass(frozen=True, slots=True)
class Video:
    mode: VideoMode
    pixel_format: PixelFormat | None = None

    @classmethod
    def encoded(cls) -> Video: ...

    @classmethod
    def native(cls) -> Video: ...

    @classmethod
    def numpy(
        cls,
        *,
        format: PixelFormat = PixelFormat.RGB,
    ) -> Video: ...


@dataclass(frozen=True, slots=True)
class Metadata:
    max_document_bytes: int = 4 * 1024 * 1024
    max_packets_per_document: int = 4096


@dataclass(frozen=True, slots=True)
class DiagnosticsConfig:
    measure_callback_time: bool = False
    trace_pipeline: bool = False
    track_allocations: bool = False


@dataclass(frozen=True, slots=True)
class StreamConfig:
    endpoint: RtspEndpoint
    video: Video | None = None
    metadata: Metadata | None = None
    transport: Transport = Transport.AUTO
    latency_ms: int = 100
    startup_timeout_s: float = 15.0
    diagnostics: DiagnosticsConfig = DiagnosticsConfig()
```

Configuration rules:

- At least one of `video` or `metadata` is required.
- Configuration is immutable and valid for one session lifetime.
- `latency_ms >= 0`; `startup_timeout_s > 0` and finite.
- `latency_ms` defaults to 100 consistently across the Python API and CLI. It configures
  GStreamer's RTSP jitter/latency behavior once at startup and is not a second
  library-owned queue.
- Metadata assembly limits are positive integers. They bound one in-progress document,
  not the session's lifetime document count.
- `Transport.AUTO` is the default and preserves the existing behavior of letting
  GStreamer negotiate between UDP and TCP. `Transport.TCP` forces interleaved RTP over
  TCP, and `Transport.UDP` permits only UDP.
  Once ready, `SessionInfo.transport` is the actual `TCP` or `UDP` transport and never
  `AUTO`.
- `VideoCodec.H264` and `VideoCodec.H265` are the complete initial negotiated codec
  outcomes. The source selects one through normal RTP caps negotiation; there is no
  public codec request, preference, or retry order.
- `Video.encoded()` accepts a negotiated H.264 or H.265 stream and produces Annex-B
  byte-stream access units aligned to codec access units, with parameter sets available
  at random-access points. The adapter selects the depayloader/parser from negotiated
  RTP caps; unsupported codecs fail clearly at runtime.
- Direct `Video` construction is validated: `ENCODED` and `NATIVE` require
  `pixel_format=None`, while `NUMPY` requires one of the three `PixelFormat` values.
  The three factories are the recommended way to produce only valid combinations.
- `Video.native()` lets GStreamer select the decoder and preserves negotiated native
  memory/caps without adding conversion for convenience.
- `Video.numpy()` alone adds GStreamer conversion to packed read-only `uint8` `RGB`,
  `BGR`, or `GRAY8`. It performs no resize.
- NumPy caps require CPU-mappable GStreamer SystemMemory. `RGB` and `BGR` arrays have
  shape `(height, width, 3)`, byte strides `(row_stride, 3, 1)`, and channel order matching
  the selected enum. `GRAY8` has shape `(height, width)` and strides `(row_stride, 1)`.
  Borrowed arrays preserve negotiated row padding and therefore need not be C-contiguous;
  `NumpyFrame.copy()` is always writable and C-contiguous.
- NumPy is neither imported nor required for the other modes.
- Configuration validation is pure and imports neither GI nor NumPy.
- `DiagnosticsConfig()` has no extra hot-path instrumentation. `measure_callback_time`
  adds monotonic-clock reads around callbacks; `trace_pipeline` emits credential-safe
  control-path debug records without URLs, payloads, or credentials; and
  `track_allocations` counts explicit library copy/materialization operations and known
  requested bytes. It does not enable `tracemalloc` or another process-global profiler.
  Each choice is fixed before startup.
- Every appsink uses direct signal delivery with one queued sample at most, no last-sample
  retention, and dropping disabled. A slow callback therefore applies visible upstream
  backpressure instead of causing a hidden library queue or silent frame/document drops;
  applications that want dropping or buffering implement it after explicit retain/copy.
- A session supports one track per requested kind. During normal dynamic-pad discovery,
  the adapter binds the first compatible unbound video pad (negotiated H.264/H.265) and
  first compatible unbound RTP `media=application` pad for metadata, in source discovery
  order; audio, unsupported pads, and later same-kind pads are ignored and may be traced.
  There is no public track selector or URL inspection. A caller that needs a particular
  track supplies an endpoint URL whose server-side selection exposes that track.

## Session interface

```python
from collections.abc import Callable

VideoValue = EncodedUnit | NativeFrame | NumpyFrame
VideoCallback = Callable[[VideoValue], None]
MetadataCallback = Callable[[SceneMetadata], None]
EventCallback = Callable[[SessionEvent], None]
ErrorCallback = Callable[[StreamFailure], None]


class SessionState(Enum):
    CREATED = "created"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


class StreamSession:
    def __init__(
        self,
        config: StreamConfig,
        *,
        on_video: VideoCallback | None = None,
        on_metadata: MetadataCallback | None = None,
        on_event: EventCallback | None = None,
        on_error: ErrorCallback | None = None,
    ) -> None: ...

    @property
    def state(self) -> SessionState: ...

    @property
    def info(self) -> SessionInfo | None: ...

    @property
    def failure(self) -> StreamFailure | None: ...

    def start(self) -> SessionInfo: ...
    def wait(self, *, timeout_s: float | None = None) -> None: ...
    def run(self) -> None: ...
    def request_stop(self) -> bool: ...
    def stop(self, *, timeout_s: float | None = None) -> None: ...
    def statistics(self) -> SessionStatistics: ...

    def __enter__(self) -> StreamSession: ...
    def __exit__(self, exc_type, exc, traceback) -> None: ...
```

Construction requires a callback for every requested stream and forbids a callback for
an unrequested stream. This prevents paid work with no consumer. Event and error
callbacks are optional.

The session is one-shot and never reconnects. Its complete transition table is:

| From | Trigger | To |
| --- | --- | --- |
| `CREATED` | `start()` | `STARTING` |
| `CREATED` | accepted stop | `STOPPED` |
| `STARTING` | readiness wins | `RUNNING` |
| `STARTING` | requested stop wins | `STOPPING`, then `STOPPED` |
| `STARTING` | startup/adapter/callback failure wins | cleanup, then `FAILED` |
| `RUNNING` | requested stop wins | `STOPPING`, then `STOPPED` |
| `RUNNING` | adapter/callback/EOS failure wins | cleanup, then `FAILED` |

No other transition is legal. In particular, accepted stop owns `STOPPING`, so later
teardown noise cannot change it to `FAILED`.

Exact lifecycle behavior:

- `start()` creates the private GStreamer control context/thread, then blocks until every
  requested stream is discovered, linked, caps-negotiated, and the pipeline is playing.
  It does not wait for the first payload; quiet metadata is still ready. The
  `startup_timeout_s` timer applies from the beginning of `STARTING` until this condition
  is satisfied. If it expires, startup fails with `StartupTimeoutError`, the adapter
  cleans up, and `start()` raises the terminal failure. On success it returns immutable
  `SessionInfo`.
- Requested sink paths are held by temporary blocking probes during startup. After every
  requested branch is negotiated and the pipeline reports playing, the control thread
  sets `RUNNING`, publishes `SessionReady`, signals the blocked `start()`, and removes the
  probes. This provides backpressure rather than buffering/dropping and guarantees no
  data callback starts before `SessionReady`.
- If source discovery completes without a requested compatible stream, startup fails
  immediately with `MissingStreamError`; if a requested pad exists but caps/linking or
  its selected processing path is unsupported, it fails with `NegotiationError`. The
  startup timer remains the fallback when discovery/readiness never reaches a conclusive
  result.
- `wait()` blocks until terminal cleanup. Its own timeout raises built-in `TimeoutError`
  and leaves the session running. A terminal failure raises the stored concrete
  `StreamError` after cleanup.
- `wait()` and `stop()` are forbidden from any data, event, error, or session-control
  callback context, even with a zero timeout, because lifecycle waiting on an owned
  execution context is error-prone. They raise `SessionContextError` before changing
  state; callback code uses `request_stop()`.
- `run()` is exactly `start()` followed by `wait()`.
- `request_stop()` is thread-safe, nonblocking, idempotent, and legal inside any callback.
  It returns `True` only for the first accepted request.
- If an accepted request arrives during `STARTING`, startup is cancelled transactionally,
  state becomes `STOPPED`, `failure` remains `None`, and the blocked `start()` raises
  `StartCancelledError`. This is requested lifecycle cancellation, not a `StreamFailure`;
  it emits `SessionStopping` and `SessionStopped`, but never `SessionFailed`.
- `stop()` requests stop and synchronously waits through cleanup from an external
  application thread. Repeated calls after a successful stop are no-ops.
- `wait(timeout_s=...)` and `stop(timeout_s=...)` require a finite nonnegative timeout;
  zero performs a poll. A stop timeout leaves cleanup running in `STOPPING`; it does not
  convert requested shutdown into failure, and a later `stop()`/`wait()` may wait again.
- `request_stop()` or `stop()` in `CREATED` moves directly to `STOPPED` without importing
  GI. The first such call is accepted; later stop requests are no-ops.
- `wait()` in `CREATED` raises `SessionStateError` because no run has begun. `wait()` in
  `STOPPED` returns immediately. `wait()` in `FAILED` raises the session's stable
  `StreamError`; repeated calls raise the same failure classification and report.
- `request_stop()` in `STOPPING`, `STOPPED`, or `FAILED` returns `False`. `stop()` in
  `STOPPED` or after completed cleanup in `FAILED` is a no-op; it does not hide or
  re-raise the terminal failure, which remains available through `failure` and `wait()`.
- `start()` or `run()` outside `CREATED` raises `SessionStateError`; create a new session
  to restart or reconnect.
- `__enter__()` calls `start()` and returns an already-ready session. `__exit__()` calls
  `stop()`. If the context body raised, that exception is never suppressed or replaced
  by a session failure. If the body completed normally, `__exit__()` calls `wait()` after
  cleanup so a terminal session failure cannot be silently hidden.
- `info` remains `None` until readiness, then retains the immutable negotiated snapshot
  through `STOPPING`, `STOPPED`, or a later `FAILED`. `failure` is non-`None` only in
  `FAILED`. `statistics()` is legal in every state and returns zero/current/final counts
  as applicable.
- Readiness, requested stop, and adapter failure are linearized under the session lock.
  If stop wins while starting, `start()` is cancelled; if readiness wins first, `start()`
  returns normally and shutdown proceeds from `RUNNING`; if failure wins, the session
  reports that failure. The first accepted terminal action wins. After stop is accepted,
  teardown EOS/errors and exceptions from callbacks that were already running cannot
  upgrade `STOPPING` to `FAILED`; a late callback exception increments
  `callback_failures` and produces only a sanitized type-only log. If callback failure is
  accepted first, it becomes terminal and a later stop request returns `False`.

## Threading and callback ordering

- Video and metadata callbacks execute directly on their relevant GStreamer delivery
  threads. The library adds no stream-data queue, worker dispatch, or thread handoff.
- Calls for one negotiated stream are ordered and non-reentrant.
- Video and metadata callbacks have no cross-stream ordering guarantee and may execute
  concurrently. Different sessions may also invoke callbacks concurrently.
- Event and error callbacks execute serially on the private session-control thread.
- `SessionReady` is published after the state becomes `RUNNING` and before the first
  data callback.
- Callbacks must return promptly. GUI signals, queues, executors, dropping, and buffering
  belong to the application.
- `state`, `info`, `failure`, `request_stop()`, and `statistics()` are thread-safe.

If a data callback raises before requested stop or another failure has won:

1. the first exception becomes the terminal cause;
2. no new data callback begins, although an already-running callback for another stream
   may finish;
3. cleanup is scheduled on the control context after callback unwinding;
4. the session transitions to `FAILED` after adapter-owned resources are released;
5. `on_error` receives one `StreamFailure` whose `cause` is the original exception;
6. `wait()`/`run()` raises `CallbackError` chained from that same exception.

No new data callback starts after stop/failure is accepted. A callback already in
progress may return or raise according to the first-terminal-action rule above.

Cleanup order is fixed: prevent new callback entry; disconnect timers, bus watches, and
signals; release temporary probes and adapter-owned samples/maps; drive the pipeline to
`NULL`; release pads/elements and pure assembly/timing state; stop the private context;
then let its thread exit. Synchronous callers return only after that sequence and control
thread termination. Application-retained buffers are not awaited or forcibly closed;
they own independent native references and continue updating their detached retention
counter when eventually closed.

`on_event` and `on_error` are observer callbacks rather than stream-data consumers. If
either raises, the library emits one credential-safe log record containing the callback
name and exception type (not its message, arguments, or traceback), disables that
observer for the rest of the session, and continues the already-selected lifecycle
outcome. Observer failures never replace or create a terminal `StreamFailure`.

## Delivered identity and timing

```python
from dataclasses import dataclass
from enum import Enum
from uuid import UUID


class StreamKind(Enum):
    VIDEO = "video"
    SCENE_METADATA = "scene-metadata"


@dataclass(frozen=True, slots=True)
class StreamIdentity:
    session_id: UUID
    kind: StreamKind


@dataclass(frozen=True, slots=True)
class RtpIdentity:
    ssrc: int
    payload_type: int
    clock_rate: int


@dataclass(frozen=True, slots=True)
class AxisCaptureTime:
    ntp_era: int
    ntp_seconds: int
    ntp_fraction: int

    @property
    def unix_time_ns(self) -> int: ...


@dataclass(frozen=True, slots=True)
class MediaTiming:
    pts_ns: int | None
    dts_ns: int | None
    duration_ns: int | None
    rtp_timestamp: int | None
    axis_capture_time: AxisCaptureTime | None
    arrival_monotonic_ns: int
    discontinuity: bool
```

`AxisCaptureTime` preserves the exact unsigned 32-bit wire seconds/fraction instead of
reducing it to a microsecond `datetime`. The adapter infers `ntp_era` as the era nearest
the packet's local realtime arrival, making the 2036 rollover explicit and testable.
`unix_time_ns` is exactly
`((era * 2**32 + seconds) - 2_208_988_800) * 1_000_000_000 +
(fraction * 1_000_000_000 // 2**32)`; fractional conversion floors with less than one
nanosecond error and performs no float/datetime round trip. Field ranges and era
conversion are pure-validated/tested.

Every video value also has a monotonically increasing `sequence` scoped to its
`StreamIdentity`. Correlation resets explicitly on discontinuity, flush, overflow, or
stream replacement rather than silently shifting timing to a later frame.

## ISSUE-001 internal primitive contracts

These are private implementation seams, but their behavior is fixed here so the first
issue can be implemented and reviewed without inventing policy.

### Metadata assembly

The GStreamer adapter extracts complete RTP payload bytes with `GstRtp` and passes plain
facts to a GI-independent assembler: 16-bit sequence number, 32-bit timestamp, marker,
payload bytes, and monotonic arrival time. The assembler is instantiated per negotiated
metadata stream and returns an ordered batch because one packet may both drop an old
incomplete timestamp and complete a new document.

The result union consists of:

- a complete strict UTF-8 document with byte count, RTP timestamp, inclusive first/last
  sequence numbers, and final-packet arrival time; or
- a typed recoverable drop with one of `SEQUENCE_GAP`, `TIMESTAMP_CHANGE`, `BYTE_LIMIT`,
  `PACKET_LIMIT`, `MISSING_XML_START`, `INVALID_UTF8`, or `RESET`, plus the applicable
  expected/received sequence and previous/current timestamp facts.

Assembly rules are exact:

- sequence continuity uses modulo 65,536, so `65535 -> 0` is contiguous;
- packets with one RTP timestamp accumulate through its marker bit;
- a timestamp change before marker drops the incomplete document, then considers the
  current packet as the start of the new timestamp;
- a sequence gap inside a document makes that timestamp corrupt and discards through its
  marker; a later timestamp can recover immediately;
- a sequence gap while idle does not poison a packet that visibly starts a fresh XML
  document, but a non-starting tail is discarded through marker;
- exceeding either positive configured limit drops immediately and discards the rest of
  that timestamp through marker, preventing a tail from being emitted as a new document;
- at marker, bytes before the first `<` are discarded as transport prefix; no `<` or
  strict UTF-8 decode failure is a recoverable typed drop;
- XML well-formedness and semantic content are never parsed or validated by the core;
- flush, stream replacement, and teardown reset state; reset reports a drop only when an
  incomplete/corrupt document actually existed.

“Visibly starts” preserves the proven byte-level rule: after ASCII whitespace and an
optional UTF-8 BOM, the payload starts with an XML declaration or an opening element
whose prefix-independent local name is `MetadataStream`. It is only a resynchronization
boundary check, not semantic XML parsing.

Recoverable document drops increment `metadata_drops` and optionally appear in pipeline
trace diagnostics. They do not call `on_error`, fail the session, or retry data. Invalid
configuration (`max_document_bytes <= 0` or `max_packets_per_document <= 0`) is a pure
`ConfigurationError` before GI import.

### Video timing correlation

The adapter parses a valid Axis `0xABAC` RTP extension into exact `AxisCaptureTime` and
records only lightweight keys/facts, never packet payloads, samples, or stream buffers.
The correlator has a fixed internal capacity of 512 completed video units per stream:

- before depayloading, `(stream identity, RTP timestamp)` identifies the completed RTP
  access unit and its optional capture time;
- at the depayloader output, that exact unit is associated with its output PTS; encoded
  delivery receives the result directly;
- decoded delivery resolves by exact output PTS, with insertion order only as a tie-break
  for duplicate PTS values, so decoder delay or reordering cannot shift a latest value
  onto the wrong frame;
- missing RTP extension, missing PTS, an unknown key, or an evicted key yields
  `axis_capture_time=None`; it never consumes or substitutes a neighboring fact;
- RTP discontinuity, pipeline flush, stream replacement, and session teardown clear the
  relevant state; capacity overflow evicts oldest unresolved facts and returns an
  explicit overflow result for counters/diagnostics.

Pure tests cover key matching, duplicate/missing PTS, reordering, overflow, reset, and
non-shifting behavior. Adapter tests separately prove the RTP-extension and output-key
facts supplied to this module are the facts from the actual GStreamer path.

## Borrowed and owned buffers

Borrowed wrappers expire in a callback-finally block even if the callback raises.
Access through a wrapper after expiry raises `BorrowExpiredError`. Python cannot revoke a
raw `memoryview`, NumPy array, or GStreamer object deliberately escaped from its scope;
such aliases are contractually invalid after callback return.

```python
class BorrowedBuffer:
    @property
    def size(self) -> int: ...

    def map_read(self) -> ContextManager[memoryview]: ...
    def retain(self) -> RetainedBuffer: ...
    def copy(self) -> OwnedBuffer: ...


class BorrowedNativeBuffer(BorrowedBuffer):
    @property
    def gst_buffer(self) -> Gst.Buffer: ...

    def copy(self) -> OwnedNativeBuffer: ...


class RetainedBuffer:
    @property
    def closed(self) -> bool: ...

    def map_read(self) -> ContextManager[memoryview]: ...
    def copy(self) -> OwnedBuffer: ...
    def close(self) -> None: ...
    def __enter__(self) -> RetainedBuffer: ...
    def __exit__(self, exc_type, exc, traceback) -> None: ...


class RetainedNativeBuffer(RetainedBuffer):
    @property
    def gst_buffer(self) -> Gst.Buffer: ...

    def copy(self) -> OwnedNativeBuffer: ...


class OwnedBuffer:
    @property
    def closed(self) -> bool: ...

    def map_read(self) -> ContextManager[memoryview]: ...
    def close(self) -> None: ...
    def __enter__(self) -> OwnedBuffer: ...
    def __exit__(self, exc_type, exc, traceback) -> None: ...


class OwnedNativeBuffer(OwnedBuffer):
    @property
    def gst_buffer(self) -> Gst.Buffer: ...
```

`retain()` increments the native reference without copying contents. Retained buffers
remain valid after callback return and session shutdown but occupy native memory and may
pin a GStreamer pool; applications must bound them and call `close()`.

`copy()` creates independent storage that does not pin the stream pool. Native/GPU
memory that cannot be copied without changing its memory contract raises
`BufferCopyError`; the library never silently stages it to CPU.

`BorrowedNativeBuffer.gst_buffer` is the single intentional expert escape hatch. It gives
native/GPU consumers the actual borrowed `Gst.Buffer` without exposing the pipeline or
adapter. An escaped object remains subject to the same callback lifetime. Retained access
requires `RetainedNativeBuffer.gst_buffer`.
This explicit backend type is intentional: GStreamer is the only production adapter,
and a generic native handle would either leak the same type indirectly or erase required
memory/GPU operations. Adding a second backend would trigger a new evidence-based design,
not a speculative protocol in this migration.

Borrowed wrappers are callback-thread-only. Retained and owned wrappers may be handed to
another application thread; `close()` is thread-safe and idempotent. Starting a map,
copy, retain, or native escape after expiry/close raises the corresponding ownership
error. Each map context keeps its own native reference, so closing the parent while a map
is active prevents new operations but does not invalidate that active view; the view
expires when its map context exits. A raw view or `Gst.Buffer` alias cannot be revoked
and remains contractually invalid beyond its declared scope.

## Video and metadata values

```python
from dataclasses import field


@dataclass(frozen=True, slots=True)
class EncodedFormat:
    codec: VideoCodec
    stream_format: str       # "byte-stream"
    alignment: str           # "au"


@dataclass(frozen=True, slots=True)
class EncodedUnit:
    identity: StreamIdentity
    rtp: RtpIdentity
    sequence: int
    timing: MediaTiming
    format: EncodedFormat
    key_frame: bool
    data: BorrowedBuffer

    def retain(self) -> RetainedEncodedUnit: ...
    def copy(self) -> bytes: ...


@dataclass(frozen=True, slots=True)
class NativeVideoFormat:
    width: int
    height: int
    gst_format: str
    memory_features: tuple[str, ...]
    strides: tuple[int, ...]
    offsets: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class NumpyVideoFormat:
    width: int
    height: int
    pixel_format: PixelFormat
    row_stride: int


@dataclass(frozen=True, slots=True)
class NativeFrame:
    identity: StreamIdentity
    rtp: RtpIdentity
    sequence: int
    timing: MediaTiming
    format: NativeVideoFormat
    buffer: BorrowedNativeBuffer

    def retain(self) -> RetainedNativeFrame: ...
    def copy(self) -> OwnedNativeFrame: ...


@dataclass(frozen=True, slots=True)
class NumpyFrame:
    identity: StreamIdentity
    rtp: RtpIdentity
    sequence: int
    timing: MediaTiming
    format: NumpyVideoFormat
    _buffer: BorrowedBuffer = field(repr=False)
    _array: numpy.ndarray = field(repr=False)

    @property
    def array(self) -> numpy.ndarray: ...  # checks _buffer's callback borrow guard

    def retain(self) -> RetainedNumpyFrame: ...
    def copy(self) -> numpy.ndarray: ...


@dataclass(frozen=True, slots=True)
class SceneMetadata:
    identity: StreamIdentity
    rtp: RtpIdentity
    sequence: int
    xml: str
    byte_count: int
    rtp_timestamp: int
    first_rtp_sequence: int
    last_rtp_sequence: int
    arrival_monotonic_ns: int


@dataclass(frozen=True, slots=True)
class RetainedEncodedUnit:
    identity: StreamIdentity
    rtp: RtpIdentity
    sequence: int
    timing: MediaTiming
    format: EncodedFormat
    key_frame: bool
    data: RetainedBuffer

    def copy(self) -> bytes: ...
    def close(self) -> None: ...
    def __enter__(self) -> RetainedEncodedUnit: ...
    def __exit__(self, exc_type, exc, traceback) -> None: ...


@dataclass(frozen=True, slots=True)
class RetainedNativeFrame:
    identity: StreamIdentity
    rtp: RtpIdentity
    sequence: int
    timing: MediaTiming
    format: NativeVideoFormat
    buffer: RetainedNativeBuffer

    def copy(self) -> OwnedNativeFrame: ...
    def close(self) -> None: ...
    def __enter__(self) -> RetainedNativeFrame: ...
    def __exit__(self, exc_type, exc, traceback) -> None: ...


@dataclass(frozen=True, slots=True)
class RetainedNumpyFrame:
    identity: StreamIdentity
    rtp: RtpIdentity
    sequence: int
    timing: MediaTiming
    format: NumpyVideoFormat
    buffer: RetainedBuffer

    def map_array(self) -> ContextManager[numpy.ndarray]: ...
    def copy(self) -> numpy.ndarray: ...
    def close(self) -> None: ...
    def __enter__(self) -> RetainedNumpyFrame: ...
    def __exit__(self, exc_type, exc, traceback) -> None: ...


@dataclass(frozen=True, slots=True)
class OwnedNativeFrame:
    identity: StreamIdentity
    rtp: RtpIdentity
    sequence: int
    timing: MediaTiming
    format: NativeVideoFormat
    buffer: OwnedNativeBuffer

    def close(self) -> None: ...
    def __enter__(self) -> OwnedNativeFrame: ...
    def __exit__(self, exc_type, exc, traceback) -> None: ...
```

Additional ownership rules:

- `EncodedUnit.copy()` returns independent `bytes`.
- `NativeFrame.copy()` returns an explicitly closable deep native copy or raises
  `BufferCopyError`; it never converts memory type or pixel format silently.
- `NumpyFrame.array` is a borrowed, read-only view with negotiated row stride.
- Accessing `NumpyFrame.array`, `retain()`, or `copy()` through the frame after callback
  expiry raises `BorrowExpiredError`. An ndarray alias deliberately saved while the
  callback was active cannot be revoked by Python and is contractually invalid afterward;
  applications must use `copy()` or `retain()` inside the callback.
- `NumpyFrame.copy()` returns a writable C-contiguous independent NumPy array.
- `NumpyFrame.retain()` returns `RetainedNumpyFrame` and retains the already-converted
  packed CPU backing without copying. It never extends the original array view; later
  access uses a new read-only scoped `map_array()` view with the same negotiated format
  and row stride. Mapping performs no conversion. Arbitrary `NativeFrame` values have no
  NumPy mapping method because conversion must be selected in the startup pipeline.
- `SceneMetadata` is ordinary owned Python data and requires no retain/copy operation.
  It contains exactly one strict UTF-8 XML string and does not retain duplicate bytes.
- The metadata callback receives `SceneMetadata`, not a bare string or dictionary;
  callers use `.xml` for the document and the same value's identity/timing fields for
  correlation.
- Core delivery never semantically parses scene XML. Only the optional synchronizer
  extracts `UtcTime`.
- `NativeVideoFormat` copies width/height, negotiated GStreamer format, canonical caps
  memory-feature strings, and available `GstVideoMeta` plane strides/offsets. For
  opaque/unmappable native memory, strides/offsets are empty rather than guessed.
- `VideoStreamInfo.decoder` and `processing_path` contain credential-safe GStreamer
  factory names in actual data-flow order, not object names, pointers, full caps dumps,
  filesystem plugin paths, or speculative candidates.

Retained/owned video counterparts preserve immutable identity, sequence, timing, and
format values while replacing the borrowed buffer with its retained/owned form. All
retained/owned video values are context managers with idempotent `close()`.

## Session information, events, and statistics

```python
@dataclass(frozen=True, slots=True)
class VideoStreamInfo:
    identity: StreamIdentity
    rtp: RtpIdentity | None
    encoded: EncodedFormat
    decoded: NativeVideoFormat | None
    decoder: str | None
    processing_path: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MetadataStreamInfo:
    identity: StreamIdentity
    rtp: RtpIdentity | None
    encoding: str             # "UTF-8 XML"


@dataclass(frozen=True, slots=True)
class SessionInfo:
    session_id: UUID
    endpoint: str             # credential-safe display name
    transport: Transport
    video: VideoStreamInfo | None
    metadata: MetadataStreamInfo | None


@dataclass(frozen=True, slots=True)
class CounterSummary:
    count: int
    total_ns: int
    minimum_ns: int
    maximum_ns: int


@dataclass(frozen=True, slots=True)
class AllocationSummary:
    count: int
    requested_bytes: int | None


@dataclass(frozen=True, slots=True)
class SessionStatistics:
    captured_at_monotonic_ns: int
    state: SessionState
    video_units: int
    video_bytes: int
    metadata_documents: int
    metadata_bytes: int
    metadata_drops: int
    discontinuities: int
    callback_failures: int
    outstanding_retained_buffers: int
    callback_time_ns: Mapping[str, CounterSummary] | None
    allocation_counts: Mapping[str, AllocationSummary] | None
```

Cheap counters are always available through `statistics()`. Callback timing and
allocation facts are `None` unless their corresponding diagnostic is enabled before
startup. Allocation categories cover explicit library-owned copies/materializations;
unknown native allocation sizes remain `None` rather than being guessed. All public
`Mapping` fields are immutable snapshot views; no mutable internal dictionary escapes.
The interface does not add
periodic reporting threads, exporters, labels, or a telemetry framework; applications
decide when to sample.

Events are a closed union without optional-field ambiguity:

```python
@dataclass(frozen=True, slots=True)
class SessionStarting:
    session_id: UUID
    monotonic_ns: int


@dataclass(frozen=True, slots=True)
class StreamNegotiated:
    session_id: UUID
    monotonic_ns: int
    stream: VideoStreamInfo | MetadataStreamInfo


@dataclass(frozen=True, slots=True)
class SessionReady:
    session_id: UUID
    monotonic_ns: int
    info: SessionInfo


@dataclass(frozen=True, slots=True)
class SessionStopping:
    session_id: UUID
    monotonic_ns: int


@dataclass(frozen=True, slots=True)
class SessionStopped:
    session_id: UUID
    monotonic_ns: int


@dataclass(frozen=True, slots=True)
class SessionFailed:
    session_id: UUID
    monotonic_ns: int
    failure: StreamFailure


SessionEvent = (
    SessionStarting
    | StreamNegotiated
    | SessionReady
    | SessionStopping
    | SessionStopped
    | SessionFailed
)
```

Each event contains `session_id` and `monotonic_ns`. `StreamNegotiated` contains one
stream-information value, `SessionReady` contains the final `SessionInfo`,
and `SessionFailed` contains the terminal `StreamFailure`. `SessionStopping` and
`SessionStopped` unambiguously mean requested shutdown; failures use `SessionFailed`, so
there is no one-value `StopReason` enum. A normal run emits `SessionStarting`, one `StreamNegotiated`
per requested stream, `SessionReady`, `SessionStopping`, then `SessionStopped`. A failed
run ends with `SessionFailed` after cleanup and emits neither `SessionStopping` nor
`SessionStopped`. Direct `CREATED` to `STOPPED` does not create a control thread and
emits no lifecycle event.
For failure, cleanup completes first, then `SessionFailed` is offered to `on_event`, then
the same `StreamFailure` is offered once to `on_error`. Observer exceptions follow the
nonterminal disable-and-log rule above. Terminal waiters are signaled only after these
observer calls and, for normal shutdown, after `SessionStopped`; therefore synchronous
`wait()`/`stop()` returns after lifecycle notification is complete and the control thread
has exited.

## Failure interface

Pure caller/lifetime mistakes are not fabricated as stream failures:

```python
class AxDevilRtspError(Exception): ...
class ConfigurationError(AxDevilRtspError, ValueError): ...
class EndpointError(ConfigurationError): ...
class SessionStateError(AxDevilRtspError, RuntimeError): ...
class SessionContextError(AxDevilRtspError, RuntimeError): ...
class StartCancelledError(AxDevilRtspError, RuntimeError): ...
class BorrowExpiredError(AxDevilRtspError, RuntimeError): ...
class BufferClosedError(AxDevilRtspError, RuntimeError): ...
class BufferMapError(AxDevilRtspError, RuntimeError): ...
class BufferCopyError(AxDevilRtspError, RuntimeError): ...
class CapabilityError(AxDevilRtspError, RuntimeError): ...
```

Terminal stream failures have one stable structured report:

```python
class FailureKind(Enum):
    DEPENDENCY = "dependency"
    CONNECTION = "connection"
    STARTUP_TIMEOUT = "startup-timeout"
    MISSING_STREAM = "missing-stream"
    NEGOTIATION = "negotiation"
    DECODE = "decode"
    PROTOCOL = "protocol"
    METADATA = "metadata"
    CALLBACK = "callback"
    END_OF_STREAM = "end-of-stream"
    INTERNAL = "internal"


@dataclass(frozen=True, slots=True, repr=False)
class StreamFailure:
    kind: FailureKind
    message: str
    session_id: UUID
    stream: StreamIdentity | None
    cause: BaseException | None  # non-None only for FailureKind.CALLBACK


class StreamError(AxDevilRtspError, RuntimeError):
    failure: StreamFailure


class DependencyError(StreamError): ...
class StreamConnectionError(StreamError): ...
class StartupTimeoutError(StreamError, TimeoutError): ...
class MissingStreamError(StreamError): ...
class NegotiationError(StreamError): ...
class DecodeError(StreamError): ...
class ProtocolError(StreamError): ...
class MetadataError(StreamError): ...
class CallbackError(StreamError): ...
class EndOfStreamError(StreamError): ...
class InternalStreamError(StreamError): ...
```

Failure classifications are stable:

| Kind | Meaning |
| --- | --- |
| `DEPENDENCY` | A required GI namespace, GStreamer element/plugin, or Python optional dependency is absent/incompatible. |
| `CONNECTION` | DNS, socket, RTSP authentication/control, or remote connection loss prevents operation. |
| `STARTUP_TIMEOUT` | The configured readiness deadline expires without another conclusive startup result. |
| `MISSING_STREAM` | Discovery completes without a requested compatible video or metadata stream. |
| `NEGOTIATION` | A requested stream exists but caps, linking, codec, decoder, conversion, or memory negotiation cannot satisfy its fixed mode. |
| `DECODE` | A selected decoder fails after successful startup. |
| `PROTOCOL` | Malformed RTSP/RTP behavior makes the negotiated branch unusable. |
| `METADATA` | The metadata branch itself becomes unusable; recoverable per-document assembly drops are excluded. |
| `CALLBACK` | A data callback raises before another terminal action wins. |
| `END_OF_STREAM` | Unexpected EOS occurs before requested stop. |
| `INTERNAL` | A library invariant fails and no narrower classification applies. |

An underlying dependency message is mapped to the narrowest stable kind using structured
error domains/codes and current lifecycle context, never by exposing its raw text.

Failure messages, representations, and logs contain only the credential-safe endpoint
name. Callback failures preserve the original application exception as `cause` and as
`CallbackError.__cause__`. For every other `FailureKind`, `StreamFailure.cause` is `None`
and the raised `StreamError.__cause__` is also `None`: raw adapter, dependency, camera,
and GStreamer exceptions are converted to safe structured facts rather than retained,
exposed, or chained. Unexpected EOS is a failure for a live RTSP session; EOS produced
after an accepted stop request is normal cleanup. `StreamFailure` representations never
include `cause`.

The credential-safety guarantee covers every library-created value, exception, log
record, diagnostic, CLI output, and test/benchmark artifact. The library neither enables
nor intercepts process-global GStreamer debug logging. Applications that opt into verbose
`GST_DEBUG` own dependency output, which may include the exact supplied connection
location; install/security guidance calls this out rather than mutating global logging or
silently rewriting the URL.

## Optional synchronization interface

`ax_devil_rtsp.sync` has no dependency on GStreamer or NumPy:

```python
from dataclasses import dataclass
from datetime import timedelta
from enum import Enum
from typing import Generic, TypeVar

V = TypeVar("V")
M = TypeVar("M")


@dataclass(frozen=True, slots=True)
class SyncPolicy:
    tolerance: timedelta
    capacity_per_side: int = 256
    max_age: timedelta = timedelta(seconds=2)


class SyncDropReason(Enum):
    MISSING_TIME = "missing-time"
    OUTSIDE_TOLERANCE = "outside-tolerance"
    EXPIRED = "expired"
    CAPACITY = "capacity"
    RESET = "reset"


class SyncSide(Enum):
    VIDEO = "video"
    METADATA = "metadata"


@dataclass(frozen=True, slots=True)
class SyncMatch(Generic[V, M]):
    video: V
    metadata: M
    video_time_ns: int
    metadata_time_ns: int
    delta_ns: int


@dataclass(frozen=True, slots=True)
class SyncDrop(Generic[V]):
    token: V
    side: SyncSide
    reason: SyncDropReason


@dataclass(frozen=True, slots=True)
class SyncBatch(Generic[V, M]):
    matches: tuple[SyncMatch[V, M], ...]
    drops: tuple[SyncDrop[V | M], ...]


class AxisSynchronizer(Generic[V, M]):
    def __init__(self, policy: SyncPolicy) -> None: ...

    def push_video(
        self,
        timing: MediaTiming,
        token: V,
    ) -> SyncBatch[V, M]: ...

    def push_metadata(
        self,
        document: SceneMetadata,
        token: M,
    ) -> SyncBatch[V, M]: ...

    def flush(self) -> SyncBatch[V, M]: ...
    def reset(self) -> SyncBatch[V, M]: ...
```

The synchronizer is thread-safe because video and metadata callbacks may be concurrent.
It stores only extracted integer time, insertion order, and the caller-owned token. It
never stores a borrowed frame/view or retains a native buffer automatically. Passing a
borrowed delivery value as a token violates the interface; callers pass an identity,
index, copied value, or explicitly retained value.

`SyncPolicy` requires finite `tolerance >= 0`, positive `capacity_per_side`, and finite
positive `max_age`. `push_metadata()` extracts only ONVIF `UtcTime`, accepting a UTC `Z`
timestamp with up to nanosecond fractional precision. It preserves the current proven
rule of selecting the first ONVIF `Frame` element with a `UtcTime` attribute in document
order, identified by namespace URI rather than XML prefix; later frame timestamps are
ignored. Absent, non-UTC, malformed XML, or malformed
first selected time yields `MISSING_TIME`. No other XML is interpreted.

Matching is online, one-to-one, and consuming. Before each push the synchronizer expires
tokens by monotonic residence time. The new token matches the currently pending opposite
token whose absolute media-time delta is smallest and within the inclusive tolerance;
ties choose the earlier media timestamp, then insertion order. `delta_ns` is signed
`video_time_ns - metadata_time_ns`. A token is never rematched or silently removed.

An unmatched token remains pending for future out-of-order input. Age and capacity
evictions return `EXPIRED` and `CAPACITY`; `reset()` returns every pending token as
`RESET`; `flush()` empties both sides and returns remaining tokens as
`OUTSIDE_TOLERANCE`. Each batch reports evictions before a match produced by the same
push. The monotonic clock is privately injectable for deterministic tests.

## Read-only capability interface

`ax_devil_rtsp.diagnostics` is importable without GI and never opens a stream or changes
the host:

```python
class Capability(Enum):
    RTSP = "rtsp"
    AXIS_METADATA = "axis-metadata"
    ENCODED_H264 = "encoded-h264"
    ENCODED_H265 = "encoded-h265"
    NATIVE_DECODE_H264 = "native-decode-h264"
    NATIVE_DECODE_H265 = "native-decode-h265"
    NUMPY_VIDEO = "numpy-video"
    DISPLAY = "display"
    CONTROLLED_STREAM = "controlled-stream"
    BENCHMARK = "benchmark"


class CapabilityStatus(Enum):
    AVAILABLE = "available"
    MISSING = "missing"
    DEGRADED = "degraded"


@dataclass(frozen=True, slots=True)
class CapabilityFinding:
    capability: Capability
    status: CapabilityStatus
    versions: Mapping[str, str]
    missing: tuple[str, ...]
    consequence: str
    remediation: str


@dataclass(frozen=True, slots=True)
class CapabilityReport:
    findings: tuple[CapabilityFinding, ...]

    def status(self, capability: Capability) -> CapabilityStatus: ...
    def require(self, *capabilities: Capability) -> None: ...


def inspect_capabilities(*, detailed: bool = False) -> CapabilityReport: ...

def static_capabilities_for(config: StreamConfig) -> frozenset[Capability]: ...
```

`CapabilityStatus.AVAILABLE` means the capability's required components are present;
`MISSING` means it cannot run; `DEGRADED` means it can run but an optional/faster path is
absent. `require()` accepts available/degraded capabilities and raises `CapabilityError`
only for missing ones, including consequence and remediation.

`static_capabilities_for()` is pure and returns only requirements knowable from fixed
configuration, such as RTSP, metadata, or NumPy support. It deliberately does not claim
an H.264/H.265 encoded or decode requirement because a Supplied RTSP URL is not inspected
and codec choice is a negotiated outcome. `inspect_capabilities(detailed=False)` checks
required GI namespaces and common GStreamer factories and represents missing GI as
findings rather than an import failure. `detailed=True` additionally enumerates
credential-free decoder/converter/display/test/benchmark candidates and versions.

When the negotiated codec/path cannot be satisfied, startup raises the session-scoped
credential-safe `DependencyError` or `NegotiationError` and rolls back. Offline inspection
reports candidates; the actually selected decoder, converter, memory path, and transport
are live `SessionInfo` facts. No public function opens a stream, installs packages,
changes environment variables, applies workarounds, or prints credentials.

## Usage examples

Each snippet below assumes this credential-safe setup unless it shows another endpoint:

```python
import os

from ax_devil_rtsp import RtspEndpoint

endpoint = RtspEndpoint.parse(os.environ["AX_DEVIL_RTSP_URL"])
```

The environment value is passed unchanged to GStreamer and is never printed. The final
executable examples delivered by ISSUE-009 include their own bounded stop condition;
these snippets focus on one API behavior at a time.

### Metadata only

```python
from ax_devil_rtsp import Metadata, StreamConfig, StreamSession

session = StreamSession(
    StreamConfig(endpoint, metadata=Metadata()),
    on_metadata=lambda document: print(document.xml),
)
session.run()
```

No video depayloader, parser, decoder, converter, NumPy import, or display dependency is
created.

### Encoded video for an external decoder

```python
from queue import Full, Queue

from ax_devil_rtsp import EncodedUnit, StreamConfig, StreamSession, Video
from ax_devil_rtsp.values import RetainedEncodedUnit

queue: Queue[RetainedEncodedUnit] = Queue(maxsize=4)


def on_video(unit: EncodedUnit) -> None:
    retained = unit.retain()
    try:
        queue.put_nowait(retained)
    except Full:
        retained.close()


session = StreamSession(
    StreamConfig(endpoint, video=Video.encoded()),
    on_video=on_video,
)
session.run()
```

The consumer must close every dequeued retained unit. If independent Python bytes are
preferred, enqueue `unit.copy()` instead.

### Native decoded frame used immediately

```python
from ax_devil_rtsp import NativeFrame, StreamConfig, StreamSession, Video


def on_video(frame: NativeFrame) -> None:
    submit_to_gpu_now(frame.buffer.gst_buffer, frame.format, frame.timing)


StreamSession(
    StreamConfig(endpoint, video=Video.native()),
    on_video=on_video,
).run()
```

The borrowed `Gst.Buffer` must not escape the callback. Asynchronous native handoff uses
`frame.retain()` and a bounded application queue.

### NumPy frame copied for asynchronous work

```python
from ax_devil_rtsp import NumpyFrame, PixelFormat, StreamConfig, StreamSession, Video


def on_video(frame: NumpyFrame) -> None:
    latest.replace(frame.copy(), frame.timing)


StreamSession(
    StreamConfig(endpoint, video=Video.numpy(format=PixelFormat.BGR)),
    on_video=on_video,
).run()
```

Immediate work may read `frame.array` directly. It is read-only and invalid after the
callback returns.

### Combined independent delivery

```python
from ax_devil_rtsp import Metadata, StreamConfig, StreamSession, Video


session = StreamSession(
    StreamConfig(
        endpoint,
        video=Video.native(),
        metadata=Metadata(),
    ),
    on_video=render_now,
    on_metadata=observe_scene_xml,
    on_error=report_failure,
)
session.run()
```

Neither callback waits for the other. There is no mandatory synchronization buffer.

### Optional synchronization with owned tokens

```python
from datetime import timedelta

from ax_devil_rtsp import NativeFrame, SceneMetadata
from ax_devil_rtsp.sync import AxisSynchronizer, SyncPolicy

sync = AxisSynchronizer(
    SyncPolicy(tolerance=timedelta(milliseconds=20)),
)


def on_video(frame: NativeFrame) -> None:
    token = (frame.identity, frame.sequence)
    publish(sync.push_video(frame.timing, token))


def on_metadata(document: SceneMetadata) -> None:
    token = (document.identity, document.sequence)
    publish(sync.push_metadata(document, token))
```

If the match consumer needs pixels/XML later, its token must own a copy or retained
buffer rather than only an identity string.

### Context-managed session

```python
from ax_devil_rtsp import StreamConfig, StreamSession, Video


config = StreamConfig(endpoint, video=Video.native())
with StreamSession(config, on_video=render_now) as session:
    gui_loop()
```

`__enter__()` returns only after the requested streams are ready. A callback that wants
to finish calls `session.request_stop()`; it never calls blocking `stop()`.

### Multiple cameras

```python
from queue import Queue

from ax_devil_rtsp import StreamError, StreamSession

errors: Queue[StreamError] = Queue()


sessions = [make_session(endpoint) for endpoint in endpoints]
started: list[StreamSession] = []

# start() synchronously waits for each session's private control thread to become ready.
for session in sessions:
    try:
        session.start()
        started.append(session)
    except StreamError as error:
        errors.put(error)

# Application policy decides when/how all sessions stop.
for session in started:
    session.request_stop()
for session in started:
    try:
        session.wait()
    except StreamError as error:
        errors.put(error)
```

Each session owns its control context and GStreamer pipeline. No registry, global loop,
retry policy, or shared mutable stream state coordinates them.

GI module loading, idempotent `Gst.init`, and GStreamer's own plugin registry are
unavoidably process-global dependency facilities. The adapter guards initialization and
does not place session/application state in them. Every GLib `MainContext`, bus watch,
pipeline, timer, callback gate, assembly/correlation state, and counter remains
session-owned; no package-global main loop or mutable session registry exists.

## CLI contract

The installed CLI has exactly two top-level commands and no implicit root streaming
behavior:

```text
ax-devil-rtsp doctor [--json] [--detailed]

ax-devil-rtsp stream
  (--url URL | --address HOST)
  [--username USER] [--ask-password]
  [--port PORT] [--source SOURCE] [--resolution WIDTHxHEIGHT]
  [--axis-timestamps | --no-axis-timestamps]
  [--video encoded|native|numpy] [--metadata]
  [--pixel-format RGB|BGR|GRAY8]
  [--transport auto|tcp|udp] [--latency-ms MS] [--startup-timeout-s SECONDS]
  [--sync-tolerance-ms MS] [--display]
  [--duration-s SECONDS] [--max-video-units COUNT]
  [--max-metadata-documents COUNT] [--json-lines]
```

CLI rules mirror the Python contract:

- `--url` is also available through `AX_DEVIL_RTSP_URL`; its exact value becomes a
  Supplied RTSP URL. It conflicts with every generated endpoint option (`--address`,
  username/password, port, source, resolution, and timestamp flags) instead of silently
  ignoring them.
- Without `--url`, `--address` (or `AX_DEVIL_TARGET_ADDR`) is required. Username may come
  from `--username`/`AX_DEVIL_TARGET_USER`; password comes only from
  `AX_DEVIL_TARGET_PASS` or an interactive `--ask-password` prompt, never a command-line
  value that predictably enters shell history/process listings.
- At least one of `--video` or `--metadata` is required; there is no hidden default mode.
  `--pixel-format` is valid only for NumPy video. `--sync-tolerance-ms` requires both
  video and metadata. `--display` initially requires NumPy BGR video and the display
  extra; it never inserts a Python conversion into another mode.
- Transport defaults to `auto`, latency to 100 ms, startup timeout to 15 seconds, Axis
  timestamps to enabled on generated video, and pixel format to RGB when NumPy is chosen.
- Each positive duration/count limit is optional; the first reached condition calls
  `request_stop()`. With no limit the command runs until signal/failure. SIGINT/SIGTERM
  request graceful stop and produce conventional exit code 130/143 after cleanup.
- Human output contains safe endpoint/session summaries and counts, never payloads by
  default. `--json-lines` emits versioned JSON records for lifecycle, safe failures,
  metadata XML, video-unit summaries, synchronization results, and final statistics;
  binary pixels/encoded bytes and credentials are never dumped. Output write failure
  requests stop and exits nonzero after cleanup.
- Every JSON object contains `schema="ax-devil-rtsp/stream-v1"`, a closed `type`,
  `session_id`, and the relevant public value fields. Failure records omit `cause`;
  video records omit buffer/array contents; metadata records include the requested owned
  XML. Serialization uses only public values and stable enum strings.
- Exit status is 0 for a reached limit/normal completion, 1 for capability/stream/output
  failure, 2 for usage/configuration error, and 130/143 for handled interrupt/termination.
  `doctor` returns 0 when requested capabilities are usable (available or degraded), 1
  when required capabilities are missing, and 2 for usage errors.

The CLI is a thin callback consumer. Display uses one application-owned slot: the
callback retains the already-converted BGR NumPy backing, atomically replaces/closes the
older item, and the display consumer maps then closes each item. It contains no pipeline construction,
retry loop, logging configuration, or second synchronization implementation.

## What the public seam hides

The one concrete GStreamer adapter owns:

- GI import/version setup and GStreamer initialization;
- the private GLib control context/thread;
- `rtspsrc`, transport, pad routing, branch construction, and transactional rollback;
- depayloaders/parsers, GStreamer decoder selection, conversion, caps, and appsinks;
- bus watches, startup timers, EOS/errors, state changes, and teardown order;
- `GstRtp` extraction of payload, padding, extensions, sequence, timestamp, and identity;
- bounded XML assembly, loss detection, strict UTF-8, reset, and recovery;
- bounded video-unit timing correlation across decoder delay/discontinuity/flush;
- `GstSample`/`GstBuffer` references, mapping, `GstVideo` layout, and pool accounting;
- credential rendering/redaction, cheap counters, and opt-in diagnostics.

Pure in-process modules own endpoint/config validation, metadata assembly state, timing
correlation, delivered values, and synchronization. Tests exercise those interfaces
directly. Adapter integration tests use the controlled RTSP stream; real Axis tests
validate the external wire behavior. Because there is one production adapter, no public
port, backend selector, or factory is introduced.

## Deliberate exclusions

The public interface contains no:

- specialized video-only, metadata-only, or combined session classes;
- low-level versus high-level client split;
- public pipeline builder or arbitrary caps/element graph;
- packet-level RTP delivery;
- decoder, GPU-vendor, or plugin preference framework;
- library-owned queue, executor, GUI bridge, or event-loop integration;
- pull iterator, generator, or asyncio client;
- reconnection, retry, or backoff policy;
- semantic Axis/ONVIF scene object model;
- audio, recording, restreaming, transcoding, discovery, or fleet management;
- compatibility aliases for the current retriever interface.

## Legacy deletion and replacement map

The migration does not preserve a second streaming path. Each legacy owner has one
explicit destination:

| Current path or responsibility | Final action | Owning issue |
| --- | --- | --- |
| `src/ax_devil_rtsp/rtsp_data_retrievers.py` and its process/queue dispatcher | Delete after atomic public cutover; no aliases or wrappers | ISSUE-007 |
| `src/ax_devil_rtsp/gstreamer/` public client, mixins, runner, and hard-coded pipeline | Replace with the private `ax_devil_rtsp._gstreamer` adapter, then delete the old package | ISSUE-002 through ISSUE-007 |
| `src/ax_devil_rtsp/raw_socket/metadata_raw.py` and the duplicate RTSP implementation | Delete when metadata-only delivery replaces it; the one GStreamer session owns metadata transport | ISSUE-002 |
| RTP/XML reconstruction and Axis timing facts embedded in callbacks/utilities | Extract into pure bounded metadata/timing modules; delete superseded helpers | ISSUE-001 through ISSUE-006 |
| `src/ax_devil_rtsp/utils/__init__.py` URL, semantic XML, and payload helpers | Move only approved endpoint/assembly behavior to its owning module; delete semantic XML in ISSUE-002 and the remaining broad utility surface at cutover | ISSUE-001, ISSUE-002, and ISSUE-007 |
| `src/ax_devil_rtsp/utils/logging.py` handlers, files, queue listeners, and app configuration | Replace internal calls with namespaced standard loggers; delete library-owned logging setup at cutover | ISSUE-007 |
| `src/ax_devil_rtsp/utils/deps.py` eager checks/workaround activation | Replace with lazy adapter startup checks and the read-only capability inventory | ISSUE-007 and ISSUE-008 |
| Package-root retriever exports | Atomically replace with the approved common-path exports | ISSUE-007 |
| `src/ax_devil_rtsp/cli.py` retriever dispatch, processing callback, and shared mutable config | Keep only a minimal session-based entry point at cutover, then rebuild as a thin public-API consumer | ISSUE-007 and ISSUE-009 |
| `examples/onvif_sync_demo.py` standalone GStreamer pipeline | Replace with a public-session/synchronizer example; no direct GI pipeline remains | ISSUE-009 |
| `src/ax_devil_rtsp/doctor.py` ad hoc checks | Replace with the read-only capability inventory and report | ISSUE-008 |
| `src/ax_devil_rtsp/setup_workarounds/` runtime environment mutation | Delete mutation paths; retain useful detection only as read-only capability reporting | ISSUE-008 |
| Legacy retriever/client/mixin tests | Delete as each behavior is replaced by pure contract, adapter, controlled-stream, lifecycle, and public-cutover tests | ISSUE-001 through ISSUE-009 |
| Monolithic base dependencies and stale install guidance | Replace with capability-aligned base/optional groups and verified documentation | ISSUE-008 |

Files may move while implementation is in progress, but the final repository must match
the ownership and deletion outcome above; temporary compatibility layers are not an
acceptable final state.

## Approval checklist

Approved ISSUE-001 product choices:

- [x] `StreamSession.start()` owns one private lifecycle/control thread while data callbacks remain direct on GStreamer delivery threads.
- [x] Sessions are one-shot; reconnect/restart means constructing a new session.
- [x] Every selected stream requires its callback at construction.
- [x] H.264 and H.265 Annex-B access units are the complete initial encoded matrix.
- [x] Packed `RGB`, `BGR`, and `GRAY8` are the complete initial NumPy matrix.
- [x] `BorrowedNativeBuffer.gst_buffer` is the only public GStreamer escape hatch.
- [x] Native copies never silently change memory type/pixel format and may fail explicitly.
- [x] Unexpected EOS is terminal failure unless produced by an accepted stop.
- [x] `axis_endpoint()` defers media-selection query rendering to `StreamConfig` so selection has one owner.
- [x] Generated Axis URLs expose only proven address/credential/port/source/resolution/timestamp settings; frame rate, compression, codec, and arbitrary query injection are excluded initially.
- [x] Synchronization stores caller-owned tokens and timing only; it never retains stream data.
