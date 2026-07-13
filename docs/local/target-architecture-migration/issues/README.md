# Target Architecture Migration Issues

Parent: [Target purpose, users, and optimization goals](../../../users-and-optimization-goals.md)

Interface draft: [Complete public interface](../PUBLIC-INTERFACE.md)

## Intent

These ten issues convert the repository directly to the target design. Backwards
compatibility is not a constraint: replaced exports and implementations are deleted,
not preserved through aliases, shims, or parallel legacy paths.

The sequence first deepens behavior that is already valuable, then builds one complete
streaming model on top, and only then rebuilds operational and user-facing surfaces.
Each AFK issue delivers a complete path that can be verified on its own. The two HITL
issues are explicit decision checkpoints rather than hidden questions inside AFK work.

## Target ownership

```text
public stream session module
├── immutable configuration and credential-safe endpoint module
├── typed delivery values and native-buffer ownership module
├── optional synchronization module
└── one concrete GStreamer adapter
    ├── pipeline construction, pad routing, and session control
    ├── Axis metadata assembly module
    └── bounded frame-timing correlation module
```

There is one concrete GStreamer adapter, so this plan does not introduce a speculative
backend protocol or factory. The useful seams are the public session interface, native
buffer ownership, metadata assembly, and optional synchronization.

## Issue order

1. [ISSUE-001: Implement the approved target contract and deepen proven primitives](ISSUE-001-target-contract-and-primitives.md) — `ready` — HITL approval complete — can start immediately.
2. [ISSUE-002: Deliver metadata through the direct stream session](ISSUE-002-metadata-stream-session.md) — `draft` — AFK — blocked by ISSUE-001.
3. [ISSUE-003: Deliver complete encoded video units](ISSUE-003-encoded-video-delivery.md) — `draft` — AFK — blocked by ISSUE-002.
4. [ISSUE-004: Deliver native decoded video frames](ISSUE-004-native-decoded-video.md) — `draft` — AFK — blocked by ISSUE-003.
5. [ISSUE-005: Add opt-in CPU NumPy frames](ISSUE-005-numpy-video-delivery.md) — `draft` — AFK — blocked by ISSUE-004.
6. [ISSUE-006: Complete independent combined delivery](ISSUE-006-combined-delivery.md) — `draft` — AFK — blocked by ISSUE-002 through ISSUE-005.
7. [ISSUE-007: Harden lifecycle and cut over to the single session](ISSUE-007-reliable-session-cutover.md) — `draft` — AFK — blocked by ISSUE-006.
8. [ISSUE-008: Align observability, capabilities, doctor, and packaging](ISSUE-008-observability-capabilities-and-packaging.md) — `draft` — AFK — blocked by ISSUE-007.
9. [ISSUE-009: Ship synchronization, CLI, examples, and docs](ISSUE-009-sync-cli-examples-and-docs.md) — `draft` — AFK — blocked by ISSUE-008.
10. [ISSUE-010: Establish performance baselines and regression budgets](ISSUE-010-performance-baseline-and-budgets.md) — `draft` — HITL — blocked by ISSUE-009.

## Working rules

- Use `users-and-optimization-goals.md` for product intent, `CONTEXT.md` for domain
  terminology and invariants, `PUBLIC-INTERFACE.md` for the concrete public contract,
  and each issue file for executable implementation and acceptance criteria. A lower
  layer may refine a higher layer only through an explicit documented decision; it must
  not silently contradict it.
- Keep one public streaming model and one owner for each shared concept.
- Preserve proven behavior, not the current mixin, retriever, dictionary-payload, or
  multiprocessing shapes that happen to contain it.
- Do not add an interface at a seam unless real variation requires it.
- Keep the replacement session internal until ISSUE-007 atomically changes public
  exports and deletes the old path; intermediate commits must not publish two models.
- Assign deletion to the first issue whose replacement fully covers the old use case.
- Controlled-stream performance measurements isolate producer and client resources;
  hardware profiles and retained reports never expose endpoints or credentials.

## Definition of done for every implementation issue

- Implement every acceptance item in the issue's owning layer; do not satisfy it through
  a legacy wrapper or by moving the ambiguity into another issue.
- Add focused pure/unit tests first where behavior is GI-independent, adapter tests for
  GStreamer facts, and controlled-stream tests for externally observable behavior.
- Run `ruff check .`, `black --check src tests`, the issue's focused tests, and then
  `USE_REAL_CAMERA=false pytest tests -v --maxfail=1 -rs`. A required controlled test may
  fail with actionable capability guidance when its documented system dependency is
  absent; it must not silently pass by skipping supported behavior in the project CI
  environment.
- Keep real-camera tests opt-in. No issue may require credentials or physical hardware
  for its normal automated completion path.
- Update the public contract, issue text, capability inventory, examples, or install docs
  in the same issue whenever implementation evidence changes an owned fact. Do not leave
  stale names or behavior for a later cleanup issue unless that deferral is explicit here.
- Record the exact verification commands and results in the issue/commit handoff. An AFK
  issue is complete only when its tests and the repository-wide checks pass; HITL issues
  additionally require their stated human approval artifact.

## Explicitly deferred

Audio, recording, restreaming, transcoding, camera discovery, fleet management,
cross-camera scheduling, device configuration, automatic reconnection, semantic scene
object modeling, a separate asyncio or pull client, decoder-vendor policy frameworks,
non-Linux parity work, speculative native rewrites, and optimizations not justified by
ISSUE-010 evidence remain outside this migration.
