## Parent

[Target purpose, users, and optimization goals](../../../users-and-optimization-goals.md)

## ID

`ISSUE-010`

## Type

`HITL`

## Status

`draft`

## What to build

Build a reproducible comparison harness, record the first controlled and Axis-device
baseline reports, and approve stable regression budgets. Compare every important library
path with an equivalent minimal GStreamer pipeline under paired workloads. This issue
ends with evidence and approved budgets; measured fixes become separately scoped future
work rather than expanding into an unbounded optimization ticket.

## Acceptance criteria

- [ ] The ISSUE-006/009 controlled stream is performance-hardened with an explicit readiness signal and configurable resolution, frame/metadata rate, payload size, duration, and session count; the baseline codec is fixed and recorded.
- [ ] Producer/server execution is isolated in a separate process or its resources are otherwise separately attributed, so client CPU/RSS and time-to-first results do not include fixture work.
- [ ] Minimal-GStreamer and library consumers use paired runs with identical source, pipeline-shaping elements, appsink settings, callback work, warmup, duration, and a defined shared clock/sequence for latency correlation.
- [ ] The matrix covers metadata-only, encoded-only, native decoded, NumPy decoded, combined, combined+synchronization, and one versus several sessions.
- [ ] Reports cover first delivery, steady latency/throughput, CPU, RSS/memory growth, allocations, copies, retention/pool pressure, and drops; every metric records source, units, scope, and measured/inferred/unavailable provenance.
- [ ] Reports include workload/stream properties, package/dependency/plugin versions, hardware/OS, selected decoder/acceleration, repetitions, variance, and harness version as JSON plus readable Markdown.
- [ ] Benchmark commands, logs, JSON/Markdown, CI artifacts, and hardware profiles sanitize usernames, passwords, tokens, userinfo, and complete credential-bearing endpoints.
- [ ] An opt-in Axis run records camera model, firmware, network conditions, stream configuration, and acceleration; hardware validates but does not replace the controlled baseline.
- [ ] Human review approves the baseline and chooses per-metric relative budgets only where variance is stable; noisy metrics remain informational with the decision recorded.
- [ ] Numeric gates run only on a pinned/self-hosted or otherwise demonstrated-stable environment; ordinary hosted CI runs harness correctness smoke and retains informational reports.
- [ ] The issue records measured bottlenecks and proposes bounded follow-up work, but implements no speculative rewrite or unrelated optimization.

## Blocked by

- [ISSUE-009](ISSUE-009-sync-cli-examples-and-docs.md)
