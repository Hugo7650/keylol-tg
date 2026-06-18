from __future__ import annotations

import unittest
from typing import Any
from typing import cast

from pyrogram.enums import ParseMode

from clients.telegram_client import TelegramClient
from domain.value_objects import TelegramPayload


class _FakePyrogramApp:
    def __init__(self):
        self.sent_messages: list[dict] = []
        self.sent_photos: list[dict] = []

    async def send_message(self, **kwargs):
        self.sent_messages.append(kwargs)

    async def send_photo(self, **kwargs):
        self.sent_photos.append(kwargs)


class TelegramClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_send_payload_to_channel_keeps_single_message(self):
        client = TelegramClient(api_id=1, api_hash="hash", bot_token="token")
        fake_app = _FakePyrogramApp()
        client.app = cast(Any, fake_app)
        payload = TelegramPayload(
            text="<b>正文</b>",
            media_urls=(
                "https://example.com/example.png",
                "https://store.steampowered.com/app/123/?utm_source=keylol",
            ),
            parse_mode="html",
        )

        success = await client.send_payload_to_channel(channel_id=123, payload=payload)

        self.assertTrue(success)
        self.assertEqual(len(fake_app.sent_messages), 1)
        self.assertEqual(len(fake_app.sent_photos), 0)
        self.assertEqual(fake_app.sent_messages[0]["chat_id"], 123)
        self.assertEqual(fake_app.sent_messages[0]["parse_mode"], ParseMode.HTML)
        self.assertEqual(fake_app.sent_messages[0]["text"], "<b>正文</b>")