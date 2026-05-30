from __future__ import annotations

from domain.value_objects import TelegramPayload
from models.post import ForumPost
from models.thread import ForumThread


class LegacyTelegramPayloadAdapter:
    """Adapt legacy ForumPost/ForumThread models into TelegramPayload."""

    def from_forum_post(
        self,
        post: ForumPost,
        *,
        disable_web_page_preview: bool,
    ) -> TelegramPayload:
        lines = [
            f"**{post.title}**",
            f"{post.author} \\ {post.publish_time.strftime('%Y-%m-%d %H:%M')}",
        ]

        if post.tags:
            lines.append(f"标签: {', '.join(post.tags)}")

        if post.content:
            lines.append(post.content)

        lines.append(f"[查看原帖]({post.url})")

        return TelegramPayload(
            text="\n".join(lines).strip(),
            media_urls=tuple(post.images),
            disable_web_page_preview=disable_web_page_preview,
        )

    def from_forum_thread(
        self,
        thread: ForumThread,
        *,
        disable_web_page_preview: bool,
    ) -> TelegramPayload:
        lines = [
            f"**{thread.title}**",
            f"{thread.author} \\ {thread.publish_time.strftime('%Y-%m-%d %H:%M')}",
        ]

        if thread.tags:
            lines.append(f"标签: {', '.join(thread.tags)}")

        lines.append(f"[查看原帖]({thread.url})")

        return TelegramPayload(
            text="\n".join(lines).strip(),
            media_urls=tuple(thread.images),
            disable_web_page_preview=disable_web_page_preview,
        )
