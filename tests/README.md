# Test Strategy for `tests_new`

This directory contains tests for the RTSP data retriever system, focusing on meaningful, high-value coverage rather than exhaustive or redundant tests.

## Strategy

- **Integration-First:**  
  We use a local GStreamer-based RTSP server (`enhanced_rtsp_server.py`) to run true integration tests. This validates that our retrievers work end-to-end with realistic RTSP streams, including both video and metadata, closely simulating real-world Axis camera behavior.

- **Targeted Unit Tests:**  
  Unit tests are included for logic that benefits from isolated testing—such as error handling, callback dispatch, or edge cases not easily triggered in integration tests. We avoid unit tests for code that is already thoroughly exercised by integration tests.

- **Minimal, High-Value Tests:**  
  We focus on a small number of well-designed tests that:
  - Validate end-to-end data flow (video and metadata) from server to retriever callbacks.
  - Ensure correct process/thread lifecycle management (start, stop, cleanup).
  - Confirm robust error handling and resource cleanup, even on failure.
  - Test context manager usage for automatic resource management.
  - Cover critical logic in isolation where integration tests are insufficient.

- **Why This Approach:**  
  - **Realism:** Integration tests with a real server catch issues that mocks cannot.
  - **Maintainability:** Fewer, more meaningful tests are easier to maintain and understand.
  - **Signal over Noise:** We avoid over-testing or duplicating logic, focusing on what matters most for reliability and correctness.

## Test Types

- **Integration Tests:**  
  - Use the local RTSP server to verify that retrievers receive and process both video and metadata streams as expected.
  - Validate callback invocation, error propagation, and resource cleanup in real scenarios.

- **Unit Tests:**  
  - Target specific logic that is not easily or reliably tested via integration (e.g., error handling, callback dispatch, or edge cases).
  - Avoid duplicating coverage already provided by integration tests.

## Directory Structure

- `/integration` — Integration tests using the local RTSP server to validate end-to-end data flow, callback invocation, and resource management in realistic scenarios.
- `/unit` — Unit tests for isolated logic such as error handling, callback dispatch, or edge cases not easily triggered in integration tests. Avoids duplicating coverage already provided by integration tests.

## Dual-Mode Integration Testing

All integration tests are designed to run in two modes:

- **Local Mode (default):** Uses the local GStreamer RTSP server for end-to-end testing, requiring no real device.
- **Real Device Mode:** If the environment variable `USE_REAL_CAMERA=true` is set, tests use a real RTSP camera, with credentials provided via the `rtsp_credentials` fixture.

The RTSP URL is always provided by a fixture, so tests remain agnostic to the source. If a real device is requested but unavailable, tests must fail (not skip), ensuring true integration coverage.

## Summary

Our goal is to ensure confidence in the retriever system with a minimal, high-signal test suite. We prioritize realistic integration tests using the local RTSP server, and supplement with targeted unit tests only where they add unique value. 