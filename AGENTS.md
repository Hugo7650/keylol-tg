# Repository Guidelines

## Project Structure & Module Organization

`main.py` wires together the bot and scheduler. Keep Telegram and forum integrations in `clients/`, application orchestration in `services/`, and concrete parsing/formatting implementations in `infrastructure/services/`. Core interfaces and structured post value objects belong in `domain/`; legacy/simple data models remain in `models/`. Tests are in `test/`, with captured forum pages and parser manifests under `test/case/`. Design notes and support matrices live in `analysis/`. Runtime state in `data/`, local sessions, and credentials must not be committed.

## Build, Test, and Development Commands

The project requires Python 3.14 and includes a locked `uv` environment.

- `uv sync` installs the exact dependencies from `uv.lock`.
- `uv run python main.py` starts the bot locally.
- `uv run python -m unittest discover -s test -p "test_*.py"` runs the complete test suite.
- `uv run python -m unittest test.test_structured_pipeline` runs one module while iterating.
- `uv run pyright` performs basic type checking using `pyrightconfig.json` (install Pyright separately if unavailable).

## Coding Style & Naming Conventions

Use four-space indentation and standard PEP 8 naming: `snake_case` for modules, functions, and variables; `PascalCase` for classes; and leading underscores for internal helpers. Preserve type annotations, `from __future__ import annotations`, and async boundaries used by network clients. Keep domain objects independent of client or infrastructure details. No formatter or linter is configured, so match surrounding import grouping and line layout; avoid unrelated reformatting.

## Testing Guidelines

Tests use the standard-library `unittest` framework and `unittest.mock`. Name modules `test_<feature>.py`, classes `<Feature>Tests`, and methods `test_<behavior>`. Add focused regression tests for parser, formatter, retry, and rollout changes. Reuse sanitized HTML fixtures in `test/case/`; never place authentication data in fixtures. There is no enforced coverage threshold, but new behavior should cover success, malformed-input, and boundary paths where relevant.

## Commit & Pull Request Guidelines

History is informal and concise (`refactor`, `add test case`) with occasional Conventional Commit subjects. Prefer an imperative, specific subject such as `fix: retry transient forum timeouts` or `test: cover paginated root posts`. Keep commits narrowly scoped. Pull requests should explain behavior changes, list verification commands, link related issues, and call out configuration or fixture changes. Include sample Telegram output when formatting behavior changes.

## Security & Configuration

Copy `.env.example` to `.env` and keep Telegram credentials, forum passwords, session files, and `data/` local. Document any new environment variable in `.env.example` and provide a safe default in configuration code.
