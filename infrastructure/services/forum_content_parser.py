from __future__ import annotations

from urllib.parse import urljoin

import lxml.etree as etree

from domain.value_objects import ContentElement
from domain.value_objects import EmbedElement
from domain.value_objects import ImageElement
from domain.value_objects import LineBreakElement
from domain.value_objects import LinkElement
from domain.value_objects import ParseIssue
from domain.value_objects import ParseResult
from domain.value_objects import PostContent
from domain.value_objects import RawThreadData
from domain.value_objects import QuoteElement
from domain.value_objects import TextElement
from domain.value_objects import UnknownElement


class KeylolForumContentParser:
    """Parse Keylol root-post HTML into a minimal structured content model."""

    _SKIP_CLASSES = {
        "swi-block",
        "steam-info-wrapper",
        "tip",
        "steam-info-loading",
        "original_text_style1",
        "rnd_ai_pr",
    }

    def parse(self, raw: RawThreadData) -> ParseResult:
        warnings: list[ParseIssue] = []

        try:
            tree = etree.HTML(raw.root_post_html, parser=etree.HTMLParser())
            if tree is None:
                raise ValueError("无法解析根帖 HTML")

            root_element = tree.xpath("//td")[0] if tree.xpath("//td") else tree
            elements = tuple(self._parse_children(root_element, raw.metadata.url, warnings))
            content = PostContent(metadata=raw.metadata, elements=elements)
            fallback_text = content.to_plain_text()
            return ParseResult(
                content=content,
                fallback_text=fallback_text,
                warnings=tuple(warnings),
                used_fallback=bool(warnings),
            )
        except Exception as exc:
            issue = ParseIssue(
                code="parser.root_failure",
                message=str(exc),
                context={
                    "thread_id": raw.metadata.thread_id,
                    "root_post_id": raw.metadata.root_post_id,
                },
            )
            fallback_text = self._collect_text(raw.root_post_html)
            content = PostContent(
                metadata=raw.metadata,
                elements=(
                    UnknownElement(
                        raw_html=raw.root_post_html,
                        text_fallback=fallback_text or "内容解析失败",
                    ),
                ),
            )
            return ParseResult(
                content=content,
                fallback_text=content.to_plain_text(),
                errors=(issue,),
                used_fallback=True,
            )

    def _parse_children(
        self,
        element: etree._Element,
        base_url: str,
        warnings: list[ParseIssue],
        *,
        bold: bool = False,
        italic: bool = False,
    ) -> list[ContentElement]:
        elements: list[ContentElement] = []

        text_node = self._make_text_element(element.text, bold=bold, italic=italic)
        if text_node:
            elements.append(text_node)

        for child in element:
            child_tag = child.tag.lower() if isinstance(child.tag, str) else ""
            try:
                elements.extend(
                    self._parse_child(
                        child,
                        child_tag,
                        base_url,
                        warnings,
                        bold=bold,
                        italic=italic,
                    )
                )
            except Exception as exc:
                warnings.append(
                    ParseIssue(
                        code="parser.child_fallback",
                        message=str(exc),
                        context={"tag": child_tag or "unknown"},
                    )
                )
                elements.append(
                    UnknownElement(
                        raw_html=etree.tostring(child, encoding="unicode"),
                        text_fallback=self._collect_text(child),
                    )
                )

            tail_node = self._make_text_element(child.tail, bold=bold, italic=italic)
            if tail_node:
                elements.append(tail_node)

        return elements

    def _parse_child(
        self,
        child: etree._Element,
        child_tag: str,
        base_url: str,
        warnings: list[ParseIssue],
        *,
        bold: bool,
        italic: bool,
    ) -> list[ContentElement]:
        if not child_tag or child_tag in {"script", "style"}:
            return []

        if child_tag == "br":
            return [LineBreakElement()]

        if child_tag == "img":
            src = child.get("file") or child.get("src") or ""
            src = self._normalize_url(base_url, src)
            if not src or src.startswith("data:"):
                return []
            return [ImageElement(url=src, alt_text=child.get("alt"))]

        if child_tag == "a":
            return self._parse_link(child, base_url, warnings)

        if child_tag == "iframe":
            embed = self._parse_iframe(child, base_url)
            return [embed] if embed else []

        if child_tag == "blockquote":
            children = tuple(self._parse_children(child, base_url, warnings))
            if not children:
                return []
            return [QuoteElement(children=children)]

        if child_tag in {"strong", "b"}:
            return self._parse_children(child, base_url, warnings, bold=True, italic=italic)

        if child_tag in {"em", "i"}:
            if "本帖最后由" in self._collect_text(child):
                return []
            return self._parse_children(child, base_url, warnings, bold=bold, italic=True)

        if child_tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            heading_text = self._collect_text(child)
            if not heading_text:
                return []
            return [TextElement(text=heading_text, bold=True), LineBreakElement()]

        if child_tag in {"div", "span"}:
            class_attr = child.get("class", "")
            if any(skip_class in class_attr for skip_class in self._SKIP_CLASSES):
                return []
            if class_attr == "locked":
                return [TextElement(text="[隐藏内容]")]
            return self._parse_children(child, base_url, warnings, bold=bold, italic=italic)

        if child_tag == "p":
            paragraph_children = self._parse_children(
                child,
                base_url,
                warnings,
                bold=bold,
                italic=italic,
            )
            if paragraph_children and not isinstance(paragraph_children[-1], LineBreakElement):
                paragraph_children.append(LineBreakElement())
            return paragraph_children

        return self._parse_children(child, base_url, warnings, bold=bold, italic=italic)

    def _parse_link(
        self,
        element: etree._Element,
        base_url: str,
        warnings: list[ParseIssue],
    ) -> list[ContentElement]:
        href = (element.get("href") or "").strip()
        link_text = self._collect_text(element)

        if href.startswith("javascript:"):
            return []

        if href.startswith("#"):
            text_node = self._make_text_element(link_text)
            return [text_node] if text_node else []

        href = self._normalize_url(base_url, href)
        if self._looks_like_image_url(href):
            return [ImageElement(url=href, alt_text=link_text or None)]

        if element.xpath(".//img"):
            elements: list[ContentElement] = []
            for image in element.xpath(".//img"):
                src = image.get("file") or image.get("src") or ""
                src = self._normalize_url(base_url, src)
                if src and not src.startswith("data:"):
                    elements.append(ImageElement(url=src, alt_text=image.get("alt")))
            if elements:
                return elements

        if href:
            return [LinkElement(url=href, text=link_text or href)]

        warnings.append(
            ParseIssue(
                code="parser.link_without_href",
                message="检测到缺少 href 的链接元素",
                context={"text": link_text},
            )
        )
        text_node = self._make_text_element(link_text)
        return [text_node] if text_node else []

    def _parse_iframe(self, element: etree._Element, base_url: str) -> EmbedElement | None:
        src = self._normalize_url(base_url, element.get("src") or "")
        if not src:
            return None

        lowered = src.lower()
        if "steam" in lowered:
            if "widget" in src:
                src = src.replace("widget", "app")
            return EmbedElement(provider="steam", url=src, label="Steam")

        if "bilibili" in lowered:
            return EmbedElement(provider="bilibili", url=src, label="Bilibili")

        if "countdown" in lowered:
            return EmbedElement(provider="countdown", url=src, label="倒计时")

        if element.get("class") == "html5video":
            return EmbedElement(provider="video", url=src, label="视频")

        return EmbedElement(provider="embed", url=src, label="嵌入内容")

    def _make_text_element(
        self,
        value: str | None,
        *,
        bold: bool = False,
        italic: bool = False,
    ) -> TextElement | None:
        if not value:
            return None

        text = " ".join(value.split())
        if not text:
            return None

        return TextElement(text=text, bold=bold, italic=italic)

    def _collect_text(self, element_or_html: etree._Element | str) -> str:
        if isinstance(element_or_html, str):
            tree = etree.HTML(element_or_html, parser=etree.HTMLParser())
            if tree is None:
                return ""
            text_nodes = tree.xpath("//text()")
        else:
            text_nodes = element_or_html.xpath(".//text()")

        return " ".join(node.strip() for node in text_nodes if node and node.strip())

    def _looks_like_image_url(self, url: str) -> bool:
        lowered = url.lower()
        return lowered.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp"))

    def _normalize_url(self, base_url: str, url: str) -> str:
        if not url:
            return ""
        return urljoin(base_url, url)
