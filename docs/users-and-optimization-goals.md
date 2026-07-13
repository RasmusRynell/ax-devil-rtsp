# Target Purpose, Users, and Optimization Goals

## Purpose

This document defines the product `ax-devil-rtsp` should become. It is a target
for future design and optimization work, not a description or assessment of an
implementation.

`ax-devil-rtsp` should be a fast, dependable Python library for receiving RTSP
video and Axis scene metadata from Axis devices. It should let application
developers use this data without building and managing their own GStreamer
integration.

The library should remain thin. Python should provide the public API, configure
and connect the streaming components, preserve required metadata, and manage
their lifecycle. Established dependencies should perform heavy work in native
code. The library should not move bulk stream data through Python or reproduce
work already handled efficiently by its dependencies without a user-facing
reason.

## Users and Primary Use Cases

The primary users are Python developers building applications that:

1. display live video with Axis overlays or related scene information; or
2. analyze video and Axis scene metadata using a CPU, GPU, or both.

Applications may consume video and metadata together, video only, or metadata
only. Combined operation must not make either specialized path unnecessarily
expensive.

Applications may also operate one camera or many cameras. The library should
support independent concurrent stream sessions without global state,
unnecessary contention, or one session's failure disrupting the others. The
application remains responsible for collecting and coordinating those sessions.

`ax-devil` is one useful reference consumer and source of feedback. It should
otherwise be treated like any other application, not as the privileged owner of
the library's requirements.

The CLI is a supporting surface. It should demonstrate the public API, showcase
video-metadata synchronization, inspect streams, and run diagnostics. It should
be reasonably efficient, but its display path is not the primary optimization
target.
Its final shape should remain thin: one explicit `stream` command for all fixed session
combinations and one read-only `doctor` command. The root command must not hide a default
stream configuration or preserve the legacy retriever dispatch model.

## Scope

The project should focus on the two primary use cases instead of becoming a
general RTSP media framework.

The following responsibilities remain outside the core:

- audio;
- recording, restreaming, and transcoding as first-class workflows;
- camera discovery and fleet management;
- cross-camera scheduling and application-wide policy;
- device configuration;
- automatic reconnection;
- a general Axis or ONVIF scene-metadata object model.

These boundaries may be reconsidered only when evidence shows that a capability
has become a major use case.

Applications may provide a complete RTSP URL or, when they do not provide one, use
a small, pure Axis endpoint helper together with `StreamConfig` to produce a
Generated Axis URL. `StreamConfig.video` and `StreamConfig.metadata` are the single
source of truth for generated media selection; separate media-enable flags are not
duplicated in the endpoint helper. These are mutually exclusive connection inputs:
a Supplied RTSP URL is used exactly as provided, and helper/device settings are
never merged into it or used to rewrite its query. The library does not inspect a
Supplied RTSP URL to infer or preflight media capabilities; it simply builds the
requested delivery branches and relies on normal runtime negotiation. URL
handling preserves the supplied connection string unchanged and examines only what
is necessary to avoid leaking it through display names, logs, or failures. URL
construction uses the fixed initial Axis scene-metadata selection when metadata is
requested and must not contact or configure the device. Credentials must never leak
through library-generated logs, errors, diagnostics, object representations, or
examples. The library does not take ownership of process-global GStreamer debug output;
documentation must warn that an application enabling verbose `GST_DEBUG` may cause the
dependency itself to print its connection location.
The initial generated helper keeps only the proven address, credentials, port, camera
source, resolution, and timestamp-extension settings. Frame-rate, compression, codec,
and arbitrary query controls remain outside the initial API until a concrete use case
and device behavior justify them.
Generated video enables the existing Axis ONVIF replay timestamp extension by default
to support capture-time correlation, with an explicit opt-out for incompatible devices.

## Optimization Goals

The project should optimize for:

1. **Low overhead.** Avoid unnecessary copies, conversions, serialization,
   allocations, retention, and Python work.
2. **Low achievable latency.** Avoid unnecessary buffering, queueing,
   scheduling, and processing between receiving and delivering data.
3. **Efficient resource use.** Keep CPU time, memory use, memory bandwidth, and
   transfer costs proportionate to the work explicitly requested.
4. **Correct combined delivery.** Preserve the timing and identity information
   needed to relate video frames to Axis scene metadata.
