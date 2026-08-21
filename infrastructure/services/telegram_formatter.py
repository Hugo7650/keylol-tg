from __future__ import annotations

from html import escape
from html import unescape
import re
from urllib.parse import unquote
from urllib.parse import urlsplit

import httpx
import lxml.etree as etree

from domain.value_objects import CodeBlockNode
from domain.value_objects import ContentElement
from domain.value_objects import EmbedNode
from domain.value_objects import HiddenBlockNode
from domain.value_objects import ImageNode
from domain.value_objects import LineBreakElement
from domain.value_objects import LinkNode
from domain.value_objects import ParseResult
from domain.value_objects import PageBreakNode
from domain.value_objects import QuoteNode
from domain.value_objects import TelegramPayload
from domain.value_objects import TextNode
from domain.value_objects import UnknownElement
from models.post import ForumPost


class TelegramFormatter:
    """Format structured thread content into Telegram HTML messages."""

    _MAX_MESSAGE_LENGTH = 4096
    _MAX_EXPANDABLE_SEGMENT_PLAIN_LENGTH = 300
    _TRUNCATION_SUFFIX = "…"

    _INLINE_BREAKING_NODES = (
        CodeBlockNode,
        HiddenBlockNode,
        PageBreakNode,
        QuoteNode,
        UnknownElement,
    )

    def __init__(self, *, steam_title_timeout: float = 5.0):
        self._steam_title_timeout = steam_title_timeout
        self._steam_label_cache: dict[str, str] = {}

    def format(self, result: ParseResult) -> TelegramPayload:
        metadata = result.content.metadata
        header_lines = [
            f"<b>{escape(metadata.title)}</b>",
            f"{escape(metadata.author)} \\ {metadata.publish_time.strftime('%Y-%m-%d %H:%M')}",
        ]

        if metadata.tags:
            header_lines.append(f"标签: {escape(', '.join(metadata.tags))}")

        body = self._render_elements(
            result.content.elements,
            thread_title=metadata.title,
        )
        footer_line = f'<a href="{escape(metadata.url, quote=True)}">查看原帖</a>'
        message = self._compose_message(header_lines, body, footer_line)

        if len(message) > self._MAX_MESSAGE_LENGTH:
            body = self._truncate_html_body_to_fit(
                body,
                header_lines,
                footer_line,
            )
            message = self._compose_message(header_lines, body, footer_line)

        if len(message) > self._MAX_MESSAGE_LENGTH:
            message = message[: self._MAX_MESSAGE_LENGTH]

        return TelegramPayload(
            text=message,
            media_urls=result.content.media_urls(),
            disable_web_page_preview=False,
            parse_mode="html",
        )

    def format_unavailable_post(
        self,
        post: ForumPost,
        forum_message: str,
    ) -> TelegramPayload:
        header_lines = [
            f"<b>{escape(post.title)}</b>",
            escape(post.author),
        ]
        body = f"论坛提示：{escape(forum_message)}"
        footer_line = f'<a href="{escape(post.url, quote=True)}">查看原帖</a>'
        message = self._compose_message(header_lines, body, footer_line)

        if len(message) > self._MAX_MESSAGE_LENGTH:
            body = self._truncate_html_body_to_fit(body, header_lines, footer_line)
            message = self._compose_message(header_lines, body, footer_line)

        if len(message) > self._MAX_MESSAGE_LENGTH:
            message = message[: self._MAX_MESSAGE_LENGTH]

        return TelegramPayload(
            text=message,
            disable_web_page_preview=False,
            parse_mode="html",
        )

    def _compose_message(
        self,
        header_lines: list[str],
        body: str,
        footer_line: str,
    ) -> str:
        sections = [line for line in header_lines if line]
        if body:
            sections.append(body)
        sections.append(footer_line)
        return "\n".join(section.rstrip() for section in sections if section).strip()

    def _truncate_html_body_to_fit(
        self,
        html_body: str,
        header_lines: list[str],
        footer_line: str,
    ) -> str:
        if not html_body:
            return ""

        low = 0
        high = len(html_body)
        best = ""

        while low <= high:
            middle = (low + high) // 2
            truncated_body = self._truncate_html_fragment(html_body, middle)
            candidate = self._compose_message(header_lines, truncated_body, footer_line)
            if len(candidate) <= self._MAX_MESSAGE_LENGTH:
                best = truncated_body
                low = middle + 1
            else:
                high = middle - 1

        return best

    def _truncate_html_fragment(self, html: str, max_chars: int) -> str:
        if max_chars <= 0:
            return ""

        if max_chars >= len(html):
            return html

        snippet = self._trim_incomplete_html_tail(html[:max_chars]).rstrip()
        if not snippet:
            return escape(self._TRUNCATION_SUFFIX)

        return f"{snippet}{escape(self._TRUNCATION_SUFFIX)}{self._closing_tags_for(snippet)}"

    def _trim_incomplete_html_tail(self, html: str) -> str:
        last_lt = html.rfind("<")
        last_gt = html.rfind(">")
        if last_lt > last_gt:
            html = html[:last_lt]

        last_amp = html.rfind("&")
        last_semicolon = html.rfind(";")
        if last_amp > last_semicolon and re.fullmatch(r"&[#A-Za-z0-9]*", html[last_amp:]):
            html = html[:last_amp]

        return html

    def _closing_tags_for(self, html: str) -> str:
        stack: list[str] = []
        closeable_tags = {"a", "b", "i", "u", "s", "pre", "blockquote", "tg-spoiler"}

        for match in re.finditer(r"<\s*(/)?\s*([A-Za-z][\w-]*)(?:\s[^<>]*)?>", html):
            is_closing = bool(match.group(1))
            tag_name = match.group(2).lower()
            if tag_name not in closeable_tags:
                continue

            if is_closing:
                if tag_name in stack:
                    stack.pop(len(stack) - 1 - stack[::-1].index(tag_name))
                continue

            if match.group(0).rstrip().endswith("/>"):
                continue
            stack.append(tag_name)

        return "".join(f"</{tag_name}>" for tag_name in reversed(stack))

    def _render_elements(
        self,
        elements: tuple[ContentElement, ...],
        *,
        fold_body_groups: bool = True,
        thread_title: str | None = None,
    ) -> str:
        lines: list[str] = []
        current_inline: list[str] = []
        current_plain: list[str] = []
        body_group: list[tuple[int, str, str]] = []
        pending_breaks = 0

        def append_line(segment: str, breaks_before: int):
            if lines:
                if self._should_collapse_breaks_between(lines[-1], segment):
                    breaks_before = min(breaks_before, 1)
                lines.extend([""] * max(0, breaks_before - 1))

            lines.append(segment)

        def flush_body_group():
            nonlocal body_group

            if not body_group:
                return

            group_lines: list[str] = []
            group_plain_parts: list[str] = []
            for index, (breaks_before, segment, plain_text) in enumerate(body_group):
                if index > 0:
                    previous_segment = body_group[index - 1][1]
                    if self._should_collapse_breaks_between(previous_segment, segment):
                        breaks_before = min(breaks_before, 1)
                    group_lines.extend([""] * max(0, breaks_before - 1))
                group_lines.append(segment)
                group_plain_parts.append(plain_text)

            grouped_segment = "\n".join(line.rstrip() for line in group_lines).strip()
            if fold_body_groups:
                grouped_segment = self._finalize_segment(
                    grouped_segment,
                    self._join_plain_fragments(group_plain_parts),
                )
            append_line(grouped_segment, body_group[0][0])
            body_group = []

        def push_segment(segment: str, plain_text: str, *, groupable: bool):
            nonlocal pending_breaks

            segment = segment.strip()
            if not segment:
                return

            if groupable:
                body_group.append((pending_breaks, segment, plain_text.strip()))
                pending_breaks = 0
                return

            flush_body_group()
            finalized = self._finalize_segment(segment, plain_text)
            if lines and self._should_collapse_breaks_between(lines[-1], finalized):
                pending_breaks = min(pending_breaks, 1)
            append_line(finalized, pending_breaks)
            pending_breaks = 0

        for element in elements:
            if isinstance(element, LineBreakElement):
                inline_segment = self._join_inline_fragments(current_inline)
                if inline_segment:
                    push_segment(
                        inline_segment,
                        self._join_plain_fragments(current_plain),
                        groupable=True,
                    )
                current_inline = []
                current_plain = []
                pending_breaks += 1
                continue

            if isinstance(element, self._INLINE_BREAKING_NODES):
                if current_inline:
                    push_segment(
                        self._join_inline_fragments(current_inline),
                        self._join_plain_fragments(current_plain),
                        groupable=True,
                    )
                    current_inline = []
                    current_plain = []
                block = self._render_block(element, thread_title=thread_title)
                if block:
                    push_segment(block, element.to_plain_text(), groupable=False)
                continue

            current_inline.append(self._render_inline(element, thread_title=thread_title))
            current_plain.append(element.to_plain_text())

        if current_inline:
            push_segment(
                self._join_inline_fragments(current_inline),
                self._join_plain_fragments(current_plain),
                groupable=True,
            )

        flush_body_group()

        rendered = "\n".join(line.rstrip() for line in lines)
        rendered = re.sub(r"\n{3,}", "\n\n", rendered)
        return rendered.strip()

    def _finalize_segment(self, segment: str, plain_text: str) -> str:
        if not segment:
            return ""

        if self._is_block_html_segment(segment):
            return segment

        if not self._should_expand_plain_text(plain_text):
            return segment

        return f"<blockquote expandable>{segment}</blockquote>"

    def _is_block_html_segment(self, segment: str) -> bool:
        return segment.lstrip().startswith(("<blockquote", "<pre", "<tg-spoiler"))

    def _should_expand_plain_text(self, plain_text: str) -> bool:
        normalized = " ".join(plain_text.split())
        return len(normalized) > self._MAX_EXPANDABLE_SEGMENT_PLAIN_LENGTH

    def _render_block(
        self,
        element: ContentElement,
        *,
        thread_title: str | None = None,
    ) -> str:
        if isinstance(element, CodeBlockNode):
            return f"<pre>{escape(element.code)}</pre>"

        if isinstance(element, HiddenBlockNode):
            return self._render_hidden_block(element, thread_title=thread_title)

        if isinstance(element, QuoteNode):
            body = self._render_elements(
                element.children,
                fold_body_groups=False,
                thread_title=thread_title,
            )
            body = body or escape(element.to_plain_text())
            if self._should_expand_plain_text(element.to_plain_text()):
                return f"<blockquote expandable>{body}</blockquote>"
            return f"<blockquote>{body}</blockquote>"

        if isinstance(element, PageBreakNode):
            return f"<b>第 {element.page_number} 页</b>"

        if isinstance(element, UnknownElement):
            if element.label == "table":
                table_html = self._render_table(element.raw_html)
                if table_html:
                    return table_html
            return escape(element.to_plain_text())

        return self._render_inline(element, thread_title=thread_title)

    def _render_hidden_block(
        self,
        element: HiddenBlockNode,
        *,
        thread_title: str | None = None,
    ) -> str:
        body_html = self._render_elements(
            element.children,
            thread_title=thread_title,
        )
        body_text = self._plain_text_from_elements(element.children)

        if element.hidden_kind == "spoiler":
            spoiler_text = body_text or element.summary or "剧透内容"
            return f"<tg-spoiler>{escape(spoiler_text)}</tg-spoiler>"

        label = {
            "hide": "隐藏内容",
            "collapse": "折叠内容",
        }.get(element.hidden_kind, "隐藏内容")
        summary = f": {escape(element.summary)}" if element.summary else ""
        lines = [f"{label}{summary}"]
        if body_html:
            lines.append(body_html)
        return f"<blockquote expandable>{'\n'.join(lines)}</blockquote>"

    def _render_inline(
        self,
        element: ContentElement,
        *,
        thread_title: str | None = None,
    ) -> str:
        if isinstance(element, TextNode):
            return self._wrap_text_marks(escape(element.text), element)

        if isinstance(element, LinkNode):
            label = escape(element.text or element.url)
            return f'<a href="{escape(element.url, quote=True)}">{label}</a>'

        if isinstance(element, ImageNode):
            label = escape(element.alt_text or "图片")
            return f'<a href="{escape(element.url, quote=True)}">{label}</a>'

        if isinstance(element, EmbedNode):
            label = escape(self._resolve_embed_label(element, thread_title=thread_title))
            return f'<a href="{escape(element.url, quote=True)}">{label}</a>'

        if isinstance(element, QuoteNode):
            return self._render_block(element, thread_title=thread_title)

        if isinstance(element, UnknownElement):
            if element.label == "table":
                table_html = self._render_table(element.raw_html)
                if table_html:
                    return table_html
            return escape(element.to_plain_text())

        return escape(element.to_plain_text())

    def _render_table(self, raw_html: str) -> str:
        rows = self._extract_table_rows(raw_html)
        if not rows:
            return ""

        header_cells: tuple[tuple[str, str], ...] = ()
        data_rows = rows
        if len(rows) > 1 and self._looks_like_table_header(rows[0]):
            header_cells = rows[0]
            data_rows = rows[1:]

        lines: list[str] = []
        if header_cells:
            header_text = " / ".join(
                plain_text for _, plain_text in header_cells if plain_text
            )
            if header_text:
                lines.append(f"表格: {escape(header_text)}")

        for row in data_rows:
            row_lines = self._render_table_row(row, header_cells)
            lines.extend(row_lines)

        body = "\n".join(line for line in lines if line).strip()
        if not body:
            return ""

        plain_text = "\n".join(
            " ".join(cell_plain for _, cell_plain in row if cell_plain)
            for row in rows
        )
        if self._should_expand_plain_text(plain_text):
            return f"<blockquote expandable>{body}</blockquote>"
        return body

    def _extract_table_rows(self, raw_html: str) -> list[tuple[tuple[str, str], ...]]:
        tree = etree.HTML(raw_html, parser=etree.HTMLParser())
        if tree is None:
            return []

        tables = tree.xpath("//table")
        if not tables:
            return []

        rows: list[tuple[tuple[str, str], ...]] = []
        for row in tables[0].xpath(".//tr"):
            cells: list[tuple[str, str]] = []
            for cell in row.xpath("./th|./td"):
                cell_html, plain_text = self._render_table_cell(cell)
                if cell_html or plain_text:
                    cells.append((cell_html, plain_text))
            if cells:
                rows.append(tuple(cells))
        return rows

    def _looks_like_table_header(self, row: tuple[tuple[str, str], ...]) -> bool:
        if not row:
            return False

        texts = [plain_text for _, plain_text in row if plain_text]
        if not texts:
            return False

        if any("<a " in cell_html for cell_html, _ in row):
            return False

        header_keywords = {
            "名称",
            "游戏",
            "价格",
            "评价",
            "语言",
            "支持",
            "商店",
            "进包",
            "折扣",
            "日期",
            "平台",
        }
        if any(any(keyword in text for keyword in header_keywords) for text in texts):
            return True

        return len(texts) > 1 and all(len(text) <= 12 for text in texts)

    def _render_table_cell(self, cell: etree._Element) -> tuple[str, str]:
        plain_text = self._normalize_table_text(" ".join(cell.xpath(".//text()")))
        if not plain_text:
            return "", ""

        anchors = cell.xpath(".//a[@href]")
        if len(anchors) == 1:
            anchor = anchors[0]
            anchor_text = self._normalize_table_text(" ".join(anchor.xpath(".//text()")))
            href = (anchor.get("href") or "").strip()
            if href and anchor_text == plain_text:
                label = escape(anchor_text or href)
                return f'<a href="{escape(href, quote=True)}">{label}</a>', plain_text

        return escape(plain_text), plain_text

    def _normalize_table_text(self, value: str) -> str:
        return re.sub(r"\s+", " ", unescape(value)).strip()

    def _render_table_row(
        self,
        row: tuple[tuple[str, str], ...],
        header_cells: tuple[tuple[str, str], ...],
    ) -> list[str]:
        if not row:
            return []

        title_html, title_plain = row[0]
        title = title_html or escape(title_plain)
        lines = [f"• {title}"]

        details: list[str] = []
        for index, (cell_html, plain_text) in enumerate(row[1:], start=1):
            if not plain_text:
                continue
            label = ""
            if index < len(header_cells):
                label = header_cells[index][1]
            label = label or f"列 {index + 1}"
            details.append(f"{escape(label)}: {cell_html or escape(plain_text)}")

        if details:
            lines.append(f"  {' ｜ '.join(details)}")
        return lines

    def _wrap_text_marks(self, text: str, element: TextNode) -> str:
        wrapped = text
        if element.bold:
            wrapped = f"<b>{wrapped}</b>"
        if element.italic:
            wrapped = f"<i>{wrapped}</i>"
        if element.underline:
            wrapped = f"<u>{wrapped}</u>"
        if element.strikethrough:
            wrapped = f"<s>{wrapped}</s>"
        return wrapped

    def _plain_text_from_elements(self, elements: tuple[ContentElement, ...]) -> str:
        return " ".join(
            element.to_plain_text().strip()
            for element in elements
            if element.to_plain_text().strip()
        ).strip()

    def _join_plain_fragments(self, fragments: list[str]) -> str:
        return " ".join(fragment.strip() for fragment in fragments if fragment.strip())

    def _join_inline_fragments(self, fragments: list[str]) -> str:
        parts: list[str] = []
        for fragment in fragments:
            if not fragment:
                continue
            if parts and self._needs_space(parts[-1], fragment):
                parts.append(" ")
            parts.append(fragment)
        return "".join(parts).strip()

    def _needs_space(self, left: str, right: str) -> bool:
        left_visible = self._visible_text(left)
        right_visible = self._visible_text(right)
        if not left_visible or not right_visible:
            return False
        if left_visible.endswith(("\n", " ", "(", "[", "<")):
            return False
        if right_visible.startswith(
            (
                "\n",
                ")",
                "]",
                ">",
                ",",
                ".",
                "!",
                "?",
                ":",
                ";",
                "，",
                "。",
                "！",
                "？",
                "：",
                "；",
            )
        ):
            return False
        return True

    def _visible_text(self, fragment: str) -> str:
        return re.sub(r"<[^>]+>", "", fragment)

    def _is_heading_line(self, line: str) -> bool:
        return bool(re.fullmatch(r"<b>[^<\n]+</b>", line.strip()))

    def _ends_with_heading_line(self, segment: str) -> bool:
        lines = [line for line in segment.splitlines() if line.strip()]
        return bool(lines and self._is_heading_line(lines[-1]))

    def _starts_with_heading_line(self, segment: str) -> bool:
        lines = [line for line in segment.splitlines() if line.strip()]
        return bool(lines and self._is_heading_line(lines[0]))

    def _should_collapse_breaks_between(self, left: str, right: str) -> bool:
        return self._is_compact_component(left, edge="end") or self._is_compact_component(
            right,
            edge="start",
        )

    def _is_compact_component(self, segment: str, *, edge: str) -> bool:
        stripped = segment.strip()
        if not stripped:
            return False

        if edge == "end" and self._ends_with_heading_line(stripped):
            return True
        if edge == "start" and self._starts_with_heading_line(stripped):
            return True

        lines = [line.strip() for line in stripped.splitlines() if line.strip()]
        target = lines[-1] if edge == "end" else lines[0]
        return target.startswith(("<a ", "<blockquote", "<pre", "<tg-spoiler"))

    def _resolve_embed_label(
        self,
        element: EmbedNode,
        *,
        thread_title: str | None = None,
    ) -> str:
        if element.provider != "steam":
            return element.label or element.provider.title()

        if element.label and element.label not in {"Steam", "蒸汽平台"}:
            return element.label

        cached = self._steam_label_cache.get(element.url)
        if cached is not None:
            return cached

        label = self._derive_steam_label_from_url(element.url)
        if label is None:
            label = self._fetch_steam_store_api_label(element.url)
        if label is None:
            label = self._normalize_steam_title(self._fetch_steam_title(element.url))
        if label is None:
            label = self._derive_steam_label_from_thread_title(thread_title)

        resolved = label or element.label or "Steam"
        self._steam_label_cache[element.url] = resolved
        return resolved

    def _derive_steam_label_from_thread_title(self, title: str | None) -> str | None:
        if not title:
            return None

        match = re.search(r"《([^》]+)》", title)
        if match:
            return match.group(1).strip() or None

        match = re.search(r"(?i)^(.+?)\s+Steam\s*页面", title)
        if match:
            return match.group(1).strip(" -:：") or None

        return None

    def _derive_steam_label_from_url(self, url: str) -> str | None:
        parsed = urlsplit(url)
        segments = [unquote(segment) for segment in parsed.path.split("/") if segment]
        if len(segments) < 3:
            return None

        if segments[0] not in {"app", "sub", "bundle"}:
            return None

        slug = segments[2]
        if not slug or slug.isdigit():
            return None

        cleaned = re.sub(r"[_\-]+", " ", slug)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned or None

    def _fetch_steam_store_api_label(self, url: str) -> str | None:
        parsed = urlsplit(url)
        segments = [segment for segment in parsed.path.split("/") if segment]
        if len(segments) < 2:
            return None

        store_host = "store.steamchina.com" if "steamchina" in parsed.netloc else "store.steampowered.com"
        api_url: str
        params: dict[str, str]

        if segments[0] == "app" and segments[1].isdigit():
            api_url = f"https://{store_host}/api/appdetails"
            params = {
                "appids": segments[1],
                "filters": "basic",
                "l": "schinese",
            }
        elif segments[0] == "sub" and segments[1].isdigit():
            api_url = f"https://{store_host}/api/packagedetails"
            params = {
                "packageids": segments[1],
                "l": "schinese",
            }
        else:
            return None

        try:
            with httpx.Client(
                follow_redirects=True,
                timeout=self._steam_title_timeout,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/137.0.0.0 Safari/537.36"
                    ),
                    "Accept": "application/json",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                },
            ) as client:
                response = client.get(api_url, params=params)
        except (httpx.HTTPError, ValueError):
            return None

        if response.status_code != 200:
            return None

        try:
            payload = response.json()
        except ValueError:
            return None

        entry_id = segments[1]
        entry = payload.get(entry_id)
        if not isinstance(entry, dict) or not entry.get("success"):
            return None

        data = entry.get("data")
        if not isinstance(data, dict):
            return None

        name = data.get("name")
        if not isinstance(name, str):
            return None

        normalized = re.sub(r"\s+", " ", unescape(name)).strip()
        if not normalized or self._is_invalid_steam_title(normalized):
            return None
        return normalized

    def _fetch_steam_title(self, url: str) -> str | None:
        try:
            with httpx.Client(
                follow_redirects=True,
                timeout=self._steam_title_timeout,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/137.0.0.0 Safari/537.36"
                    ),
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                },
            ) as client:
                response = client.get(url)
        except httpx.HTTPError:
            return None

        if response.status_code != 200:
            return None

        tree = etree.HTML(response.text, parser=etree.HTMLParser())
        if tree is None:
            return None

        meta_titles = tree.xpath(
            '//meta[@property="og:title"]/@content | //meta[@name="twitter:title"]/@content'
        )
        if meta_titles:
            return meta_titles[0].strip()

        title_nodes = tree.xpath("//title/text()")
        if title_nodes:
            return title_nodes[0].strip()

        return None

    def _normalize_steam_title(self, title: str | None) -> str | None:
        if not title:
            return None

        normalized = re.sub(r"\s+", " ", unescape(title)).strip()
        if self._is_invalid_steam_title(normalized):
            return None

        patterns = (
            r"^Steam 上的\s+",
            r"^在 Steam 上购买\s+",
            r"^Steam 上购买\s+",
            r"^蒸汽平台上的\s+",
            r"^在蒸汽平台购买\s+",
            r"^Buy\s+",
            r"^Pre\-Purchase\s+",
            r"^Save\s+\d+%\s+on\s+",
        )
        for pattern in patterns:
            normalized = re.sub(pattern, "", normalized, flags=re.I)

        suffixes = (
            r"\s+on Steam$",
            r"\s+on Steam China$",
            r"\s+\| Steam$",
            r"\s+\| 蒸汽平台$",
        )
        for suffix in suffixes:
            normalized = re.sub(suffix, "", normalized, flags=re.I)

        normalized = normalized.strip(" -|")
        if self._is_invalid_steam_title(normalized):
            return None
        return normalized or None

    def _is_invalid_steam_title(self, title: str) -> bool:
        normalized = title.strip().lower()
        invalid_titles = {
            "站点错误",
            "site error",
            "error",
            "access denied",
            "403 forbidden",
            "too many requests",
        }
        return normalized in invalid_titles
