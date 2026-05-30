# Requirements Document

## Introduction

This feature restructures Keylol thread processing into an incremental pipeline that separates fetching, extraction, parsing, and Telegram rendering. The first iteration must improve maintainability without breaking the bot's current behavior or introducing abstractions that the codebase does not yet need.

## Scope Clarification

- Phase 1 processes a thread page and its root post, because the current bot consumes thread links and forwards the first post.
- The system must preserve today's externally visible behavior while enabling structured content internally.
- Cross-forum plugins, multi-platform delivery frameworks, and full reply-tree parsing are out of scope for phase 1.

## Requirements

### Requirement 1

**User Story:** As a maintainer, I want clear fetching and extraction boundaries, so that transport code, HTML extraction, and formatting logic can evolve independently.

#### Acceptance Criteria

1. WHEN a thread is loaded THEN ForumClient SHALL be responsible only for authentication, HTTP retrieval, and session management.
2. WHEN thread HTML is parsed THEN page metadata extraction and root post HTML extraction SHALL happen outside ForumClient in a dedicated extractor component.
3. WHEN the async bot workflow fetches forum pages THEN ForumClient SHALL use an async HTTP client based on httpx and SHALL avoid blocking the event loop.
4. WHEN post data moves to processing layers THEN ForumClient SHALL not contain Telegram formatting logic or message-string assembly.
5. WHEN fetching or extraction fails THEN the system SHALL surface structured failure information tied to the current thread ID or URL.

### Requirement 2

**User Story:** As a developer, I want a typed structured content model, so that the system preserves semantics without flattening everything into a string too early.

#### Acceptance Criteria

1. WHEN the root post is parsed THEN the system SHALL produce a typed PostContent object instead of a plain string.
2. WHEN element order matters THEN the structured model SHALL preserve the original source order.
3. WHEN formatting is present THEN the model SHALL preserve at least bold text, italic text, links, quotes, line breaks, and embedded media references.
4. WHEN metadata is stored THEN the model SHALL represent thread_id and root_post_id explicitly and SHALL not blur thread-level and post-level identifiers.
5. WHEN unknown HTML structures are encountered THEN the model SHALL preserve recoverable information through UnknownElement or an equivalent fallback node.

### Requirement 3

**User Story:** As a developer, I want a stable parser contract with graceful fallback behavior, so that malformed or unexpected forum markup does not break delivery.

#### Acceptance Criteria

1. WHEN content parsing runs THEN the parser SHALL return a ParseResult contract that includes structured content, warnings, errors, and a fallback indicator.
2. WHEN a single element fails to parse THEN the parser SHALL degrade that element to text or unknown content instead of aborting the whole parse.
3. WHEN a full structured parse fails THEN the system SHALL still produce a plain-text fallback suitable for delivery.
4. WHEN parser issues are recorded THEN each issue SHALL include a stable code and enough context for debugging.
5. WHEN processing succeeds with warnings THEN downstream formatters SHALL still be able to render the content.

### Requirement 4

**User Story:** As an integrator, I want rendering to produce a typed delivery payload, so that Telegram-specific behavior does not leak back into domain models or forum scraping code.

#### Acceptance Criteria

1. WHEN content is formatted for Telegram THEN the formatter SHALL return a typed delivery payload instead of a bare string.
2. WHEN a post contains media references THEN the delivery payload SHALL expose text and media separately.
3. WHEN rendering rules change THEN Telegram formatting logic SHALL remain outside ForumPost and ForumClient.
4. WHEN the current bot flow still expects a string message THEN the system SHALL provide a migration adapter.
5. WHEN additional output channels are introduced later THEN they SHALL consume the same structured content contract.

### Requirement 5

**User Story:** As a maintainer, I want migration-safe backward compatibility, so that the refactor can ship incrementally without forcing a flag day rewrite.

#### Acceptance Criteria

1. WHEN the refactor is introduced THEN existing post forwarding behavior SHALL remain available during migration.
2. WHEN legacy code accesses ForumPost.content THEN the system SHALL continue to provide a string view derived from structured content or fallback text.
3. WHEN lazy loading is retained THEN it SHALL live in a loader or adapter layer, not inside immutable value objects.
4. WHEN the new structured pipeline is enabled THEN rollout SHALL allow side-by-side comparison with the legacy output path.
5. WHEN migration is complete THEN legacy formatting code SHALL be removable without changing the structured parser contract.

### Requirement 6

**User Story:** As a developer, I want typed contracts, validation, and regression tests, so that new structured-processing code can be changed safely.

#### Acceptance Criteria

1. WHEN structured content types are defined THEN they SHALL use explicit Python type annotations and immutable data objects where practical.
2. WHEN static type safety is required THEN the project SHALL define and run a type-checking tool such as pyright or mypy for the new modules.
3. WHEN required fields are missing or malformed THEN runtime validation SHALL produce clear errors.
4. WHEN parsing and formatting components are tested THEN tests SHALL use the same typed contracts as production code.
5. WHEN regressions are checked THEN the test suite SHALL include golden samples derived from real forum HTML fragments.