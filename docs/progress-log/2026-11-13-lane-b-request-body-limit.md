### 2026-11-13 — Lane B: a request body cap for every API route

- Found reviewing lane A's #495: nothing capped request bodies. FastAPI reads and parses a JSON
  body completely before the route and its dependencies run, so per-route Content-Length checks
  capped nothing, and a chunked request declares no length.
- `app/core/body_limit.py`: an ASGI middleware (innermost, so the 413 still carries the request
  ID and security headers) counts the bytes received; 1 MiB by default, a declared length over it
  refused before reading, a chunked body stopped at the first chunk past it. 413
  `payload_too_large` with `max_bytes`, an existing labelled code.
- The four streaming routes raise their own cap with `body_limit(n)` (files 100 MB + 64 KiB,
  people imports 5 MB, asset imports 25 MB, checklist imports 5 MB; their own exact checks stay).
  `STREAMED` lists their paths so a declared length waits for the route's cap; a guard test fails
  when a raised cap and the list disagree.
- docs/deployment.md: "Request size", for a proxy in front.
- Tests: tests/test_body_limit.py (6).
