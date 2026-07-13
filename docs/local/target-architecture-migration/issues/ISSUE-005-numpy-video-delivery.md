## Parent

[Target purpose, users, and optimization goals](../../../users-and-optimization-goals.md)

## ID

`ISSUE-005`

## Type

`AFK`

## Status

`draft`

## What to build

Add the opt-in decoded CPU NumPy representation without changing native decoded
delivery. The startup configuration asks GStreamer to convert to one of the small packed
CPU formats approved in ISSUE-001, then maps the native buffer for the callback and
exposes a borrowed NumPy view when safe.

This slice owns runtime conversion/mapping behavior only. Package extras and installation
metadata are aligned later in ISSUE-008.

## Acceptance criteria

- [ ] NumPy delivery is an explicit startup choice; metadata, encoded, and native decoded paths do not import NumPy or perform its mapping/conversion work.
- [ ] Package/public-module imports and construction of non-NumPy configurations succeed when NumPy is absent. Selecting NumPy mode remains pure at configuration time and produces a structured missing capability/dependency result before pipeline state change at startup.
- [ ] Pixel-format conversion occurs in the original GStreamer pipeline, not in Python loops, OpenCV, or a post-callback path.
- [ ] `NumpyVideoFormat` shape and row stride/padding come from negotiated `GstVideo` metadata for the approved packed format matrix; unsupported planar/vendor layouts fail clearly rather than expanding into a general format framework.
- [ ] RGB/BGR are read-only `uint8` `(height, width, 3)` SystemMemory views with `(row_stride, 3, 1)` byte strides; GRAY8 is `(height, width)` with `(row_stride, 1)`. Borrowed padding is preserved, while explicit copies are writable C-contiguous arrays.
- [ ] The borrowed NumPy view shares mapped storage for the full callback and is always unmapped afterward, including when the callback raises.
- [ ] A regression test proves the view remains mapped and valid throughout the callback and is unmapped in its `finally` path afterward, fixing the current unmap-before-callback bug. Post-callback access through `NumpyFrame` fails detectably; a raw ndarray alias cannot be revoked and is documented/tested only as contractually invalid.
- [ ] Explicit copying returns independent CPU storage. `NumpyFrame.retain()` instead retains the already-converted CPU backing and `RetainedNumpyFrame.map_array()` creates a new explicitly scoped read-only view with no conversion; arbitrary native/GPU buffers expose no NumPy mapping method.
- [ ] Optional conversion preserves frame timing, stream identity, and negotiated format/dimensions.
- [ ] Controlled-stream tests cover each approved CPU format, non-tight row stride, copy lifetime, callback failure, and the absence of NumPy work on native paths.

## Blocked by

- [ISSUE-004](ISSUE-004-native-decoded-video.md)
