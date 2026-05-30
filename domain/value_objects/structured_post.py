from __future__ import annotations

from abc import ABC
from abc import abstractmethod
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from typing import Any
from typing import ClassVar
from typing import Mapping


def _join_text_fragments(fragments: tuple[str, ...] | list[str]) -> str:
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
            and not fragment.startswith(("\n", ")", "]", ">", ",", ".", "!", "?", ":", ";", "，", "。", "！", "？", "：", "；"))
        ):
            parts.append(" ")

        parts.append(fragment)

    return "".join(parts).strip()


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
class RawThreadData:
    metadata: RootPostMetadata
    root_post_html: str
    page_html: str | None = None


@dataclass(frozen=True, slots=True)
class ContentElement(ABC):
    kind: ClassVar[str]

    @abstractmethod
    def to_plain_text(self) -> str:
        raise NotImplementedError

    def media_urls(self) -> tuple[str, ...]:
        return ()


@dataclass(frozen=True, slots=True)
class TextElement(ContentElement):
    text: str
    bold: bool = False
    italic: bool = False

    kind: ClassVar[str] = "text"

    def to_plain_text(self) -> str:
        return self.text


@dataclass(frozen=True, slots=True)
class LinkElement(ContentElement):
    url: str
    text: str

    kind: ClassVar[str] = "link"

    def to_plain_text(self) -> str:
        return self.text or self.url


@dataclass(frozen=True, slots=True)
class ImageElement(ContentElement):
    url: str
    alt_text: str | None = None

    kind: ClassVar[str] = "image"

    def to_plain_text(self) -> str:
        return self.alt_text or self.url

    def media_urls(self) -> tuple[str, ...]:
        return (self.url,) if self.url else ()


@dataclass(frozen=True, slots=True)
class QuoteElement(ContentElement):
    children: tuple[ContentElement, ...]

    kind: ClassVar[str] = "quote"

    def to_plain_text(self) -> str:
        return _join_text_fragments(
            [child.to_plain_text() for child in self.children if child.to_plain_text()]
        )

    def media_urls(self) -> tuple[str, ...]:
        urls: list[str] = []
        for child in self.children:
            urls.extend(child.media_urls())
        return tuple(urls)


@dataclass(frozen=True, slots=True)
class EmbedElement(ContentElement):
    provider: str
    url: str
    label: str | None = None

    kind: ClassVar[str] = "embed"

    def to_plain_text(self) -> str:
        return self.label or self.url

    def media_urls(self) -> tuple[str, ...]:
        return (self.url,) if self.url else ()


@dataclass(frozen=True, slots=True)
class LineBreakElement(ContentElement):
    kind: ClassVar[str] = "line_break"

    def to_plain_text(self) -> str:
        return "\n"


@dataclass(frozen=True, slots=True)
class UnknownElement(ContentElement):
    raw_html: str
    text_fallback: str

    kind: ClassVar[str] = "unknown"

    def to_plain_text(self) -> str:
        return self.text_fallback


@dataclass(frozen=True, slots=True)
class PostContent:
    metadata: RootPostMetadata
    elements: tuple[ContentElement, ...]

    def to_plain_text(self) -> str:
        return _join_text_fragments(
            [element.to_plain_text() for element in self.elements if element.to_plain_text()]
        )

    def media_urls(self) -> tuple[str, ...]:
        urls: list[str] = []
        for element in self.elements:
            urls.extend(element.media_urls())
        return tuple(urls)


@dataclass(frozen=True, slots=True)
class ParseIssue:
    code: str
    message: str
    context: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ParseResult:
    content: PostContent
    fallback_text: str
    warnings: tuple[ParseIssue, ...] = ()
    errors: tuple[ParseIssue, ...] = ()
    used_fallback: bool = False

    @property
    def is_successful(self) -> bool:
        return not self.errors


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
