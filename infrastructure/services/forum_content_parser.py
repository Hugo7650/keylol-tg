from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urljoin
from urllib.parse import urlsplit
from urllib.parse import urlunsplit

import lxml.etree as etree

from domain.value_objects import CodeBlockNode
from domain.value_objects import ContentElement
from domain.value_objects import EmbedElement
from domain.value_objects import HiddenBlockNode
from domain.value_objects import ImageElement
from domain.value_objects import LineBreakElement
from domain.value_objects import LinkElement
from domain.value_objects import ParseIssue
from domain.value_objects import ParseResult
from domain.value_objects import PageBreakNode
from domain.value_objects import PostContent
from domain.value_objects import RawThreadData
from domain.value_objects import RootPostFragment
from domain.value_objects import QuoteElement
from domain.value_objects import TextElement
from domain.value_objects import UnknownElement


@dataclass(frozen=True, slots=True)
class _TextStyle:
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strikethrough: bool = False
    superscript: bool = False
    subscript: bool = False

    def evolve(
        self,
        *,
        bold: bool | None = None,
        italic: bool | None = None,
        underline: bool | None = None,
        strikethrough: bool | None = None,
        superscript: bool | None = None,
        subscript: bool | None = None,
    ) -> _TextStyle:
        return _TextStyle(
            bold=self.bold if bold is None else bold,
            italic=self.italic if italic is None else italic,
            underline=self.underline if underline is None else underline,
            strikethrough=self.strikethrough
            if strikethrough is None
            else strikethrough,
            superscript=self.superscript if superscript is None else superscript,
            subscript=self.subscript if subscript is None else subscript,
        )


