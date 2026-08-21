from __future__ import annotations

import asyncio
from datetime import datetime
import json
from tempfile import TemporaryDirectory
from typing import Any, cast
import unittest
from unittest.mock import patch

from clients.forum_client import ForumThreadUnavailableException
from clients.forum_client import ForumTransportException
from domain.value_objects import FetchedLatestPostsPage
from domain.value_objects import ParseResult
from domain.value_objects import PostContent
from domain.value_objects import ProcessedThread
from domain.value_objects import RawThreadData
from domain.value_objects import RootPostMetadata
from domain.value_objects import TelegramPayload
from domain.value_objects import TextElement
from models.post import ForumPost
from services.post_service import PostService


async def _immediate_sleep(_delay: float) -> None:
    return None


def _make_processed_thread(thread_id: int, payload_text: str) -> ProcessedThread:
    metadata = cast(Any, RootPostMetadata)(
        thread_id=thread_id,
        root_post_id=thread_id,
        title=f"帖子 {thread_id}",
        author="结构化作者",
        publish_time=datetime(2026, 5, 30, 12, 40),
        url=f"https://example.com/t{thread_id}-1-1",
    )
    content = PostContent(metadata=metadata, elements=(TextElement(text="结构化正文"),))
    parse_result = ParseResult(content=content, fallback_text="结构化正文")
    raw = RawThreadData(metadata=metadata, root_post_html="<p>结构化正文</p>")
    return ProcessedThread(
        raw=raw,
        parse_result=parse_result,
        telegram_payload=TelegramPayload(text=payload_text),
    )


class _FakeForumClient:
    base_url = "https://example.com"

    def __init__(self, login_status_exception: Exception | None = None):
        self.login_status_exception = login_status_exception
        self.login_calls = 0

    async def async_check_login_status(self) -> bool:
        if self.login_status_exception is not None:
            raise self.login_status_exception
        return True

    async def async_login(self) -> bool:
        self.login_calls += 1
        return True

    async def fetch_latest_posts_page(self) -> FetchedLatestPostsPage:
        return FetchedLatestPostsPage(
            url="https://example.com/forum.php?mod=guide&view=newthread",
            html="<html></html>",
            fetched_at=datetime(2026, 5, 30, 12, 41),
        )


class _FakeTelegramClient:
    def __init__(self, *, channel_send_success: bool = True):
        self.channel_send_success = channel_send_success
        self.channel_payloads: list[tuple[int, TelegramPayload]] = []
        self.user_payloads: list[tuple[int, TelegramPayload]] = []
        self.notifications: list[tuple[int, str]] = []

    async def send_payload_to_channel(self, channel_id: int, payload: TelegramPayload) -> bool:
        self.channel_payloads.append((channel_id, payload))
        return self.channel_send_success

    async def send_payload_to_user(self, user_id: int, payload: TelegramPayload) -> bool:
        self.user_payloads.append((user_id, payload))
        return True

    async def send_admin_notification(self, admin_id: int, message: str, captcha_image=None) -> bool:
        self.notifications.append((admin_id, message))
        return True


class _BlockingTelegramClient(_FakeTelegramClient):
    def __init__(self):
        super().__init__()
        self.channel_send_started = asyncio.Event()
        self.release_channel_send = asyncio.Event()

    async def send_payload_to_channel(self, channel_id: int, payload: TelegramPayload) -> bool:
        self.channel_payloads.append((channel_id, payload))
        self.channel_send_started.set()
        await self.release_channel_send.wait()
        return True


class _FakePostProcessingService:
    def __init__(
        self,
        payload_text: str = "structured",
        fail_ids: tuple[int, ...] = (),
        exception_by_id: dict[int, Exception] | None = None,
    ):
        self.payload_text = payload_text
        self.fail_ids = set(fail_ids)
        self.exception_by_id = exception_by_id or {}
        self.calls: list[int] = []

    async def process_thread(self, thread_id: int) -> ProcessedThread:
        self.calls.append(thread_id)
        if thread_id in self.exception_by_id:
            raise self.exception_by_id[thread_id]
        if thread_id in self.fail_ids:
            raise RuntimeError("boom")
        return _make_processed_thread(thread_id, self.payload_text)


