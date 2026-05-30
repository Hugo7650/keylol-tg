from __future__ import annotations

from datetime import datetime
from typing import Any

from clients.forum_client import ForumTransportException
from domain.repositories import SyncThreadPageFetcher
from domain.repositories import ThreadContentParser
from domain.repositories import ThreadPageExtractor
from models.post import ForumPost


class LegacyForumPostLoader:
    """Bridge the structured pipeline back into ForumPost-compatible detail loading."""

    def __init__(
        self,
        page_fetcher: SyncThreadPageFetcher,
        page_extractor: ThreadPageExtractor,
        content_parser: ThreadContentParser,
        *,
        base_url: str,
    ):
        self._page_fetcher = page_fetcher
        self._page_extractor = page_extractor
        self._content_parser = content_parser
        self._base_url = base_url.rstrip('/')

    def create_post(
        self,
        thread_id: int,
        *,
        title: str | None = None,
        author: str | None = None,
        url: str | None = None,
    ) -> ForumPost:
        return ForumPost(
            id=thread_id,
            title=title or f"帖子 {thread_id}",
            url=url or f"{self._base_url}/t{thread_id}-1-1",
            author=author or "未知作者",
            details_loader=self.load_post_details,
        )

    def load_post_details(self, thread_id: int) -> dict[str, Any] | None:
        try:
            fetched_page = self._page_fetcher.fetch_thread_page_sync(thread_id)
            raw_thread = self._page_extractor.extract(fetched_page)
            parse_result = self._content_parser.parse(raw_thread)
            metadata = raw_thread.metadata

            return {
                "title": metadata.title,
                "author": metadata.author,
                "content": parse_result.fallback_text,
                "publish_time": metadata.publish_time,
                "images": list(parse_result.content.media_urls()),
                "tags": list(metadata.tags),
            }
        except ForumTransportException:
            raise
        except Exception:
            return {
                "title": f"帖子 {thread_id}",
                "author": "未知作者",
                "content": "",
                "publish_time": datetime.now(),
                "images": [],
                "tags": [],
            }