class KeylolForumContentParser:
    """Parse Keylol root-post HTML into an AST-oriented structured content model."""

    _SKIP_CLASSES = {
        "swi-block",
        "steam-info-wrapper",
        "tip",
        "steam-info-loading",
        "original_text_style1",
        "rnd_ai_pr",
    }

    _CONTROL_TEXTS = {"点击显示", "点击隐藏", "复制代码"}

    def parse(self, raw: RawThreadData) -> ParseResult:
        warnings: list[ParseIssue] = []

        try:
            elements: list[ContentElement] = []
            fragments = self._iter_fragments(raw)
            for index, fragment in enumerate(fragments):
                if index > 0:
                    elements.append(PageBreakNode(page_number=fragment.page_number))
                elements.extend(
                    self._parse_fragment(fragment, raw.metadata.url, warnings)
                )

            if not elements:
                fallback_text = self._collect_text(raw.root_post_html)
                elements.append(
                    UnknownElement(
                        raw_html=raw.root_post_html,
                        text_fallback=fallback_text or "内容为空",
                        label="empty_root_post",
                    )
                )

            elements = self._compact_elements(elements)
            content = PostContent(metadata=raw.metadata, elements=tuple(elements))
            fallback_text = content.to_plain_text()
            return ParseResult(content, fallback_text, tuple(warnings), (), bool(warnings))
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
                        label="root_failure",
                        reason=str(exc),
                    ),
                ),
            )
            return ParseResult(content, content.to_plain_text(), (), (issue,), True)

    def _iter_fragments(self, raw: RawThreadData) -> tuple[RootPostFragment, ...]:
        if raw.fragments:
            return raw.fragments
        return (
            RootPostFragment(
                page_number=1,
                container_kind=raw.container_kind,
                html=raw.root_post_html,
            ),
        )

    def _parse_fragment(
        self,
        fragment: RootPostFragment,
        base_url: str,
        warnings: list[ParseIssue],
    ) -> list[ContentElement]:
        tree = etree.HTML(fragment.html, parser=etree.HTMLParser())
        if tree is None:
            raise ValueError(f"无法解析根帖片段 HTML: page={fragment.page_number}")

        root_element = tree.xpath("//body")[0] if tree.xpath("//body") else tree
        return self._compact_elements(
            self._parse_children(root_element, base_url, warnings, style=_TextStyle())
        )

    def _parse_children(
        self,
        element: etree._Element,
        base_url: str,
        warnings: list[ParseIssue],
        *,
        style: _TextStyle,
    ) -> list[ContentElement]:
        elements: list[ContentElement] = []

        text_node = self._make_text_element(element.text, style=style)
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
                        style=style,
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
                        label=child_tag or "unknown",
                        reason=str(exc),
                    )
                )

            tail_node = self._make_text_element(child.tail, style=style)
            if tail_node:
                elements.append(tail_node)

        return self._compact_elements(elements)

    def _parse_child(
        self,
        child: etree._Element,
        child_tag: str,
        base_url: str,
        warnings: list[ParseIssue],
        *,
        style: _TextStyle,
    ) -> list[ContentElement]:
        if not child_tag:
            return []

        if child_tag == "script":
            script_text = (child.text or "").strip()
            if script_text:
                warnings.append(
                    ParseIssue(
                        code="parser.script_ignored",
                        message="跳过脚本注入内容",
                        context={"snippet": script_text[:120]},
                    )
                )
            return []

        if child_tag == "style":
            return []

        if child_tag == "br":
            return [LineBreakElement()]

        if child_tag in {"table", "ruby"}:
            return [self._make_unsupported(child, child_tag, warnings)]

        if child_tag == "img":
            src = child.get("file") or child.get("zoomfile") or child.get("src") or ""
            src = self._normalize_url(base_url, src)
            if not src or src.startswith("data:") or self._is_decorative_image(src):
                return []
            return [ImageElement(url=src, alt_text=child.get("alt"))]

        if child_tag == "a":
            return self._parse_link(child, base_url, warnings)

        if child_tag == "iframe":
            embed = self._parse_iframe(child, base_url)
            return [embed] if embed else []

        class_attr = child.get("class", "")

        if child_tag == "div" and "blockcode" in class_attr:
            code_block = self._parse_code_block(child)
            return [code_block] if code_block else []

        if child_tag == "div" and "showhide" in class_attr:
            return [self._parse_showhide(child, base_url, warnings)]

        if child_tag == "div" and "sff_collapse" in class_attr:
            return [self._parse_collapse(child, base_url, warnings)]

        if child_tag == "div" and "locked" in class_attr:
            return [
                HiddenBlockNode(
                    hidden_kind="hide",
                    summary=self._clean_summary_text(self._collect_text(child)),
                    children=(),
                    revealed=False,
                )
            ]

        if child_tag == "div" and "quote" in class_attr:
            blockquote = child.xpath("./blockquote")
            target = blockquote[0] if blockquote else child
            children = tuple(self._parse_children(target, base_url, warnings, style=style))
            return [QuoteElement(children=children)] if children else []

        if child_tag == "span" and "bbcode_spoiler" in class_attr:
            return [self._parse_spoiler(child, base_url, warnings)]

        if child_tag == "blockquote":
            children = tuple(self._parse_children(child, base_url, warnings, style=style))
            if not children:
                return []
            return [QuoteElement(children=children)]

        if child_tag in {"strong", "b"}:
            return self._parse_children(
                child,
                base_url,
                warnings,
                style=style.evolve(bold=True),
            )

        if child_tag in {"em", "i"}:
            if "本帖最后由" in self._collect_text(child):
                return []
            return self._parse_children(
                child,
                base_url,
                warnings,
                style=style.evolve(italic=True),
            )

        if child_tag == "u":
            return self._parse_children(
                child,
                base_url,
                warnings,
                style=style.evolve(underline=True),
            )

        if child_tag in {"del", "s"}:
            return self._parse_children(
                child,
                base_url,
                warnings,
                style=style.evolve(strikethrough=True),
            )

        if child_tag == "sup":
            return self._parse_children(
                child,
                base_url,
                warnings,
                style=style.evolve(superscript=True),
            )

        if child_tag == "sub":
            return self._parse_children(
                child,
                base_url,
                warnings,
                style=style.evolve(subscript=True),
            )

        if child_tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            heading_text = self._collect_text(child)
            if not heading_text:
                return []
            return [TextElement(text=heading_text, bold=True), LineBreakElement()]

        if child_tag in {"ul", "ol"}:
            return self._parse_list(child, base_url, warnings)

        if child_tag == "li":
            list_item: list[ContentElement] = [TextElement(text="•")]
            list_item.extend(
                self._parse_children(child, base_url, warnings, style=style)
            )
            if list_item and not isinstance(list_item[-1], LineBreakElement):
                list_item.append(LineBreakElement())
            return list_item

        if child_tag in {"div", "span"}:
            if child_tag == "span" and self._is_auxiliary_steam_info(child):
                return []
            if any(skip_class in class_attr for skip_class in self._SKIP_CLASSES):
                return []
            if self._looks_like_hover_container(child):
                return [self._make_unsupported(child, "hover", warnings)]
            styled = self._apply_style_attributes(style, child.get("style", ""))
            return self._parse_children(child, base_url, warnings, style=styled)

        if child_tag == "p":
            paragraph_children = self._parse_children(
                child,
                base_url,
                warnings,
                style=style,
            )
            if paragraph_children and not isinstance(paragraph_children[-1], LineBreakElement):
                paragraph_children.append(LineBreakElement())
            return paragraph_children

        return self._parse_children(child, base_url, warnings, style=style)

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
                src = image.get("file") or image.get("zoomfile") or image.get("src") or ""
                src = self._normalize_url(base_url, src)
                if (
                    src
                    and not src.startswith("data:")
                    and not self._is_decorative_image(src)
                ):
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

    def _parse_code_block(self, element: etree._Element) -> CodeBlockNode | None:
        code_lines = [
            self._collect_text(item)
            for item in element.xpath(".//ol/li")
            if self._collect_text(item)
        ]
        code = "\n".join(line for line in code_lines if line).strip()
        if not code:
            return None
        return CodeBlockNode(code=code, caption="复制代码")

    def _parse_showhide(
        self,
        element: etree._Element,
        base_url: str,
        warnings: list[ParseIssue],
    ) -> HiddenBlockNode:
        header = element.xpath("./h4")
        if header:
            summary = self._clean_summary_text(self._collect_text(header[0]))
            body_children = self._parse_following_content(
                header[0],
                element,
                base_url,
                warnings,
            )
            return HiddenBlockNode(
                hidden_kind="hide",
                summary=summary,
                children=tuple(body_children),
                revealed=True,
            )

        spoiler = element.xpath('./div[contains(concat(" ", normalize-space(@class), " "), " spoiler ")]')
        if spoiler:
            summary_node = element.xpath("./p")
            summary = self._clean_summary_text(
                self._collect_text(summary_node[0]) if summary_node else "折叠内容"
            )
            body_root = self._clone_without_control_links(spoiler[0])
            body_children = self._parse_children(
                body_root,
                base_url,
                warnings,
                style=_TextStyle(),
            )
            return HiddenBlockNode(
                hidden_kind="collapse",
                summary=summary,
                children=tuple(body_children),
                revealed=False,
            )

        return HiddenBlockNode(
            hidden_kind="hide",
            summary=self._clean_summary_text(self._collect_text(element)),
            children=(),
            revealed=False,
        )

    def _parse_collapse(
        self,
        element: etree._Element,
        base_url: str,
        warnings: list[ParseIssue],
    ) -> HiddenBlockNode:
        title = element.xpath('./div[contains(concat(" ", normalize-space(@class), " "), " sff_collapse_b ")]')
        body = element.xpath('./div[contains(concat(" ", normalize-space(@class), " "), " sff_collapse_d ")]')
        summary = self._clean_summary_text(self._collect_text(title[0])) if title else "折叠内容"
        body_children: tuple[ContentElement, ...] = ()
        if body:
            body_root = self._clone_without_control_links(body[0])
            body_children = tuple(
                self._parse_children(body_root, base_url, warnings, style=_TextStyle())
            )
        return HiddenBlockNode(
            hidden_kind="collapse",
            summary=summary,
            children=body_children,
            revealed=False,
        )

    def _parse_spoiler(
        self,
        element: etree._Element,
        base_url: str,
        warnings: list[ParseIssue],
    ) -> HiddenBlockNode:
        content = element.xpath('./span[contains(concat(" ", normalize-space(@class), " "), " bbcode_spoiler_content ")]')
        target = content[0] if content else element
        children = tuple(
            self._parse_children(target, base_url, warnings, style=_TextStyle())
        )
        return HiddenBlockNode(
            hidden_kind="spoiler",
            summary=None,
            children=children,
            revealed=False,
        )

    def _parse_iframe(self, element: etree._Element, base_url: str) -> EmbedElement | None:
        src = self._normalize_url(base_url, element.get("src") or "")
        if not src:
            return None

        lowered = src.lower()
        if "steam" in lowered:
            src = self._canonicalize_steam_url(src)
            return EmbedElement(provider="steam", url=src, label="Steam")

        if "bilibili" in lowered:
            return EmbedElement(provider="bilibili", url=src, label="Bilibili")

        if "youku" in lowered:
            return EmbedElement(provider="youku", url=src, label="Youku")

        if "countdown" in lowered:
            return EmbedElement(provider="countdown", url=src, label="倒计时")

        if element.get("class") == "html5video":
            return EmbedElement(provider="video", url=src, label="视频")

        return EmbedElement(provider="embed", url=src, label="嵌入内容")

    def _is_auxiliary_steam_info(self, element: etree._Element) -> bool:
        hrefs = [href.lower() for href in element.xpath(".//a/@href") if href]
        if not hrefs:
            return False

        text = self._collect_text(element)
        has_store_entry = any(
            href.startswith("https://store.steampowered.com/app/")
            or href.startswith("https://store.steamchina.com/app/")
            or href.startswith("https://store.steampowered.com/sub/")
            or href.startswith("https://store.steamchina.com/sub/")
            for href in hrefs
        )
        has_support_links = any(
            "steamdb.info" in href
            or "steamcardexchange.net" in href
            or "barter.vg" in href
            or "astats." in href
            or "plugin.php?id=keylol_tags:redirect" in href
            for href in hrefs
        )
        return has_store_entry and has_support_links and (
            "Steam商店" in text or "蒸汽平台商店" in text
        )

    def _canonicalize_steam_url(self, url: str) -> str:
        parsed = urlsplit(url)
        segments = [segment for segment in parsed.path.split("/") if segment]

        if "widget" in segments:
            widget_index = segments.index("widget")
            ids = segments[widget_index + 1 :]
            if len(ids) >= 2 and ids[1].isdigit():
                path = f"/sub/{ids[1]}/"
            elif ids and ids[0].isdigit():
                path = f"/app/{ids[0]}/"
            else:
                path = parsed.path
            return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))

        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))

    def _make_text_element(
        self,
        value: str | None,
        *,
        style: _TextStyle = _TextStyle(),
    ) -> TextElement | None:
        if not value:
            return None

        text = " ".join(value.split())
        if not text:
            return None

        if text in self._CONTROL_TEXTS:
            return None

        return TextElement(
            text=text,
            bold=style.bold,
            italic=style.italic,
            underline=style.underline,
            strikethrough=style.strikethrough,
            superscript=style.superscript,
            subscript=style.subscript,
        )

    def _parse_following_content(
        self,
        marker: etree._Element,
        parent: etree._Element,
        base_url: str,
        warnings: list[ParseIssue],
    ) -> list[ContentElement]:
        children: list[ContentElement] = []
        tail_node = self._make_text_element(marker.tail)
        if tail_node:
            children.append(tail_node)

        collect = False
        for sibling in parent:
            if sibling is marker:
                collect = True
                continue
            if not collect:
                continue
            sibling_tag = sibling.tag.lower() if isinstance(sibling.tag, str) else ""
            children.extend(
                self._parse_child(
                    sibling,
                    sibling_tag,
                    base_url,
                    warnings,
                    style=_TextStyle(),
                )
            )
            tail_node = self._make_text_element(sibling.tail)
            if tail_node:
                children.append(tail_node)

        return self._compact_elements(children)

    def _clone_without_control_links(self, element: etree._Element) -> etree._Element:
        clone = etree.fromstring(etree.tostring(element, encoding="unicode"))
        for link in clone.xpath('.//a[starts-with(@href, "javascript:")]'):
            parent = link.getparent()
            if parent is not None:
                parent.remove(link)
        for node in clone.xpath(".//div"):
            text = self._clean_summary_text(self._collect_text(node))
            if text == "":
                parent = node.getparent()
                if parent is not None:
                    parent.remove(node)
        return clone

    def _parse_list(
        self,
        element: etree._Element,
        base_url: str,
        warnings: list[ParseIssue],
    ) -> list[ContentElement]:
        items: list[ContentElement] = []
        for child in element.xpath("./li"):
            item_children = self._parse_children(
                child,
                base_url,
                warnings,
                style=_TextStyle(),
            )
            if not item_children:
                continue
            items.append(TextElement(text="•"))
            items.extend(item_children)
            if not isinstance(items[-1], LineBreakElement):
                items.append(LineBreakElement())
        return self._compact_elements(items)

    def _apply_style_attributes(self, style: _TextStyle, style_attr: str) -> _TextStyle:
        lowered = style_attr.lower()
        return style.evolve(
            underline=style.underline or "underline" in lowered,
            strikethrough=style.strikethrough or "line-through" in lowered,
            bold=style.bold or "font-weight:bold" in lowered,
            italic=style.italic or "font-style:italic" in lowered,
        )

    def _make_unsupported(
        self,
        element: etree._Element,
        label: str,
        warnings: list[ParseIssue],
    ) -> UnknownElement:
        warnings.append(
            ParseIssue(
                code="parser.unsupported_structure",
                message=f"未完整支持的结构: {label}",
                context={"label": label},
            )
        )
        return UnknownElement(
            raw_html=etree.tostring(element, encoding="unicode"),
            text_fallback=self._collect_text(element),
            label=label,
        )

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

    def _is_decorative_image(self, url: str) -> bool:
        lowered = url.lower()
        return "/static/image/common/bb_" in lowered or lowered.endswith("/none.gif")

    def _looks_like_hover_container(self, element: etree._Element) -> bool:
        class_attr = element.get("class", "")
        return "hover" in class_attr and "bbcode_spoiler" not in class_attr

    def _clean_summary_text(self, value: str) -> str:
        text = value.strip()
        for marker in self._CONTROL_TEXTS:
            text = text.replace(marker, "")
        return " ".join(text.replace(">", " ").split()).strip("，, ")

    def _compact_elements(self, elements: list[ContentElement]) -> list[ContentElement]:
        compacted: list[ContentElement] = []
        for element in elements:
            if isinstance(element, TextElement) and compacted and isinstance(
                compacted[-1], TextElement
            ):
                previous = compacted[-1]
                if previous.marks == element.marks:
                    compacted[-1] = TextElement(
                        text=self._merge_text(previous.text, element.text),
                        bold=previous.bold,
                        italic=previous.italic,
                        underline=previous.underline,
                        strikethrough=previous.strikethrough,
                        superscript=previous.superscript,
                        subscript=previous.subscript,
                    )
                    continue

            if isinstance(element, LineBreakElement) and compacted and isinstance(
                compacted[-1], LineBreakElement
            ):
                if len(compacted) >= 2 and isinstance(compacted[-2], LineBreakElement):
                    continue

            compacted.append(element)

        while compacted and isinstance(compacted[0], LineBreakElement):
            compacted.pop(0)
        while compacted and isinstance(compacted[-1], LineBreakElement):
            compacted.pop()
        return compacted

    def _merge_text(self, left: str, right: str) -> str:
        if not left:
            return right
        if not right:
            return left
        if left.endswith(("\n", " ", "(", "[", "<")):
            return f"{left}{right}"
        if right.startswith((")", "]", ">", ",", ".", "!", "?", ":", ";", "，", "。", "！", "？", "：", "；")):
            return f"{left}{right}"
        return f"{left} {right}"

    def _normalize_url(self, base_url: str, url: str) -> str:
        if not url:
            return ""
        return urljoin(base_url, url)