5. **Predictable behavior under load.** Do not allow hidden queues or resource
   use to grow without control.
6. **Reliability.** Keep startup, long-running streaming, error reporting,
   shutdown, and failure cleanup dependable.
7. **Application independence.** Do not optimize around the internal structure
   of one consumer.
8. **Pay-for-what-you-use processing.** Keep decoding, conversion, CPU
   materialization, and similar transformations optional when earlier data is
   useful to the caller.
9. **Simplicity.** Maintain a small, understandable API and codebase that serve
   the major use cases well.

## Stream Configuration and Data Representation

Each session should use one fixed pipeline configuration for its lifetime.
Pipeline-shaping operations must be declared before streaming starts and run
inside the original GStreamer pipeline. Changing them requires stopping and
restarting the stream; live pipeline rebuilding and secondary Python-mediated
conversion paths are outside the target.

RTSP transport should preserve GStreamer's UDP/TCP negotiation by default while allowing
an application to force TCP or UDP for deployment-specific network constraints. Ready
session information should report the transport actually selected.
The initial jitter/latency default is 100 ms for both the Python API and CLI; callers may
override it per fixed session, and later default changes require benchmark/reliability
evidence rather than divergent surface-specific values.
Startup readiness uses one 15-second default across Python and CLI. It covers the full
requested-branch readiness condition, replacing legacy connection-only timeout meanings;
callers may override it per session.

Video delivery should provide two clear modes:

- **Encoded:** GStreamer handles RTSP and reconstructs complete encoded video
  units while preserving timing and stream identity. The application owns any
  later decoding path. The initial supported outcomes are negotiated H.264 and
  H.265; applications do not select or order codecs through the public API.
- **Decoded:** GStreamer selects and runs the decoder, then delivers the native
  decoded frame. The library should not reproduce GStreamer's decoder selection
  with its own CPU, GPU, vendor, or plugin policy framework.

This lets common applications use GStreamer decoding while specialized
applications own a better-suited external path. Decoded mode may optionally
request a common CPU NumPy representation at startup. GStreamer should perform
any required pixel-format conversion, and Python should expose a borrowed NumPy
view whenever safe. Consumers that do not need NumPy must still receive the
native decoded buffer without a Python pixel loop or mandatory defensive copy.
Retaining a NumPy delivery may retain its already-converted packed CPU backing and map a
new scoped view later, but mapping an arbitrary native/GPU frame must never imply hidden
pixel conversion; conversion remains a startup pipeline choice.
Because GStreamer is the sole backend, native/GPU consumers may deliberately access the
wrapped `Gst.Buffer` under the same borrow/retain lifetime. The project should not invent
a lowest-common-denominator native-handle protocol for hypothetical backends.

Video and Axis scene metadata should remain independent at the core boundary,
with enough timing and identity information for callers to relate them without
mandatory synchronization buffering. The metadata callback should receive one
owned `SceneMetadata` value per complete document. Its `xml` field is one strict
UTF-8 Python string, decoded once without retaining duplicate bytes; the value also
carries the stream identity, RTP sequence range, and timing facts needed by callers.
Semantic parsing belongs to the application. A narrow optional synchronization helper
may extract only the timing needed for matching, and the CLI should demonstrate it.

## Callback, Threading, and Ownership Contract

The public lifecycle should be synchronous, with stream data delivered through
scoped callbacks directly on the relevant GStreamer delivery thread. The core
should not add mandatory queues, worker dispatch, thread handoff, pull-based
delivery, a separate `asyncio` client, or event-loop-specific cancellation.

`start()` should return a ready session only after every requested stream has been
discovered, linked, caps-negotiated, and included in a playing pipeline. Readiness
must not wait for the first video frame or metadata document; a startup timeout
must fail and clean up the session.
An explicit stop requested by another thread during startup is normal cancellation:
it should clean up into the stopped state, leave no terminal stream failure, and
unblock the starter with a distinct lifecycle exception because readiness was never
reached.

Callbacks must return promptly because blocking them can stall the stream.
Applications own any event-loop bridge, queue, executor, GUI signal, and choice
to block, drop, or buffer. Different sessions may invoke callbacks concurrently,
so applications must retain data before asynchronous handoff and the threading
contract must be explicit. A callback-safe stop request must be nonblocking; an
external application thread may synchronously wait for session cleanup.

