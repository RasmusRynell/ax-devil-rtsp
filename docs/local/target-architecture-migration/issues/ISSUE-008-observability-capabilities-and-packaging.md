## Parent

[Target purpose, users, and optimization goals](../../../users-and-optimization-goals.md)

## ID

`ISSUE-008`

## Type

`AFK`

## Status

`draft`

## What to build

Verify and align the operational interfaces shipped at cutover, then make runtime
capability checks, doctor output, package extras, and installation facts agree. Live
session information, failures, events, and statistics remain separate from stream-data
callbacks. Offline doctor reports discovered capability candidates and remediation
without opening a stream or changing the host.

`pyproject.toml` remains the owner of Python distribution metadata. One runtime/system
capability inventory owns GI/GStreamer requirements and consequences; tests verify that
package extras and docs agree with it rather than adding a generated build system.

## Acceptance criteria

- [ ] The cutover's typed session-information/error/statistics interfaces are verified against negotiated caps/formats, stream identity, actual selected decoder/path, lifecycle events, failures, cheap counters, and outstanding retention counts outside stream-data callbacks.
- [ ] Cutover tracing, timing, allocation, and callback statistics are verified as explicit, disabled by default, correctly populated when enabled, and documented with their cost without becoming a telemetry framework.
- [ ] The cutover's ordinary namespaced Python logging is verified to install no handlers, files/directories, formatting, queue listeners, or global levels; no deleted application-logging interface or import path reappears during doctor/capability work.
- [ ] The runtime capability inventory distinguishes minimal RTSP/metadata/encoded, decoded, CPU NumPy, display, controlled-test, and benchmark capabilities plus their missing-path consequences.
- [ ] `static_capabilities_for(config)` returns only requirements knowable without inspecting a supplied URL or assuming a codec. Those requirements are validated before pipeline state change; selected codec/decoder failures discovered during negotiation produce structured `DependencyError`/`NegotiationError` and roll startup back transactionally.
- [ ] Offline doctor reports required failures, optional candidates, degraded-but-usable paths, versions, and remediation. Normal inspection never connects to an endpoint; the actually selected decoder/acceleration remains live session information.
- [ ] Doctor is read-only, does not require test-only GI namespaces, and never installs/reconfigures software, initializes application logging, or prints environment secret values.
- [ ] Automatic workaround/environment mutation paths, including runtime calls to `ensure_safe_environment`, are deleted; useful vulnerability detection may remain only as read-only reporting.
- [ ] Base dependencies are minimal; NumPy, display/OpenCV, test-server, benchmark, and development packages live in accurate optional groups, unused packages are removed, and tests verify metadata/inventory/docs agreement.
- [ ] Wheel smoke tests prove package/public-module imports work without GI and NumPy present, diagnostics represent their absence as findings, and only selected session startup imports/initializes required runtime components.
- [ ] Linux installation guidance states why each external dependency is needed, how to install/verify it, and which capability is unavailable when absent.
- [ ] Doctor human/JSON output, live session information, logs, and negotiation errors exclude usernames, passwords, tokens, raw/encoded URL userinfo, and complete credential-bearing endpoints.
- [ ] Security docs distinguish library-controlled output (always sanitized and tested) from application-enabled process-global `GST_DEBUG` dependency output (not intercepted and potentially sensitive); the library never changes global GStreamer logging to manufacture a guarantee.
- [ ] CI builds wheel/sdist, installs the wheel into clean minimal and optional-capability environments, runs `pip check`, import/CLI/doctor smoke tests, and exercises the controlled stream from the wheel.

## Blocked by

- [ISSUE-007](ISSUE-007-reliable-session-cutover.md)
