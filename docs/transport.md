# RTSP transport ownership

`RtspConnection` owns RTSP request serialization, authentication state, SDP and
RTSP response parsing, and interleaved packet framing. It creates one private
`_transport.Transport(url, timeout, verify_tls=...)`, regardless of URL scheme.
The transport owns endpoint validation/default ports, socket options, TLS,
HTTP authentication and negotiation, base64 request encoding, and all readers
and sockets. HTTP-specific machinery lives entirely in `_transport.py`.

The interface has four operations:

- `connect()` returns a borrowed buffered binary reader positioned at the first
  RTSP byte, whether backed by TCP or an HTTP GET body. RTSP reads it directly;
  buffering and read ownership remain with the transport.
- `sendall(message)` sends one complete RTSP message, encoding it for HTTP when
  needed. RTSP retains its send lock and nonce accounting for keepalives.
- `shutdown()` remembers cancellation and shuts down every registered socket.
  It can run from another thread during setup or I/O and never waits for a send
  lock, reader lock, or protocol exchange. No TEARDOWN is sent.
- `close()` releases the owned readers and sockets after I/O threads stop.
  Failed `connect()` calls also release partially opened resources. Repeated
  close/shutdown calls are safe.

There is no transport plugin protocol, adapter hierarchy, or new public API.
The buffered reader keeps RTSP parsing direct without duplicating `read`,
`readline`, and header parsing wrappers. `_auth.py` owns the existing shared
Basic/Digest calculations; HTTP and RTSP retain independent challenge/nonce
state. `_errors.py` owns `StreamError`, still exported from `ax_devil_rtsp`.
Neither shared module imports RTSP or the transport, avoiding circular imports.

A stop that races with DNS/TCP establishment is remembered and checked when
`socket.create_connection` returns. That call itself cannot be interrupted by
this transport; TCP uses the configured timeout and DNS resolution can take
longer. Registered sockets can be interrupted during TLS handshake, HTTP
headers, RTSP startup, streaming, and writes. The session still joins its
keepalive sender before closing the transport.

## Preserved HTTP limits

HTTP uses paired HTTP/1.0 GET and POST connections sharing a random cookie.
Responses/media arrive as raw RTSP bytes on GET; whole outbound RTSP messages
are base64-encoded on POST. HTTPS verifies certificates by default.

- Chunked GET responses are rejected; no chunk decoder is provided.
- Redirects are rejected as non-200 responses; no redirects are followed.
- POST advertises `Content-Length: 32767`. There is no accounting, renewal or
  rollover when encoded request bytes reach that length. Servers may terminate
  long-running sessions at that point.
- POST response negotiation and independent POST authentication retries are
  not implemented; GET's accepted challenge is used for POST.

This refactor does not expand these protocol capabilities.

## Validation and integration

Based on PR #29 head `8ed6efe330bfcc0dd1e0e2463a32fa2cd97143ab`.
The refactor commit can be cherry-picked onto an integration branch containing
that commit (or equivalent PR #29 content). Review the delta against that head,
not against main. Existing PR branches are not changed.

PR #30's URL-builder/CLI work is independent. This change does not modify
`url.py`, CLI options, or URL-building behavior. The sole CLI source edit moves
the `StreamError` import to its owning module. When combining with #30, retain
that import alongside #30's options and keep the tunnel-limits README paragraph
alongside its URL documentation. No combined #30 validation was performed here.

Validation used Python 3.14.8, PyAV 19.0.2, NumPy 2.5.4, and local fake cameras:

```sh
pytest -q
ruff check .
mypy
```

All 106 tests passed; Ruff and strict mypy passed. Coverage includes TCP and
HTTP/HTTPS streaming, Basic/Digest authentication and nonce rotation, trusted
and rejected TLS certificates, H.264/H.265 decoding, metadata and capture
timestamps, existing callback/lifecycle tests, and startup cancellation during
TCP RTSP reads, HTTP GET headers and TLS handshake. Focused transport tests
exercise wire bytes, default ports, rejected HTTP responses, partial setup
failures, and resource cleanup. No physical-camera or long-duration validation
was performed.
