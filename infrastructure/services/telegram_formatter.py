from __future__ import annotations

from domain.value_objects import ParseResult
from domain.value_objects import TelegramPayload


class TelegramFormatter:
    """Format structured thread content into the bot's current Telegram message shape."""

    def format(self, result: ParseResult) -> TelegramPayload:
        metadata = result.content.metadata
        lines = [
            f"**{metadata.title}**",
            f"{metadata.author} \\ {metadata.publish_time.strftime('%Y-%m-%d %H:%M')}",
        ]

        if metadata.tags:
            lines.append(f"标签: {', '.join(metadata.tags)}")

        body = result.fallback_text or result.content.to_plain_text()
        if body:
            lines.append(body)

        lines.append(f"[查看原帖]({metadata.url})")

        return TelegramPayload(
            text="\n".join(lines).strip(),
            media_urls=result.content.media_urls(),
            disable_web_page_preview=False,
        )
