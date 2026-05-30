from __future__ import annotations

from datetime import datetime

import lxml.etree as etree

from domain.value_objects import FetchedThreadPage
from domain.value_objects import RawThreadData
from domain.value_objects import RootPostMetadata


class ThreadPageExtractionError(ValueError):
    """Raised when a thread page cannot be reduced to root-post data."""


class KeylolThreadPageExtractor:
    """Extract page-level metadata and root-post HTML from a fetched Keylol thread."""

    def extract(self, page: FetchedThreadPage) -> RawThreadData:
        tree = etree.HTML(page.html, parser=etree.HTMLParser())
        if tree is None:
            raise ThreadPageExtractionError(
                f"无法解析帖子页面 HTML: thread_id={page.thread_id}"
            )

        try:
            post_element = tree.xpath('//div[@id="postlist"]/div[contains(@id, "post_")]')[0]
            post_id = int(post_element.xpath('./@id')[0].split('_')[-1])
            post_message = post_element.xpath(f'.//td[@id="postmessage_{post_id}"]')[0]
        except (IndexError, ValueError) as exc:
            raise ThreadPageExtractionError(
                f"缺少根帖锚点，无法抽取 thread_id={page.thread_id}"
            ) from exc

        title = self._extract_title(tree)
        author = self._extract_author(post_element)
        publish_time_raw = self._extract_publish_time_raw(post_element, post_id)
        publish_time = self._parse_time(publish_time_raw)
        tags = tuple(self._extract_tags(post_message))
        post_html = etree.tostring(post_message, encoding="unicode")

        metadata = RootPostMetadata(
            thread_id=page.thread_id,
            root_post_id=post_id,
            title=title,
            author=author,
            publish_time=publish_time,
            url=page.url,
            tags=tags,
            forum_extra={"publish_time_raw": publish_time_raw},
        )
        return RawThreadData(
            metadata=metadata,
            root_post_html=post_html,
            page_html=page.html,
        )

    def _extract_title(self, tree: etree._Element) -> str:
        title_elements = tree.xpath('//a[@id="thread_subject"]')
        if title_elements and title_elements[0].text:
            title = title_elements[0].text.strip()
            if title:
                return title
        return "未知标题"

    def _extract_author(self, post_element: etree._Element) -> str:
        author_elements = post_element.xpath('.//td[@class="pls"]//a[@class="xw1"]')
        if author_elements and author_elements[0].text:
            author = author_elements[0].text.strip()
            if author:
                return author
        return "未知作者"

    def _extract_publish_time_raw(
        self, post_element: etree._Element, post_id: int
    ) -> str:
        publish_times = post_element.xpath(f'.//em[@id="authorposton{post_id}"]/span/@title')
        if not publish_times:
            return ""
        return publish_times[0].strip()

    def _extract_tags(self, message_element: etree._Element) -> list[str]:
        tags: list[str] = []
        tag_elements = message_element.xpath(
            './/span[@class="tag"] | .//a[contains(@class, "tag")]'
        )
        for tag_element in tag_elements:
            tag_text = tag_element.text or ""
            tag_text = tag_text.strip()
            if tag_text:
                tags.append(tag_text)
        return tags

    def _parse_time(self, time_str: str) -> datetime:
        if not time_str:
            return datetime.now()

        try:
            return datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return datetime.now()
