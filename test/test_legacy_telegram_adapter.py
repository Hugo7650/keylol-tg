from __future__ import annotations

from datetime import datetime
from typing import Any, cast
import unittest

from clients.telegram_client import TelegramClient
from infrastructure.services import LegacyTelegramPayloadAdapter
from models.post import ForumPost
from models.thread import ForumThread


class _FakeApp:
    def __init__(self):
        self.messages: list[dict[str, object]] = []

    async def send_message(self, **kwargs):
        self.messages.append(kwargs)


class _NoFormatPost:
    def __init__(self):
        self.id = 1
        self.title = "兼容帖子"
        self.author = "兼容作者"
        self.url = "https://example.com/t1-1-1"
        self.publish_time = datetime(2026, 5, 30, 12, 34)
        self.tags = ["标签甲"]
        self.content = "兼容正文"
        self.images = ["https://example.com/image.png"]

    def to_telegram_message(self):
        raise AssertionError("legacy send path should not call to_telegram_message")


class LegacyTelegramAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_send_post_to_user_uses_payload_adapter(self):
        client = TelegramClient(1, "hash", "token")
        fake_app = _FakeApp()
        client.app = cast(Any, fake_app)

        post = _NoFormatPost()
        success = await client.send_post_to_user(42, post)  # type: ignore[arg-type]

        self.assertTrue(success)
        self.assertEqual(len(fake_app.messages), 1)
        sent = fake_app.messages[0]
        text = cast(str, sent["text"])
        self.assertEqual(sent["chat_id"], 42)
        self.assertTrue(sent["disable_web_page_preview"])
        self.assertIn("**兼容帖子**", text)
        self.assertIn("兼容正文", text)

    async def test_legacy_adapter_projects_forum_post(self):
        post = ForumPost(
            id=2,
            title="旧帖子",
            url="https://example.com/t2-1-1",
            author="旧作者",
        )
        post._content = "旧正文"
        post._publish_time = datetime(2026, 5, 30, 12, 35)
        post._images = ["https://example.com/old.png"]
        post._tags = ["旧标签"]
        post._is_loaded = True

        payload = LegacyTelegramPayloadAdapter().from_forum_post(
            post,
            disable_web_page_preview=False,
        )

        self.assertFalse(payload.disable_web_page_preview)
        self.assertIn("**旧帖子**", payload.text)
        self.assertIn("旧标签", payload.text)
        self.assertEqual(payload.media_urls, ("https://example.com/old.png",))

    async def test_model_compatibility_methods_delegate_to_adapter(self):
        post = ForumPost(
            id=3,
            title="兼容方法帖子",
            url="https://example.com/t3-1-1",
            author="兼容作者",
        )
        post._content = "兼容方法正文"
        post._publish_time = datetime(2026, 5, 30, 12, 36)
        post._images = []
        post._tags = ["兼容标签"]
        post._is_loaded = True

        thread = ForumThread(
            id="4",
            title="线程标题",
            author="线程作者",
            publish_time=datetime(2026, 5, 30, 12, 37),
            url="https://example.com/t4-1-1",
            tags=["线程标签"],
        )

        self.assertIn("兼容方法正文", post.to_telegram_message())
        self.assertIn("[查看原帖](https://example.com/t3-1-1)", post.to_telegram_message())
        self.assertIn("线程标签", thread.to_telegram_message())

    async def test_forum_post_lazy_loads_via_details_loader(self):
        calls: list[int] = []

        def details_loader(post_id: int):
            calls.append(post_id)
            return {
                "content": "延迟加载正文",
                "publish_time": datetime(2026, 5, 30, 12, 38),
                "images": ["https://example.com/lazy.png"],
                "tags": ["延迟标签"],
            }

        post = ForumPost(
            id=9,
            title="延迟帖子",
            url="https://example.com/t9-1-1",
            author="延迟作者",
            details_loader=details_loader,
        )

        self.assertEqual(post.content, "延迟加载正文")
        self.assertEqual(post.images, ["https://example.com/lazy.png"])
        self.assertEqual(post.tags, ["延迟标签"])
        self.assertEqual(calls, [9])


if __name__ == "__main__":
    unittest.main()