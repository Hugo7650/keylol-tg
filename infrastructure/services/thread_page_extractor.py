from __future__ import annotations

from copy import deepcopy
from datetime import datetime

import lxml.etree as etree

from domain.value_objects import FetchedThreadPage
from domain.value_objects import RawThreadData
from domain.value_objects import RootPostFragment
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
            post_element, post_id = self._extract_post_anchor(tree)
            post_message = self._extract_post_content(post_element, post_id)
        except (IndexError, ValueError) as exc:
            raise ThreadPageExtractionError(
                f"缺少根帖锚点，无法抽取 thread_id={page.thread_id}"
            ) from exc

        title = self._extract_title(tree)
        author = self._extract_author(post_element)
        publish_time_raw = self._extract_publish_time_raw(post_element, post_id)
        publish_time = self._parse_time(publish_time_raw)
        tags = tuple(self._extract_tags(post_message))
        container_kind = self._detect_container_kind(post_message)
        fragments = self._extract_fragments(post_message, container_kind)
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
            container_kind=container_kind,
            fragments=fragments,
        )

    def _extract_title(self, tree: etree._Element) -> str:
        title_elements = tree.xpath('//a[@id="thread_subject"]')
        if title_elements and title_elements[0].text:
            title = title_elements[0].text.strip()
            if title:
                return title
        return "未知标题"

    def _extract_post_anchor(self, tree: etree._Element) -> tuple[etree._Element, int]:
        post_elements = tree.xpath('//div[@id="postlist"]/div[starts-with(@id, "post_")]')
        if post_elements:
            post_element = post_elements[0]
            post_id = int(post_element.xpath('./@id')[0].split('_')[-1])
            return post_element, post_id

        post_tables = tree.xpath('//table[starts-with(@id, "pid")]')
        if post_tables:
            post_element = post_tables[0]
            post_id = int(post_element.xpath('./@id')[0].replace('pid', ''))
            return post_element, post_id

        raise IndexError("missing root post anchor")

    def _extract_post_content(
        self,
        post_element: etree._Element,
        post_id: int,
    ) -> etree._Element:
        content_nodes = post_element.xpath(
            f'.//*[@id="postmessage_{post_id}" or @id="postpw_{post_id}"]'
        )
        if not content_nodes:
            raise IndexError("missing root post content")
        return content_nodes[0]

    def _detect_container_kind(self, message_element: etree._Element) -> str:
        element_id = message_element.get("id", "")
        if element_id.startswith("postpw_"):
            return "postpw"
        return "postmessage"

    def _extract_fragments(
        self,
        message_element: etree._Element,
        base_container_kind: str,
    ) -> tuple[RootPostFragment, ...]:
        base_fragment = deepcopy(message_element)
        for node in base_fragment.xpath(
            './div[contains(concat(" ", normalize-space(@class), " "), " keylol-page-break ")]'
            ' | ./div[contains(concat(" ", normalize-space(@class), " "), " keylol-page-fragment ")]'
        ):
            parent = node.getparent()
            if parent is not None:
                parent.remove(node)

        fragments = [
            RootPostFragment(
                page_number=1,
                container_kind=base_container_kind,
                html=self._serialize_inner_html(base_fragment),
            )
        ]

        for wrapper in message_element.xpath(
            './div[contains(concat(" ", normalize-space(@class), " "), " keylol-page-fragment ")]'
        ):
            page_number = self._parse_page_number(wrapper.get("data-keylol-cp"))
            if page_number is None:
                continue

            fragments.append(
                RootPostFragment(
                    page_number=page_number,
                    container_kind=wrapper.get("data-keylol-container-kind")
                    or base_container_kind,
                    html=self._serialize_inner_html(wrapper),
                )
            )

        return tuple(
            fragment
            for fragment in fragments
            if fragment.page_number == 1 or fragment.html.strip()
        )

    def _serialize_inner_html(self, element: etree._Element) -> str:
        parts: list[str] = []
        if element.text:
            parts.append(element.text)
        for child in element:
            parts.append(etree.tostring(child, encoding="unicode"))
        return "".join(parts).strip()

    def _parse_page_number(self, raw_value: str | None) -> int | None:
        if not raw_value:
            return None
        try:
            page_number = int(raw_value)
        except ValueError:
            return None
        return page_number if page_number > 1 else None

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
