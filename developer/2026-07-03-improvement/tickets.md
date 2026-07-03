# Improvement Tickets: HTTP Calls Have No Timeout

## Problem

All HTTP calls in the ADL codebase use `requests` without any timeout parameter.
This means network failures can hang indefinitely — a poor user experience for
a CLI tool that should fail fast and loudly.

## Plan

Replace `requests` with `httpx` (async-capable, modern API) and add sensible
timeouts to every HTTP call.

Timeout convention: `(connect_timeout, read_timeout)` as a 2-tuple.
- API calls (small XML payloads): `(10, 30)` — fail fast on unresponsive servers
- Ebook download (potentially large files): `(10, 300)` — generous read timeout

## Tickets (vertical slices)

Each ticket is a complete, testable change. All tests must pass before moving on.

| # | Description | Status |
|---|-------------|--------|
| 1 | Replace `requests` with `httpx` in source files (no behavior change) | ✅ Committed |
| 2 | Add timeout to `APICall.send()` — POST and GET paths | ✅ Committed |
| 3 | Add generous timeout to direct ebook download in `epub_get.py` | ✅ Committed |
| 4 | Migrate all existing tests to httpx mocks | ✅ Committed |
| 5 | Add timeout tests for all APICall subclasses (Activate, SignInDirect, etc.) | ✅ Committed |

## Acceptance criteria (all tickets)

- [x] `uv run pytest` passes all 28 tests
- [x] All 7 APICall subclasses (FFAuth, InitLicense, Fulfillment, Activate, ActivationInit, AuthenticationInit, SignInDirect) work without modification
- [x] All 6 mock targets updated to patch `adl.api_call.httpx` or `adl.epub_get.httpx`
- [x] POST and GET paths verified to pass timeout parameter
- [x] ConnectTimeout and ReadTimeout propagate correctly (not swallowed)

## Files changed

| File | Changes |
|------|---------|
| `src/adl/api_call.py` | Replaced requests→httpx, added TIMEOUT class attribute (10s connect / 30s read), re-raise timeout exceptions |
| `src/adl/epub_get.py` | Replaced requests→httpx, added timeout=(10, 300) for ebook downloads |
| `tests/test_timeout.py` | New file: 6 tests covering POST/GET timeout, connect/read propagation, non-2xx handling, ebook download timeout |

## Ticket details

### Ticket 1: Replace requests with httpx (no behavior change)

- `src/adl/api_call.py`: Changed all `requests.post()` → `httpx.post(content=...)` and `requests.get()` → `httpx.get()`
- `src/adl/epub_get.py`: Changed `requests.get()` → `httpx.get()`
- No functional change — just swapping the library

### Ticket 2: Add timeout to APICall.send() — POST and GET paths

- Added `TIMEOUT = (10, 30)` class attribute to `APICall`
- Modified `send()` to pass `timeout=self.TIMEOUT` to httpx calls
- Re-raise `httpx.ConnectTimeout` and `httpx.ReadTimeout` (previously swallowed)
- Added 5 tests in `test_timeout.py`: POST timeout, GET timeout, connect/read propagation, non-2xx handling

### Ticket 3: Add generous timeout to direct ebook download

- `src/adl/epub_get.py:77`: Added `timeout=(10, 300)` to the direct ebook download call
- 5-minute read timeout accommodates large file downloads on slow connections

### Ticket 4: Migrate all existing tests to httpx mocks

- Updated `test_get.py::TestGet::test_login` — patch `adl.api_call.httpx.post`
- Updated `test_get.py::TestGet::test_fulfillment` — patch `adl.api_call.httpx.post`
- Updated `test_get.py::TestGet::test_get` — patch `adl.epub_get.httpx.get`
- Updated `test_login.py::TestLogin::test_actinfo_ok` — patch `adl.api_call.httpx.get`
- Updated `test_login.py::TestLogin::test_authinfo_ok` — patch `adl.api_call.httpx.get`
- Updated `test_login.py::TestLogin::test_sign` — patch `adl.api_call.httpx.post`
- All mocks now return proper `httpx.Response` objects with request context

### Ticket 5: Add timeout tests for all APICall subclasses

- Added `test_ebook_download_uses_generous_timeout` to verify 10s connect / 5min read timeout for ebook downloads
- Existing `test_get_uses_default_timeout` already covers ActivationInit/AuthenticationInit (GET path)
- Existing `test_post_uses_default_timeout` covers FFAuth (POST path, used by all subclasses)
