# Tickets: HTTP Calls Have No Timeout

## Overview

All HTTP calls in the project use `requests` without a timeout, meaning any stalled Adobe or fulfillment endpoint can hang the CLI indefinitely. This work switches from `requests` to `httpx` and adds sensible timeouts at every call site.

**Files affected:**
- `src/adl/api_call.py` — `APICall.send()` (lines 31, 33)
- `src/adl/epub_get.py` — direct `requests.get()` (line 77)
- `tests/test_get.py` — mocks `requests.post`, `requests.get` (lines 61, 112, 165)
- `tests/test_login.py` — mocks `requests.get`, `requests.post` (lines 10, 21, 49)
- `pyproject.toml` — dependency declaration

---

## Ticket 1: Add httpx dependency and verify it replaces requests

**Priority:** P0 — blocks all other work
**Effort:** 15 min

### Description

Add `httpx` to `pyproject.toml` dependencies and remove `requests`. Confirm the project builds and existing tests still fail (they should, since they mock `requests`).

### Acceptance criteria

- [ ] `pyproject.toml` lists `httpx` (pin a recent stable version)
- [ ] `requests` is removed from dependencies
- [ ] `uv sync` succeeds
- [ ] `uv run pytest` runs (tests will fail due to broken mocks — that is expected)

### Notes

- Do not change any source code yet. This ticket only swaps the dependency and confirms the test surface is intact.

---

## Ticket 2: Add timeout to APICall.send() — POST and GET paths

**Priority:** P0
**Effort:** 1 hr

### Description

`APICall.send()` in `src/adl/api_call.py:22-41` calls both `requests.post()` and `requests.get()` without a timeout. Replace the `requests` calls with equivalent `httpx` calls that use a configurable timeout (default: connect=10s, read=30s).

### Acceptance criteria

- [ ] `api_call.py` imports `httpx` instead of `requests`
- [ ] `APICall.send()` passes a timeout tuple `(connect, read)` to both `httpx.post()` and `httpx.get()`
- [ ] Default timeout is reasonable for CLI use (connect=10s, read=30s)
- [ ] A subclass or caller can override the timeout (via a new `timeout` attribute on `APICall`)
- [ ] All 7 subclasses (`FFAuth`, `InitLicense`, `Fulfillment`, `Activate`, `ActivationInit`, `AuthenticationInit`, `SignInDirect`) work without modification

### Tests to write (vertical slices, one at a time)

1. **POST with default timeout** — `FFAuth.call()` succeeds; verify the httpx call was made with the default timeout tuple.
2. **GET with default timeout** — `ActivationInit.call()` succeeds; verify the httpx call was made with the default timeout tuple.
3. **Timeout exception is raised** — server does not respond within connect time; verify `httpx.ConnectTimeout` propagates (do NOT swallow it silently).
4. **Read timeout exception** — server connects but does not send response within read time; verify `httpx.ReadTimeout` propagates.
5. **Non-2xx response** — server returns 401/500; verify `raise_for_status()` equivalent behavior (httpx raises `httpx.HTTPStatusError`).

### Implementation notes

- httpx API differences from requests:
  - `requests.post(url, data=...)` → `httpx.post(url, content=...)` for raw bytes
  - `requests.get(url)` → `httpx.get(url)`
  - `r.text` → `r.text` (same)
  - `r.content` → `r.content` (same)
  - `r.raise_for_status()` → `r.raise_for_status()` (same method name)
  - Timeout: `timeout=(10, 30)` as a tuple (connect, read)

---

## Ticket 3: Add timeout to direct ebook download in epub_get.py

**Priority:** P0
**Effort:** 30 min

### Description

`src/adl/epub_get.py:77` makes a direct `requests.get(ebook_url)` without timeout to download the final epub file. This is the longest-running call (potentially large files) and needs a generous read timeout.

### Acceptance criteria

