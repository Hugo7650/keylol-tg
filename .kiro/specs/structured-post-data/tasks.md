# Implementation Plan

Status updated: 2026-05-30

- [x] 1. Define the new structured-processing contracts
  - Create FetchedThreadPage, RootPostMetadata, RawThreadData, PostContent, ParseIssue, ParseResult, and TelegramPayload.
  - Add a minimal content-element set: TextElement, LinkElement, ImageElement, QuoteElement, EmbedElement, LineBreakElement, and UnknownElement.
  - Add projection helpers for plain text and media URLs.
  - _Requirements: 2.1, 2.2, 2.4, 2.5, 6.1_

- [x] 2. Split thread fetching from HTML extraction
  - Refactor ForumClient so it fetches thread pages and manages authentication/session state only.
  - Introduce a transport-level FetchedThreadPage result and typed fetch/extraction errors with thread context.
  - Remove message-string assembly from ForumClient.
  - _Requirements: 1.1, 1.4, 1.5_

- [x] 3. Implement ThreadPageExtractor
  - Extract title, author, publish_time, root_post_id, tags, canonical URL, and root_post_html from fetched thread pages.
  - Return RawThreadData with validated required metadata.
  - Keep page-structure assumptions localized to the extractor.
  - _Requirements: 1.2, 2.4, 6.3_

- [x] 4. Migrate forum transport from requests to httpx
  - Convert ForumClient thread fetch, login, and session-aware request paths to async methods backed by httpx.AsyncClient.
  - Preserve cookies, headers, timeout behavior, and login-expiry detection during the migration.
  - Keep the scheduler and notification flow working while removing event-loop blocking.
  - _Requirements: 1.3, 5.1_

- [x] 5. Implement the minimal forum content parser
  - Parse root_post_html into the minimal AST with support for text, links, images, quotes, embeds, line breaks, and unknown nodes.
  - Populate ParseResult with fallback_text, warnings, errors, and used_fallback.
  - Degrade malformed elements to TextElement or UnknownElement instead of aborting the parse.
  - _Requirements: 2.1, 2.3, 2.5, 3.1, 3.2, 3.3, 3.4, 3.5_

- [x] 6. Implement TelegramFormatter and TelegramPayload delivery rules
  - Convert ParseResult into TelegramPayload with separate text and media outputs.
  - Keep Telegram-specific escaping, preview, quote, and embed rendering rules inside the formatter.
  - Avoid re-reading raw HTML during rendering.
  - _Requirements: 4.1, 4.2, 4.3, 4.5_

- [x] 7. Create PostProcessingService and a processed-thread result
  - Orchestrate fetch, extract, parse, and format into a single service entry point.
  - Return a ProcessedThread-style result that exposes raw data, parse diagnostics, and TelegramPayload together.
  - Keep the rest of the application insulated from intermediate pipeline details.
  - _Requirements: 1.2, 3.5, 4.5, 5.1_

- [x] 8. Add a legacy compatibility adapter for ForumPost
  - Keep ForumPost.content available as a string projection from structured content or fallback_text.
  - Move lazy loading into a loader or adapter layer instead of keeping transport access inside immutable structured value objects.
  - Deprecate direct Telegram formatting methods on ForumPost.
  - _Requirements: 4.4, 5.1, 5.2, 5.3, 5.5_

- [x] 9. Integrate TelegramPayload into PostService and TelegramClient
  - Update the send flow to consume TelegramPayload instead of calling ForumPost.to_telegram_message directly.
  - Preserve the current end-user behavior while enabling media-aware delivery.
  - Add a side-by-side comparison or feature-flagged rollout path for migration.
  - _Requirements: 4.2, 5.1, 5.4_

- [x] 10. Add regression tests and type-checking for the new pipeline
  - Store golden HTML fixtures from real Keylol threads.
  - Add extractor, parser, formatter, and adapter tests using the typed contracts.
  - Configure pyright or mypy for the new structured-processing modules.
  - _Requirements: 3.4, 6.2, 6.4, 6.5_

- [x] 11. Remove obsolete legacy helpers after verification
  - Delete or simplify the old string-focused parsing helpers in ForumClient once the new path is verified.
  - Remove redundant formatting logic that remains in ForumPost or other legacy call paths.
  - Keep the structured parser contract stable while legacy code is retired.
  - _Requirements: 1.4, 5.5_

## Deferred Work

- A parser plugin system is intentionally deferred until there is a second real parser or forum source.
- A generalized formatter abstraction is intentionally deferred until there is a second delivery target.
- Full reply-tree parsing is intentionally deferred until the bot needs more than the root post.