# Code Review: Improvement Suggestions

Date: 2026-07-03

## Findings

1. Importing `adl` performs filesystem and database work.

   `src/adl/__init__.py:6` constructs `DBData`, `src/adl/__init__.py:8` creates `~/.adl` if needed, and `src/adl/__init__.py:12` loads the SQLite database at import time. This makes normal imports stateful, complicates tests, and can surprise library users or tools that only need metadata. Move this behind an explicit application context or lazy accessor, and let the CLI initialize it.

2. HTTP calls have no timeout.

   `src/adl/api_call.py:27` and `src/adl/api_call.py:29` call `requests.post()` and `requests.get()` without a timeout. A stalled Adobe or fulfillment endpoint can hang the CLI indefinitely. Add a default timeout, expose it as an option if needed, and test timeout handling separately from HTTP status handling.

3. API error handling loses useful failure detail.

   `src/adl/api_call.py:32` catches every exception, logs it, and returns `None`. Callers then often collapse distinct failures into generic falsey results. Prefer narrower exception handling around `requests.RequestException`, return a structured result or raise a project-specific exception, and preserve server response bodies where available.

4. AES decrypt works but obscures the protocol.

   `src/adl/utils.py:55` creates a random IV while decrypting and `src/adl/utils.py:64` discards the first plaintext block. Because the encrypted payload appears to prefix the real IV, this can still produce the expected plaintext after dropping the corrupted first block, but the intent is hard to verify. Use `iv = msg[:16]`, decrypt `msg[16:]`, and remove the slice from the plaintext.

5. Tests rely on manual monkey-patch restore.

   Several tests assign mocks directly to module functions and restore them at the end, for example `tests/test_get.py:39` and `tests/test_get.py:114`. If an assertion fails before restoration, later tests can inherit the mocked state. Prefer `unittest.mock.patch.object()` as a context manager or fixture so cleanup is guaranteed.

6. The `ty` gate is intentionally permissive while typing debt remains.

   `pyproject.toml` configures `ty` to inspect `src` and `tests`, but currently ignores `unresolved-import`, `unresolved-attribute`, `invalid-argument-type`, and `invalid-assignment` so `uv run ty check` can serve as a passing introductory gate. The ignored diagnostics point to real cleanup work: `lxml.etree` import typing, nullable DB/config state, cryptography key type narrowing, and tests assigning deliberately loose mock values. Tighten these areas incrementally, then remove the ignored rules one at a time.

## Suggested Next Steps

1. Split runtime state out of package import and make `adl.cli` responsible for initializing application data.
2. Add request timeout behavior and tests for timeout, non-2xx, and ADEPT error payloads.
3. Replace manual test monkey-patching with scoped patches.
4. Clarify the AES envelope handling with explicit IV extraction and a protocol-focused unit test.
5. Reduce `ty` ignores incrementally until `uv run ty check` passes with the default rule set.
