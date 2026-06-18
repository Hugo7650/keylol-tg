from __future__ import annotations

from abc import ABC
from abc import abstractmethod
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from typing import Any
from typing import ClassVar
from typing import Iterable
from typing import Mapping


def _join_text_fragments(fragments: Iterable[str]) -> str:
    parts: list[str] = []
    for fragment in fragments:
        if not fragment:
            continue

        if fragment == "\n":
            if parts and parts[-1].endswith(" "):
                parts[-1] = parts[-1].rstrip()
            parts.append(fragment)
            continue

        if (
            parts
            and not parts[-1].endswith(("\n", " ", "(", "[", "<"))
            and not fragment.startswith(
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
            )
        ):
            parts.append(" ")

        parts.append(fragment)

    return "".join(parts).strip()


def _dedupe_urls(urls: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for url in urls:
        if not url or url in seen:
            continue
        seen.add(url)
        ordered.append(url)
    return tuple(ordered)


@dataclass(frozen=True, slots=True)
class FetchedThreadPage:
    thread_id: int
    url: str
    html: str
    fetched_at: datetime


@dataclass(frozen=True, slots=True)
class FetchedLatestPostsPage:
    url: str
    html: str
    fetched_at: datetime


@dataclass(frozen=True, slots=True)
class RootPostMetadata:
    thread_id: int
    root_post_id: int
    title: str
    author: str
    publish_time: datetime
    url: str
    tags: tuple[str, ...] = ()
    forum_extra: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RootPostFragment:
    page_number: int
    container_kind: str
    html: str


@dataclass(frozen=True, slots=True)
class RawThreadData:
    metadata: RootPostMetadata
    root_post_html: str
    page_html: str | None = None
    container_kind: str = "postmessage"
    fragments: tuple[RootPostFragment, ...] = ()

    @property
    def has_pagination(self) -> bool:
        return len(self.fragments) > 1


@dataclass(frozen=True, slots=True)
class ContentNode(ABC):
    kind: ClassVar[str]

    @abstractmethod
    def to_plain_text(self) -> str:
        raise NotImplementedError

    def media_urls(self) -> tuple[str, ...]:
        return ()


@dataclass(frozen=True, slots=True)
class TextNode(ContentNode):
    text: str
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strikethrough: bool = False
    superscript: bool = False
    subscript: bool = False

    kind: ClassVar[str] = "text"

    @property
    def marks(self) -> tuple[str, ...]:
        marks: list[str] = []
        if self.bold:
            marks.append("bold")
        if self.italic:
            marks.append("italic")
        if self.underline:
            marks.append("underline")
        if self.strikethrough:
            marks.append("strikethrough")
        if self.superscript:
            marks.append("superscript")
        if self.subscript:
            marks.append("subscript")
        return tuple(marks)

    def to_plain_text(self) -> str:
        return self.text


@dataclass(frozen=True, slots=True)
class LinkNode(ContentNode):
    url: str
    text: str

    kind: ClassVar[str] = "link"

    def to_plain_text(self) -> str:
        return self.text or self.url


@dataclass(frozen=True, slots=True)
class ImageNode(ContentNode):
    url: str
    alt_text: str | None = None

    kind: ClassVar[str] = "image"

    def to_plain_text(self) -> str:
        return self.alt_text or "[图片]"

    def media_urls(self) -> tuple[str, ...]:
        return (self.url,) if self.url else ()


@dataclass(frozen=True, slots=True)
class QuoteNode(ContentNode):
    children: tuple[ContentNode, ...]

    kind: ClassVar[str] = "quote"

    def to_plain_text(self) -> str:
        quote_text = _join_text_fragments(child.to_plain_text() for child in self.children)
        return quote_text if not quote_text else f"引用: {quote_text}"

    def media_urls(self) -> tuple[str, ...]:
        return _dedupe_urls(
            url for child in self.children for url in child.media_urls()
        )


@dataclass(frozen=True, slots=True)
class CodeBlockNode(ContentNode):
    code: str
    language: str | None = None
    caption: str | None = None

    kind: ClassVar[str] = "code_block"

    def to_plain_text(self) -> str:
        return self.code.strip()


@dataclass(frozen=True, slots=True)
class HiddenBlockNode(ContentNode):
    hidden_kind: str
    summary: str | None = None
    children: tuple[ContentNode, ...] = ()
    revealed: bool | None = None

    kind: ClassVar[str] = "hidden_block"

    def to_plain_text(self) -> str:
        label = {
            "hide": "隐藏内容",
            "collapse": "折叠内容",
            "spoiler": "剧透内容",
        }.get(self.hidden_kind, "隐藏内容")
        summary = (self.summary or "").strip()
        child_text = _join_text_fragments(child.to_plain_text() for child in self.children)
        header = label if not summary else f"{label}: {summary}"
        return _join_text_fragments([header, child_text]) if child_text else header

    def media_urls(self) -> tuple[str, ...]:
        return _dedupe_urls(
            url for child in self.children for url in child.media_urls()
        )


@dataclass(frozen=True, slots=True)
class EmbedNode(ContentNode):
    provider: str
    url: str
    label: str | None = None

    kind: ClassVar[str] = "embed"

    def to_plain_text(self) -> str:
        return self.label or self.url

    def media_urls(self) -> tuple[str, ...]:
        return (self.url,) if self.url else ()


@dataclass(frozen=True, slots=True)
class PageBreakNode(ContentNode):
    page_number: int

    kind: ClassVar[str] = "page_break"

    def to_plain_text(self) -> str:
        return f"\n--- 第 {self.page_number} 页 ---\n"


@dataclass(frozen=True, slots=True)
class LineBreakNode(ContentNode):
    kind: ClassVar[str] = "line_break"

    def to_plain_text(self) -> str:
        return "\n"


@dataclass(frozen=True, slots=True)
class UnsupportedBlockNode(ContentNode):
    raw_html: str
    text_fallback: str
    label: str = "unsupported"
    reason: str | None = None

    kind: ClassVar[str] = "unsupported_block"

    def to_plain_text(self) -> str:
        fallback = self.text_fallback.strip()
        if fallback:
            return fallback
        return f"[未完整支持: {self.label}]"


@dataclass(frozen=True, slots=True)
class Document:
    metadata: RootPostMetadata
    elements: tuple[ContentNode, ...]

    def to_plain_text(self) -> str:
        return _join_text_fragments(
            element.to_plain_text() for element in self.elements if element.to_plain_text()
        )

    def media_urls(self) -> tuple[str, ...]:
        return _dedupe_urls(
            url for element in self.elements for url in element.media_urls()
        )

    @property
    def children(self) -> tuple[ContentNode, ...]:
        return self.elements


@dataclass(frozen=True, slots=True)
class ParseIssue:
    code: str
    message: str
    context: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ParseResult:
    content: Document
    fallback_text: str
    warnings: tuple[ParseIssue, ...] = ()
    errors: tuple[ParseIssue, ...] = ()
    used_fallback: bool = False

    @property
    def document(self) -> Document:
        return self.content

    @property
    def is_successful(self) -> bool:
        return not self.errors

    @property
    def issues(self) -> tuple[ParseIssue, ...]:
        return self.errors + self.warnings


@dataclass(frozen=True, slots=True)
class TelegramPayload:
    text: str
    media_urls: tuple[str, ...] = ()
    disable_web_page_preview: bool = False
    parse_mode: str | None = None


@dataclass(frozen=True, slots=True)
class ProcessedThread:
    raw: RawThreadData
    parse_result: ParseResult
    telegram_payload: TelegramPayload


ContentElement = ContentNode
TextElement = TextNode
LinkElement = LinkNode
ImageElement = ImageNode
QuoteElement = QuoteNode
EmbedElement = EmbedNode
LineBreakElement = LineBreakNode
UnknownElement = UnsupportedBlockNode
PostContent = Document
