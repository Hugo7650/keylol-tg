from __future__ import annotations

from typing import Optional

import lxml.etree as etree

from domain.value_objects import FetchedLatestPostsPage
from models.post import ForumPost


class LatestPostsPageExtractionError(Exception):
    """Raised when the latest-posts page does not contain the expected anchors."""


class KeylolLatestPostsPageExtractor:
    """Extract minimal ForumPost entries from the Keylol latest-posts page."""

    def extract(
        self,
        page: FetchedLatestPostsPage,
        *,
        base_url: str,
        limit: Optional[int] = None,
    ) -> list[ForumPost]:
        tree = etree.HTML(page.html, parser=etree.HTMLParser())
        thread_elements = tree.xpath('//div[@id="forumnew"]/following-sibling::*[1]/tbody')

        if not thread_elements and not tree.xpath('//div[@id="forumnew"]'):
            raise LatestPostsPageExtractionError(
                f"最新帖子页面结构异常: {page.url}"
            )

        posts: list[ForumPost] = []
        normalized_base_url = base_url.rstrip('/')
        for element in thread_elements:
            post = self._extract_post(element, normalized_base_url)
            if post is not None:
                posts.append(post)

        return posts[:limit] if limit is not None else posts

    def _extract_post(
        self,
        element: etree._Element,
        base_url: str,
    ) -> ForumPost | None:
        try:
            title = element.xpath('.//th[@class="common"]/a/text()')[0].strip()
            relative_url = element.xpath('.//th[@class="common"]/a/@href')[0].strip()
            url = f"{base_url}/{relative_url.lstrip('/')}"
            thread_id = int(url.split('t')[-1].split('-')[0])
            author = element.xpath('.//td[@class="by"]/cite/a/text()')[0].strip()
            return ForumPost(
                id=thread_id,
                title=title,
                url=url,
                author=author,
            )
        except (IndexError, ValueError, AttributeError):
            return None