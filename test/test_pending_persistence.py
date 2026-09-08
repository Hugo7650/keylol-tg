from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast
import unittest
from unittest.mock import AsyncMock, patch

from clients.forum_client import ForumThreadUnavailableException, ForumTransportException
from services.post_service import PostService
from test.test_post_service_rollout import (
    _FakeForumClient, _FakeLatestPostsExtractor, _FakePostProcessingService,
    _FakeTelegramClient, _immediate_sleep,
)


class PendingPersistenceTests(unittest.IsolatedAsyncioTestCase):
    def make_service(self, directory, ids=(), telegram=None, processing=None):
        return PostService(
            cast(Any, _FakeForumClient()),
            cast(Any, telegram or _FakeTelegramClient()), 100, 200,
            max_posts=500, work_dir=directory,
            post_processing_service=cast(Any, processing or _FakePostProcessingService()),
            latest_posts_extractor=cast(Any, _FakeLatestPostsExtractor(ids)),
        )

    async def test_restart_retries_regular_and_notice_posts_then_removes_them(self):
        for unavailable in (False, True):
            with self.subTest(unavailable=unavailable), TemporaryDirectory() as directory:
                processing = _FakePostProcessingService(exception_by_id={
                    101: ForumThreadUnavailableException(101, '论坛提示'),
                } if unavailable else {})
                first = self.make_service(
                    directory, (101, 102),
                    _FakeTelegramClient(channel_send_success=False), processing,
                )
                await first.check_and_send_new_posts()
                restored = self.make_service(directory, processing=processing)
                self.assertEqual(list(restored._pending_posts), [101, 102])
                self.assertEqual(restored._pending_posts, first._pending_posts)
                with patch('services.post_service.asyncio.sleep', new=_immediate_sleep):
                    await restored.check_and_send_new_posts()
                again = self.make_service(directory)
                self.assertEqual(again._pending_posts, {})
                self.assertEqual(again.processed_posts, {101, 102})

    async def test_fetch_failure_preserves_entire_queue_over_200(self):
        with TemporaryDirectory() as directory:
            ids = tuple(range(1, 252))
            service = self.make_service(directory, ids, processing=_FakePostProcessingService(
                exception_by_id={1: ForumTransportException('offline')},
            ))
            await service.check_and_send_new_posts()
            self.assertEqual(list(self.make_service(directory)._pending_posts), list(ids))

    async def test_list_failure_does_not_block_restored_queue(self):
        for error in (ForumTransportException('offline'), ValueError('bad list')):
            with self.subTest(error=error), TemporaryDirectory() as directory:
                first = self.make_service(directory, (101,))
                await first._enqueue_latest_posts()
                restored = self.make_service(directory)
                with (
                    patch.object(restored, '_load_latest_posts', new=AsyncMock(side_effect=error)),
                    patch('services.post_service.asyncio.sleep', new=_immediate_sleep),
                ):
                    await restored.check_and_send_new_posts()
                self.assertEqual(restored.processed_posts, {101})

    def test_legacy_cache_and_pending_deduplication(self):
        with TemporaryDirectory() as directory:
            cache = Path(directory) / 'processed_posts.json'
            cache.write_text(json.dumps({'posts': [101], 'last_post': 101}), encoding='utf-8')
            legacy = self.make_service(directory)
            self.assertEqual(legacy.processed_posts, {101})
            self.assertEqual(legacy._pending_posts, {})
            records = [dict(id=i, title=str(i), author='author', url=f'https://example.com/t{i}-1-1')
                       for i in (103, 101, 102, 103)]
            cache.write_text(json.dumps({'posts': [101], 'pending_posts': records}), encoding='utf-8')
            self.assertEqual(list(self.make_service(directory)._pending_posts), [103, 102])

    async def test_failed_atomic_write_keeps_old_file_and_blocks_delivery(self):
        for operation in ('os.replace', 'os.fsync'):
            with self.subTest(operation=operation), TemporaryDirectory() as directory:
                service = self.make_service(directory, (101,))
                service._save_processed_posts()
                cache = Path(service.cache_file)
                original = cache.read_bytes()
                with patch(f'services.post_service.{operation}', side_effect=OSError('disk failure')):
                    await service.check_and_send_new_posts()
                    await service.check_and_send_new_posts()
                self.assertEqual(cache.read_bytes(), original)
                self.assertEqual(service.telegram_client.channel_payloads, [])
                self.assertEqual(list(service._pending_posts), [101])
                self.assertEqual(list(Path(directory).glob('*.tmp')), [])
                with patch('services.post_service.asyncio.sleep', new=_immediate_sleep):
                    await service.check_and_send_new_posts()
                self.assertEqual(self.make_service(directory).processed_posts, {101})

    async def test_success_save_failure_stops_before_next_post(self):
        with TemporaryDirectory() as directory:
            service = self.make_service(directory, (101, 102))
            await service._enqueue_latest_posts()
            with patch('services.post_service.os.replace', side_effect=OSError('disk failure')):
                await service.check_and_send_new_posts()
            self.assertEqual(len(service.telegram_client.channel_payloads), 1)
            self.assertEqual(list(self.make_service(directory)._pending_posts), [101, 102])
            with patch('services.post_service.asyncio.sleep', new=_immediate_sleep):
                await service.check_and_send_new_posts()
            self.assertEqual(len(service.telegram_client.channel_payloads), 2)
            self.assertEqual(self.make_service(directory).processed_posts, {101, 102})
