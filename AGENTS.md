# AGENTS.md

This file is for human developers and coding agents working on ADL.

## Project Layout

- `src/adl/` contains the runtime package.
- `tests/` contains the pytest suite and fixtures.
- `README.md` is user-facing documentation.
- `developer/` contains developer notes and reviews.

## Tooling

Use `uv` for dependency management and command execution.

Common commands:

```sh
uv sync
uv run ruff format
uv run ruff check --fix
uv run ty check
uv run pytest
```

Before committing, all of these gates must pass:

```sh
uv run ruff format
uv run ruff check --fix
uv run ty check
uv run pytest
```

`ruff` and `ty` are configured to inspect `src` and `tests` by default.

## Development Notes

- Keep user documentation in `README.md`; keep maintainer and agent workflow notes here.
- Preserve the command-line entry point: `uv run adl`.
- The package currently initializes application data at import time. Be careful when changing imports or test setup.
- Do not reintroduce direct `libcrypto` loading through `ctypes`; use `cryptography` APIs instead.
- Tests include fixture paths under `tests/files` and `tests/fake_device`.
