from __future__ import annotations

from datetime import datetime
import json
from tempfile import TemporaryDirectory
from typing import Any, cast
import unittest

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
    def __init__(self):
        self.channel_payloads: list[tuple[int, TelegramPayload]] = []
        self.user_payloads: list[tuple[int, TelegramPayload]] = []
        self.notifications: list[tuple[int, str]] = []

    async def send_payload_to_channel(self, channel_id: int, payload: TelegramPayload) -> bool:
        self.channel_payloads.append((channel_id, payload))
        return True

    async def send_payload_to_user(self, user_id: int, payload: TelegramPayload) -> bool:
        self.user_payloads.append((user_id, payload))
        return True

    async def send_admin_notification(self, admin_id: int, message: str, captcha_image=None) -> bool:
        self.notifications.append((admin_id, message))
        return True

    def build_legacy_payload_for_post(
        self,
        post: ForumPost,
        *,
        disable_web_page_preview: bool,
    ) -> TelegramPayload:
        return TelegramPayload(
            text=f"legacy:{post.id}:{post.content}",
            disable_web_page_preview=disable_web_page_preview,
        )


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

    def extract(self, page, *, base_url, details_loader, limit=None):
        posts = [
            ForumPost(
                id=post_id,
                title=f"最新帖子 {post_id}",
                url=f"{base_url}/t{post_id}-1-1",
                author="列表作者",
                details_loader=details_loader,
            )
            for post_id in self.post_ids
        ]
        return posts[:limit] if limit is not None else posts


class _FakeLegacyPostLoader:
    def __init__(self, exception_to_raise: Exception | None = None):
        self.loaded_ids: list[int] = []
        self.created_ids: list[int] = []
        self.exception_to_raise = exception_to_raise

    def load_post_details(self, thread_id: int):
        if self.exception_to_raise is not None:
            raise self.exception_to_raise
        self.loaded_ids.append(thread_id)
        return {
            "title": f"legacy {thread_id}",
            "author": "兼容作者",
            "content": "兼容正文",
            "publish_time": datetime(2026, 5, 30, 12, 42),
            "images": [],
            "tags": [],
        }

    def create_post(self, thread_id: int, *, title=None, author=None, url=None):
        self.created_ids.append(thread_id)
        return ForumPost(
            id=thread_id,
            title=title or f"帖子 {thread_id}",
            url=url or f"https://example.com/t{thread_id}-1-1",
            author=author or "未知作者",
            details_loader=self.load_post_details,
        )


class PostServiceRolloutTests(unittest.IsolatedAsyncioTestCase):
    async def test_compare_mode_sends_structured_payload_and_reports_diff(self):
        with TemporaryDirectory() as work_dir:
            telegram_client = _FakeTelegramClient()
            post_processing_service = _FakePostProcessingService(payload_text="structured")
            legacy_post_loader = _FakeLegacyPostLoader()

            service = PostService(
                cast(Any, _FakeForumClient()),
                cast(Any, telegram_client),
                100,
                200,
                work_dir=work_dir,
                post_processing_service=cast(Any, post_processing_service),
                latest_posts_extractor=cast(Any, _FakeLatestPostsExtractor()),
                legacy_post_loader=cast(Any, legacy_post_loader),
                structured_pipeline_mode="compare",
            )

            await service.check_and_send_new_posts()

            self.assertEqual(post_processing_service.calls, [101])
            self.assertEqual(legacy_post_loader.loaded_ids, [101])
            self.assertEqual(len(telegram_client.channel_payloads), 1)
            self.assertEqual(telegram_client.channel_payloads[0][1].text, "structured")
            self.assertEqual(len(telegram_client.notifications), 1)
            self.assertIn("text", telegram_client.notifications[0][1])

    async def test_legacy_mode_uses_legacy_payload_for_single_thread(self):
        with TemporaryDirectory() as work_dir:
            telegram_client = _FakeTelegramClient()
            post_processing_service = _FakePostProcessingService(payload_text="should-not-be-used")
            legacy_post_loader = _FakeLegacyPostLoader()

            service = PostService(
                cast(Any, _FakeForumClient()),
                cast(Any, telegram_client),
                100,
                200,
                work_dir=work_dir,
                post_processing_service=cast(Any, post_processing_service),
                latest_posts_extractor=cast(Any, _FakeLatestPostsExtractor()),
                legacy_post_loader=cast(Any, legacy_post_loader),
                structured_pipeline_mode="legacy",
            )

            success = await service.process_single_thread(303, 404)

            self.assertTrue(success)
            self.assertEqual(post_processing_service.calls, [])
            self.assertEqual(legacy_post_loader.created_ids, [303])
            self.assertEqual(legacy_post_loader.loaded_ids, [303])
            self.assertEqual(len(telegram_client.user_payloads), 1)
            self.assertEqual(telegram_client.user_payloads[0][0], 404)
            self.assertIn("legacy:303:兼容正文", telegram_client.user_payloads[0][1].text)

    async def test_compare_mode_keeps_structured_send_when_legacy_compare_hits_transport_error(self):
        with TemporaryDirectory() as work_dir:
            telegram_client = _FakeTelegramClient()
            post_processing_service = _FakePostProcessingService(payload_text="structured")
            legacy_post_loader = _FakeLegacyPostLoader(
                exception_to_raise=ForumTransportException("temporary eof")
            )

            service = PostService(
                cast(Any, _FakeForumClient()),
                cast(Any, telegram_client),
                100,
                200,
                work_dir=work_dir,
                post_processing_service=cast(Any, post_processing_service),
                latest_posts_extractor=cast(Any, _FakeLatestPostsExtractor()),
                legacy_post_loader=cast(Any, legacy_post_loader),
                structured_pipeline_mode="compare",
            )

            await service.check_and_send_new_posts()

            self.assertEqual(post_processing_service.calls, [101])
            self.assertEqual(len(telegram_client.channel_payloads), 1)
            self.assertEqual(telegram_client.channel_payloads[0][1].text, "structured")
            self.assertEqual(telegram_client.notifications, [])

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
                legacy_post_loader=cast(Any, _FakeLegacyPostLoader()),
                structured_pipeline_mode="structured",
            )

            await service.check_and_send_new_posts()

            self.assertEqual([payload.text for _, payload in telegram_client.channel_payloads], ["structured"])
            self.assertIn(101, service.processed_posts)
            self.assertNotIn(102, service.processed_posts)

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
                legacy_post_loader=cast(Any, _FakeLegacyPostLoader()),
                structured_pipeline_mode="structured",
            )

            await service.check_and_send_new_posts()

            self.assertEqual(forum_client.login_calls, 0)
            self.assertEqual(telegram_client.notifications, [])
            self.assertEqual(telegram_client.channel_payloads, [])


if __name__ == "__main__":
    unittest.main()