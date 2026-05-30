from __future__ import annotations

from domain.repositories import ThreadContentParser
from domain.repositories import ThreadFormatter
from domain.repositories import ThreadPageExtractor
from domain.repositories import ThreadPageFetcher
from domain.value_objects import ProcessedThread


class PostProcessingService:
    """Coordinate the structured thread-processing pipeline."""

    def __init__(
        self,
        page_fetcher: ThreadPageFetcher,
        page_extractor: ThreadPageExtractor,
        content_parser: ThreadContentParser,
        formatter: ThreadFormatter,
    ):
        self._page_fetcher = page_fetcher
        self._page_extractor = page_extractor
        self._content_parser = content_parser
        self._formatter = formatter

    async def process_thread(self, thread_id: int) -> ProcessedThread:
        page = await self._page_fetcher.fetch_thread_page(thread_id)
        raw = self._page_extractor.extract(page)
        parse_result = self._content_parser.parse(raw)
        telegram_payload = self._formatter.format(parse_result)
        return ProcessedThread(
            raw=raw,
            parse_result=parse_result,
            telegram_payload=telegram_payload,
        )