Frame data should be borrowed for the documented callback scope. Callers that
need it afterward must explicitly retain and later release it. Retention should
preserve the native buffer without copying when safe; an explicit copy should
provide independent storage otherwise. Retained buffers still occupy CPU or GPU
memory and may prevent pool reuse, so applications must bound retained data.

If a callback raises, the library should preserve that application exception as
the terminal cause. If the adapter, a dependency, or the camera fails, the library
should instead expose credential-safe structured facts and must neither retain nor
chain the raw third-party exception. Either kind of failure should release that
session's resources and stop its stream without affecting other sessions. The
library should not repeatedly call a failing callback, should schedule callback-failure
cleanup outside the streaming callback, should not reconnect automatically, and
should not own retry or backoff policy.

## API and Repository Design

The project should expose one efficient streaming model rather than parallel
low-level and high-level clients. Pipeline configuration should compose with
narrow synchronization, retention, and copying operations without duplicating
connection or lifecycle behavior.

Small, closed public choices should use enums. Enums are preferable to ambiguous
booleans, unchecked strings, or configuration objects that contain no real
configuration. Richer objects should exist only when a major use case requires
associated values or behavior.

Existing public APIs do not constrain the target design. Deliberate breaking
changes are allowed whenever they produce a cleaner API, simpler ownership, or
more efficient data path. Compatibility aliases, shims, and duplicate legacy
implementations should not be retained.

The repository should use cohesive modules with clear ownership and dependency
direction. Files should be divided when they contain distinct responsibilities,
while closely related behavior should remain together. Structure should make
the data flow and public API easy to trace without unnecessary layers,
abstractions, or tiny modules. Shared concepts should have one obvious owner.

Examples should use the same public API as real applications. Convenience
should come from clear names, focused operations, and documentation rather than
hidden work or a second framework inside the package.

## Platforms and External Dependencies

Linux is the first-class platform for installation, documentation, testing,
correctness, and performance. Other platforms may be supported on a best-effort
basis when their dependencies make that practical, but they should not
complicate or weaken the Linux path.

The project must document:

- required and optional external components;
- why each component is needed;
- how to install it on supported environments;
- how to verify that it is available and compatible; and
- which capability or performance path is unavailable when it is missing.

Executable diagnostics should accompany that guidance, identify missing or
incompatible dependencies, plugins, codecs, and acceleration capabilities,
point to remediation, and expose important performance fallbacks. The library
must not install or reconfigure system components automatically.

## Observability and Logging

Applications should be able to inspect negotiated formats and capabilities,
stream identity and timing, selected dependency paths, lifecycle events,
failures, and existing counters without meaningful extra work. Stream-data
callbacks should remain focused; session information, errors, and optional
statistics should use separate callbacks or small interfaces.

Diagnostics that require extra tracing, timing, or allocation tracking must be
explicitly configurable and disabled by default. The configuration and its cost
must be clear; the project should not become a general telemetry framework.

The library should emit standard Python log records without configuring
application handlers, files, directories, formatting, or global log levels.
Programmatic information should use structured callbacks rather than requiring
applications to parse logs.

## Performance Validation

The lowest-level supported path should add as little avoidable overhead as
practical compared with an equivalent minimal GStreamer pipeline; "fast enough
for Python" is not the target. Reproducible benchmarks should determine whether
a limit comes from Python, a dependency, the device, the network, or library
work. The response should follow the measured cause, potential speedup, and
maintenance cost rather than a blanket language policy.

Benchmark coverage should include:

- overhead relative to an equivalent minimal GStreamer pipeline;
- time to first video and metadata;
- steady-state delivery latency and throughput;
- allocations and copies on important paths;
- CPU and memory use per stream;
- scaling across multiple concurrent streams; and
- the incremental cost of optional decoding, conversion, and synchronization.

Results should record the workload, stream properties, dependency versions,
hardware, and enabled acceleration. Performance-sensitive changes should use
these benchmarks to identify improvements, regressions, and tradeoffs.

Controlled local streams should provide repeatable baselines that isolate
library overhead. Real Axis devices should validate camera behavior, metadata,
timing, network interaction, and acceleration paths. Hardware results must
identify the camera model, firmware, network conditions, and stream
configuration; they validate rather than replace the controlled baseline.