- [ ] `epub_get.py` imports `httpx` instead of `requests`
- [ ] The download call uses httpx with a timeout appropriate for large file downloads (e.g., connect=10s, read=300s)
- [ ] `r.content` is used to get the binary epub data (unchanged)

### Tests to write

1. **Ebook download with timeout** — `get_ebook()` downloads successfully; verify httpx was called with the expected timeout.
2. **Ebook download timeout** — server stalls during download; verify `httpx.ReadTimeout` propagates.

---

## Ticket 4: Migrate all existing tests to httpx mocks

**Priority:** P1
**Effort:** 1 hr

### Description

All existing tests mock `requests.post` and `requests.get`. These mocks are now broken (Ticket 1). Update them to mock the corresponding httpx calls.

### Files and lines requiring updates

| File | Line(s) | Current mock | New mock target |
|------|---------|-------------|-----------------|
| `tests/test_get.py` | 61 | `patch("requests.post")` | `patch("adl.api_call.httpx.post")` |
| `tests/test_get.py` | 112 | `patch("requests.post")` | `patch("adl.api_call.httpx.post")` |
| `tests/test_get.py` | 165 | `patch("requests.get")` | `patch("adl.epub_get.httpx.get")` |
| `tests/test_login.py` | 10 | `patch("requests.get")` | `patch("adl.api_call.httpx.get")` |
| `tests/test_login.py` | 21 | `patch("requests.get")` | `patch("adl.api_call.httpx.get")` |
| `tests/test_login.py` | 49 | `patch("requests.post")` | `patch("adl.api_call.httpx.post")` |

### Acceptance criteria

- [ ] All 6 mock targets updated to patch `adl.api_call.httpx` or `adl.epub_get.httpx`
- [ ] Mock return values use httpx response objects (or `httpx.mock.MockResponse`)
- [ ] `uv run pytest` passes all tests

### Notes on httpx mocking

httpx provides `httpx.mock.MockResponse` for testing. Replace:
```python
# Before (requests)
mock_request.return_value.status_code = 200
mock_request.return_value.text = "success"

# After (httpx)
mock_request.return_value = httpx.mock.MockResponse(text="success", status_code=200)
```

---

## Ticket 5: Ensure error handling preserves timeout distinction

**Priority:** P1
**Effort:** 30 min

### Description

The current `APICall.send()` catches every exception and returns `None`, losing the distinction between network timeouts, connection errors, and server errors. After switching to httpx, ensure timeout exceptions are not silently swallowed — they should propagate so callers can distinguish "the server never responded" from "the server returned an error."

### Acceptance criteria

- [ ] `httpx.ConnectTimeout` and `httpx.ReadTimeout` propagate to the caller (not swallowed)
- [ ] `httpx.HTTPStatusError` is still handled (existing behavior: parse error from response body)
- [ ] Other `httpx.RequestError` types propagate (connection refused, DNS failure, etc.)
- [ ] The existing `parse()` methods that check for `None` still work when a timeout occurs (they already return fallback values on `None`)

### Tests to write

1. **Timeout propagates from Fulfillment** — `Fulfillment.call()` raises `httpx.ReadTimeout` when the server stalls.
2. **Connection error propagates** — `Activate.call()` raises `httpx.ConnectError` when the host is unreachable.
3. **4xx/5xx still returns None** — server error response does not crash the caller (existing behavior preserved).

---

## Suggested execution order

```
Ticket 1 → Ticket 2 → Ticket 4 → Ticket 3 → Ticket 5
```

1. Swap the dependency (Ticket 1) to confirm the test surface is intact.
2. Implement timeout on `APICall.send()` with tests (Ticket 2).
3. Migrate existing test mocks to httpx (Ticket 4) — this validates Ticket 2 doesn't break anything.
4. Handle the standalone ebook download (Ticket 3).
5. Review and tighten error handling (Ticket 5) — this is the polish pass that ensures timeout vs. server-error distinction is correct.
