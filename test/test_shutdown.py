from __future__ import annotations

import asyncio
import logging
import signal
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from main import KeylolTelegramApp
from services.scheduler import TaskScheduler


class ShutdownTests(unittest.IsolatedAsyncioTestCase):
    def make_app(self):
        with patch("main.Config") as config, patch.object(
            KeylolTelegramApp, "_setup_logging", return_value=logging.getLogger(__name__)
        ):
            config.return_value = SimpleNamespace(
                telegram_admin_id=1, validate=lambda: True
            )
            app = KeylolTelegramApp()
        app.SHUTDOWN_TIMEOUT = 0.02
        return app

    async def test_notification_timeout_still_closes_clients_once(self):
        app = self.make_app()
        cancelled = asyncio.Event()

        async def disconnected_notification(*args):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        app.scheduler = SimpleNamespace(stop=AsyncMock())
        app.telegram_client = SimpleNamespace(
            send_admin_notification=AsyncMock(side_effect=disconnected_notification),
            stop=AsyncMock(),
        )
        app.forum_client = SimpleNamespace(aclose=AsyncMock())
        await asyncio.wait_for(asyncio.gather(app.stop(), app.stop()), 1)
        self.assertTrue(cancelled.is_set())
        self.assertTrue(app._should_exit.is_set())
        app.scheduler.stop.assert_awaited_once()
        app.telegram_client.send_admin_notification.assert_awaited_once()
        app.telegram_client.stop.assert_awaited_once()
        app.forum_client.aclose.assert_awaited_once()

    async def test_client_stop_error_still_closes_forum(self):
        app = self.make_app()
        app.telegram_client = SimpleNamespace(
            send_admin_notification=AsyncMock(),
            stop=AsyncMock(side_effect=RuntimeError("connection lost")),
        )
        app.forum_client = SimpleNamespace(aclose=AsyncMock())
        await app.stop()
        app.forum_client.aclose.assert_awaited_once()
        self.assertTrue(app._should_exit.is_set())

    async def test_signal_cancels_initial_poll_and_restores_handlers(self):
        app = self.make_app()
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def poll():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        app._initialize_components = AsyncMock()
        app.scheduler = SimpleNamespace(start=Mock(), stop=AsyncMock())
        app.post_service = SimpleNamespace(check_and_send_new_posts=poll)
        previous = signal.getsignal(signal.SIGINT)
        task = asyncio.create_task(app.start())
        await asyncio.wait_for(started.wait(), 1)
        app._signal_handler(signal.SIGINT, None)
        await asyncio.wait_for(task, 1)
        self.assertTrue(cancelled.is_set())
        self.assertTrue(app._should_exit.is_set())
        self.assertEqual(signal.getsignal(signal.SIGINT), previous)

    async def test_second_signal_forces_exit(self):
        app = self.make_app()
        app._main_task = Mock()
        app._loop = Mock()
        with patch("main.os._exit") as force_exit:
            app._signal_handler(signal.SIGINT, None)
            app._signal_handler(signal.SIGINT, None)
        force_exit.assert_called_once_with(130)

    async def test_partial_initialization_failure_runs_cleanup(self):
        app = self.make_app()
        app.forum_client = SimpleNamespace(aclose=AsyncMock())
        app._initialize_components = AsyncMock(side_effect=RuntimeError("startup failed"))
        self.assertFalse(await app.start())
        app.forum_client.aclose.assert_awaited_once()

    async def test_scheduler_cancels_running_jobs_and_rejects_late_jobs(self):
        scheduler = TaskScheduler(asyncio.get_running_loop())
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def job():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        scheduler.is_running = True
        scheduler._start_job(job, (), {})
        await asyncio.wait_for(started.wait(), 1)
        await scheduler.stop()
        self.assertTrue(cancelled.is_set())
        self.assertFalse(scheduler._tasks)
        late_job = AsyncMock()
        scheduler._start_job(late_job, (), {})
        late_job.assert_not_called()


if __name__ == "__main__":
    unittest.main()
