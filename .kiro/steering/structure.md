# Project Structure

## Root Level
- `main.py`: Application entry point and lifecycle orchestration
- `config.py`: Environment-backed configuration
- `pyproject.toml`: Project metadata and dependencies
- `data/`: Runtime data such as sessions, logs, and processed-post caches
- `test/`: Unit and regression fixtures
- `.kiro/`: Internal specs, plans, and steering notes

## Runtime Code

### `clients/`
- `forum_client.py`: Forum authentication, session persistence, and page fetching
- `telegram_client.py`: Telegram delivery and inbound link handling

### `services/`
- `post_service.py`: Polling, single-thread processing, and outbound delivery orchestration
- `post_processing_service.py`: Structured fetch/extract/parse/format pipeline coordinator
- `scheduler.py`: Interval-based job scheduling

### `infrastructure/services/`
- `latest_posts_page_extractor.py`: Extract latest-post summaries from the guide page
- `thread_page_extractor.py`: Extract root-post metadata and HTML from a thread page
- `forum_content_parser.py`: Parse root-post HTML into structured content
- `telegram_formatter.py`: Render `ParseResult` into `TelegramPayload`

### `domain/`
- `value_objects/`: Structured pipeline contracts such as fetched pages, parse results, and Telegram payloads
- `repositories/`: Protocol-style interfaces for pipeline collaborators

### `models/`
- `post.py`: `ForumPost` summary dataclass used for latest-post listings

## Current Direction
- Structured processing is the only production forwarding path.
- `ForumPost` is a minimal summary model, not a lazy loader or formatter.
- Telegram rendering belongs in `TelegramFormatter`, and sending belongs in `TelegramClient`.
- Compatibility adapters, rollout flags, and legacy fallback send paths are no longer part of the runtime design.

## Conventions
- Use async/await for I/O operations.
- Keep transport, extraction, parsing, and rendering concerns separate.
- Prefer typed dataclasses and value objects for application contracts.
- Store runtime data in `data/`.
- Keep bot-facing delivery logic out of forum scraping code.
