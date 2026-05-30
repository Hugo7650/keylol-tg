from __future__ import annotations

from typing import Protocol

from domain.value_objects import FetchedThreadPage
from domain.value_objects import ParseResult
from domain.value_objects import RawThreadData
from domain.value_objects import TelegramPayload


class ThreadPageFetcher(Protocol):
    async def fetch_thread_page(self, thread_id: int) -> FetchedThreadPage:
        """Fetch a thread page from the remote forum."""
        ...


class SyncThreadPageFetcher(Protocol):
    def fetch_thread_page_sync(self, thread_id: int) -> FetchedThreadPage:
        """Fetch a thread page from the remote forum synchronously."""
        ...


class ThreadPageExtractor(Protocol):
    def extract(self, page: FetchedThreadPage) -> RawThreadData:
        """Extract root-post metadata and HTML from a fetched page."""
        ...


class ThreadContentParser(Protocol):
    def parse(self, raw: RawThreadData) -> ParseResult:
        """Parse root-post HTML into a structured content model."""
        ...


class ThreadFormatter(Protocol):
    def format(self, result: ParseResult) -> TelegramPayload:
        """Format parsed thread content for a concrete delivery target."""
        ...