class _FakeLatestPostsExtractor:
    def __init__(self, post_ids: tuple[int, ...] = (101,)):
        self.post_ids = post_ids

    def extract(self, page, *, base_url, limit=None):
        posts = [
            ForumPost(
                id=post_id,
                title=f"最新帖子 {post_id}",
                url=f"{base_url}/t{post_id}-1-1",
                author="列表作者",
            )
            for post_id in self.post_ids
        ]
        return posts[:limit] if limit is not None else posts


class PostServiceRolloutTests(unittest.IsolatedAsyncioTestCase):
    async def test_unavailable_post_sends_forum_message_and_continues_polling(self):
        with TemporaryDirectory() as work_dir:
            forum_message = "抱歉，指定的主题不存在或已被删除或正在被审核"
            telegram_client = _FakeTelegramClient()
            post_processing_service = _FakePostProcessingService(
                payload_text="structured",
                exception_by_id={
                    101: ForumThreadUnavailableException(101, forum_message),
                },
            )

            service = PostService(
                cast(Any, _FakeForumClient()),
                cast(Any, telegram_client),
                100,
                200,
                work_dir=work_dir,
                post_processing_service=cast(Any, post_processing_service),
                latest_posts_extractor=cast(Any, _FakeLatestPostsExtractor((101, 102))),
            )

            with patch("services.post_service.asyncio.sleep", new=_immediate_sleep):
                await service.check_and_send_new_posts()

            self.assertEqual(post_processing_service.calls, [101, 102])
            self.assertEqual(len(telegram_client.channel_payloads), 2)
            self.assertIn("<b>最新帖子 101</b>", telegram_client.channel_payloads[0][1].text)
            self.assertIn("列表作者", telegram_client.channel_payloads[0][1].text)
            self.assertIn(f"论坛提示：{forum_message}", telegram_client.channel_payloads[0][1].text)
            self.assertEqual(telegram_client.channel_payloads[1][1].text, "structured")
            self.assertEqual(telegram_client.notifications, [])
            self.assertEqual(service.processed_posts, {101, 102})

            with open(f"{work_dir}/processed_posts.json", "r", encoding="utf-8") as file_handle:
                persisted = json.load(file_handle)

            self.assertEqual(persisted["posts"], [102, 101])

    async def test_unavailable_post_is_not_processed_when_channel_send_fails(self):
        with TemporaryDirectory() as work_dir:
            telegram_client = _FakeTelegramClient(channel_send_success=False)
            post_processing_service = _FakePostProcessingService(
                exception_by_id={
                    101: ForumThreadUnavailableException(101, "论坛提示"),
                },
            )

            service = PostService(
                cast(Any, _FakeForumClient()),
                cast(Any, telegram_client),
                100,
                200,
                work_dir=work_dir,
                post_processing_service=cast(Any, post_processing_service),
                latest_posts_extractor=cast(Any, _FakeLatestPostsExtractor((101,))),
            )

            await service.check_and_send_new_posts()

            self.assertEqual(len(telegram_client.channel_payloads), 1)
            self.assertNotIn(101, service.processed_posts)
            self.assertEqual(list(service._pending_posts), [101])
            self.assertEqual(telegram_client.notifications, [])

    async def test_overlapping_polls_enqueue_each_post_once_during_blocked_delivery(self):
        with TemporaryDirectory() as work_dir:
            telegram_client = _BlockingTelegramClient()
            post_processing_service = _FakePostProcessingService()
            latest_posts_extractor = _FakeLatestPostsExtractor((101,))

            service = PostService(
                cast(Any, _FakeForumClient()),
                cast(Any, telegram_client),
                100,
                200,
                work_dir=work_dir,
                post_processing_service=cast(Any, post_processing_service),
                latest_posts_extractor=cast(Any, latest_posts_extractor),
            )

            with patch("services.post_service.asyncio.sleep", new=_immediate_sleep):
                first_poll = asyncio.create_task(service.check_and_send_new_posts())
                await asyncio.wait_for(
                    telegram_client.channel_send_started.wait(),
                    timeout=1,
                )

                latest_posts_extractor.post_ids = (101, 102)
                await asyncio.wait_for(service.check_and_send_new_posts(), timeout=1)

                self.assertEqual(post_processing_service.calls, [101])
                self.assertEqual(len(telegram_client.channel_payloads), 1)
                self.assertEqual(list(service._pending_posts), [101, 102])

                telegram_client.release_channel_send.set()
                await asyncio.wait_for(first_poll, timeout=1)

            self.assertEqual(post_processing_service.calls, [101, 102])
            self.assertEqual(len(telegram_client.channel_payloads), 2)
            self.assertEqual(service.processed_posts, {101, 102})
            self.assertEqual(service._pending_posts, {})

    async def test_failed_delivery_stays_deduplicated_and_retries_without_new_posts(self):
        with TemporaryDirectory() as work_dir:
            telegram_client = _FakeTelegramClient(channel_send_success=False)
            post_processing_service = _FakePostProcessingService()
            latest_posts_extractor = _FakeLatestPostsExtractor((101,))

            service = PostService(
                cast(Any, _FakeForumClient()),
                cast(Any, telegram_client),
                100,
                200,
                work_dir=work_dir,
                post_processing_service=cast(Any, post_processing_service),
                latest_posts_extractor=cast(Any, latest_posts_extractor),
            )

            await service.check_and_send_new_posts()
            await service.check_and_send_new_posts()

            self.assertEqual(list(service._pending_posts), [101])
            self.assertEqual(post_processing_service.calls, [101, 101])
            self.assertEqual(len(telegram_client.channel_payloads), 2)

            telegram_client.channel_send_success = True
            latest_posts_extractor.post_ids = ()
            with patch("services.post_service.asyncio.sleep", new=_immediate_sleep):
                await service.check_and_send_new_posts()

            self.assertEqual(post_processing_service.calls, [101, 101, 101])
            self.assertEqual(len(telegram_client.channel_payloads), 3)
            self.assertEqual(service.processed_posts, {101})
            self.assertEqual(service._pending_posts, {})

    async def test_single_unavailable_thread_returns_forum_message_to_requester(self):
        with TemporaryDirectory() as work_dir:
            telegram_client = _FakeTelegramClient()
            post_processing_service = _FakePostProcessingService(
                exception_by_id={
                    303: ForumThreadUnavailableException(
                        303,
                        "抱歉，您没有权限访问该版块",
                    ),
                },
            )

            service = PostService(
                cast(Any, _FakeForumClient()),
                cast(Any, telegram_client),
                100,
                200,
                work_dir=work_dir,
                post_processing_service=cast(Any, post_processing_service),
                latest_posts_extractor=cast(Any, _FakeLatestPostsExtractor()),
            )

            success = await service.process_single_thread(303, 404)

            self.assertFalse(success)
            self.assertEqual(telegram_client.channel_payloads, [])
            self.assertEqual(
                telegram_client.notifications,
                [(404, "论坛提示：抱歉，您没有权限访问该版块")],
            )

    async def test_unclassified_polling_error_still_notifies_admin(self):
        with TemporaryDirectory() as work_dir:
            telegram_client = _FakeTelegramClient()
            post_processing_service = _FakePostProcessingService(fail_ids=(101,))

            service = PostService(
                cast(Any, _FakeForumClient()),
                cast(Any, telegram_client),
                100,
                200,
                work_dir=work_dir,
                post_processing_service=cast(Any, post_processing_service),
                latest_posts_extractor=cast(Any, _FakeLatestPostsExtractor((101, 102))),
            )

            await service.check_and_send_new_posts()

            self.assertEqual(telegram_client.channel_payloads, [])
            self.assertNotIn(101, service.processed_posts)
            self.assertEqual(post_processing_service.calls, [101])
            self.assertEqual(list(service._pending_posts), [101, 102])
            self.assertEqual(
                telegram_client.notifications,
                [(200, "检查新帖子时出错: boom")],
            )

    async def test_channel_delivery_uses_structured_payload(self):
        with TemporaryDirectory() as work_dir:
            telegram_client = _FakeTelegramClient()
            post_processing_service = _FakePostProcessingService(payload_text="structured")

            service = PostService(
                cast(Any, _FakeForumClient()),
                cast(Any, telegram_client),
                100,
                200,
                work_dir=work_dir,
                post_processing_service=cast(Any, post_processing_service),
                latest_posts_extractor=cast(Any, _FakeLatestPostsExtractor()),
            )

            with patch("services.post_service.asyncio.sleep", new=_immediate_sleep):
                await service.check_and_send_new_posts()

            self.assertEqual(post_processing_service.calls, [101])
            self.assertEqual(len(telegram_client.channel_payloads), 1)
            self.assertEqual(telegram_client.channel_payloads[0][1].text, "structured")
            self.assertEqual(telegram_client.notifications, [])

    async def test_single_thread_uses_structured_payload(self):
        with TemporaryDirectory() as work_dir:
            telegram_client = _FakeTelegramClient()
            post_processing_service = _FakePostProcessingService(payload_text="structured-user")

            service = PostService(
                cast(Any, _FakeForumClient()),
                cast(Any, telegram_client),
                100,
                200,
                work_dir=work_dir,
                post_processing_service=cast(Any, post_processing_service),
                latest_posts_extractor=cast(Any, _FakeLatestPostsExtractor()),
            )

            success = await service.process_single_thread(303, 404)

            self.assertTrue(success)
            self.assertEqual(post_processing_service.calls, [303])
            self.assertEqual(len(telegram_client.user_payloads), 1)
            self.assertEqual(telegram_client.user_payloads[0][0], 404)
            self.assertEqual(telegram_client.user_payloads[0][1].text, "structured-user")

    async def test_single_thread_processing_error_notifies_user_without_fallback(self):
        with TemporaryDirectory() as work_dir:
            telegram_client = _FakeTelegramClient()
            post_processing_service = _FakePostProcessingService(
                exception_by_id={303: RuntimeError("boom")}
            )

            service = PostService(
                cast(Any, _FakeForumClient()),
                cast(Any, telegram_client),
                100,
                200,
                work_dir=work_dir,
                post_processing_service=cast(Any, post_processing_service),
                latest_posts_extractor=cast(Any, _FakeLatestPostsExtractor()),
            )

            success = await service.process_single_thread(303, 404)

            self.assertFalse(success)
            self.assertEqual(post_processing_service.calls, [303])
            self.assertEqual(telegram_client.user_payloads, [])
            self.assertEqual(
                telegram_client.notifications,
                [(404, "无法获取帖子内容，可能是链接无效或需要权限")],
            )

    async def test_network_failure_after_first_success_still_persists_processed_ids(self):
        with TemporaryDirectory() as work_dir:
            telegram_client = _FakeTelegramClient()
            post_processing_service = _FakePostProcessingService(
                payload_text="structured",
                exception_by_id={102: ForumTransportException("temporary eof")},
            )

            service = PostService(
                cast(Any, _FakeForumClient()),
                cast(Any, telegram_client),
                100,
                200,
                work_dir=work_dir,
                post_processing_service=cast(Any, post_processing_service),
                latest_posts_extractor=cast(Any, _FakeLatestPostsExtractor((101, 102))),
            )

            with patch("services.post_service.asyncio.sleep", new=_immediate_sleep):
                await service.check_and_send_new_posts()

            self.assertEqual([payload.text for _, payload in telegram_client.channel_payloads], ["structured"])
            self.assertIn(101, service.processed_posts)
            self.assertNotIn(102, service.processed_posts)
            self.assertEqual(list(service._pending_posts), [102])

            with open(f"{work_dir}/processed_posts.json", "r", encoding="utf-8") as file_handle:
                persisted = json.load(file_handle)

            self.assertEqual(persisted["posts"], [101])

    async def test_transport_error_during_polling_skips_relogin(self):
        with TemporaryDirectory() as work_dir:
            forum_client = _FakeForumClient(
                login_status_exception=ForumTransportException("temporary eof")
            )
            telegram_client = _FakeTelegramClient()

            service = PostService(
                cast(Any, forum_client),
                cast(Any, telegram_client),
                100,
                200,
                work_dir=work_dir,
                post_processing_service=cast(Any, _FakePostProcessingService()),
                latest_posts_extractor=cast(Any, _FakeLatestPostsExtractor()),
            )

            await service.check_and_send_new_posts()

            self.assertEqual(forum_client.login_calls, 0)
            self.assertEqual(telegram_client.notifications, [])
            self.assertEqual(telegram_client.channel_payloads, [])


if __name__ == "__main__":
    unittest.main()
