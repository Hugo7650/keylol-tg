from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs
import unittest

import httpx

from clients.forum_client import ForumClient
from clients.forum_client import ForumTransportException
from infrastructure.services.latest_posts_page_extractor import KeylolLatestPostsPageExtractor
from infrastructure.services.legacy_forum_post_loader import LegacyForumPostLoader
from infrastructure.services import KeylolForumContentParser
from infrastructure.services import KeylolThreadPageExtractor


class ForumClientAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_async_login_status_and_page_fetches(self):
        login_page_html = (
            '<html><head><meta charset="utf-8" /></head><body><form name="login" id="loginform_abc">'
            '<input name="formhash" value="hash123" /></form></body></html>'
        )
        list_page_html = (
            '<html><head><meta charset="utf-8" /></head><body><section id="nav-additional"></section><div id="forumnew"></div>'
            '<table><tbody><tr><th class="common"><a href="t321-1-1">帖子标题</a></th>'
            '<td class="by"><cite><a>作者甲</a></cite></td></tr></tbody></table></body></html>'
        )
        base_page_html = '<html><head><meta charset="utf-8" /></head><body><section id="nav-additional"></section></body></html>'
        thread_page_html = '<html><head><meta charset="utf-8" /></head><body>线程正文</body></html>'

        async def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "member.php" in url and request.method == "GET":
                return httpx.Response(200, text=login_page_html, request=request)
            if "member.php" in url and request.method == "POST":
                body = (await request.aread()).decode()
                data = parse_qs(body)
                self.assertEqual(data["username"][0], "user")
                self.assertEqual(data["password"][0], "pass")
                return httpx.Response(200, text="reload https://example.com/", request=request)
            if url == "https://example.com":
                return httpx.Response(200, text=base_page_html, request=request)
            if "forum.php?mod=guide&view=newthread" in url:
                return httpx.Response(200, text=list_page_html, request=request)
            if url == "https://example.com/t321-1-1":
                return httpx.Response(200, text=thread_page_html, request=request)
            return httpx.Response(404, text="not found", request=request)

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport, follow_redirects=True) as client:
            forum_client = ForumClient(
                "https://example.com",
                "user",
                "pass",
                async_http_client=client,
            )

            self.assertTrue(await forum_client.async_login())
            self.assertTrue(await forum_client.async_check_login_status())

            latest_posts_page = await forum_client.fetch_latest_posts_page()
            thread_page = await forum_client.fetch_thread_page(321)

            self.assertIn("帖子标题", latest_posts_page.html)
            self.assertEqual(thread_page.thread_id, 321)
            self.assertIn("线程正文", thread_page.html)

    async def test_async_login_handles_duplicate_cookie_names(self):
        login_page_html = (
            '<html><head><meta charset="utf-8" /></head><body><form name="login" id="loginform_dup">'
            '<input name="formhash" value="hash789" /></form></body></html>'
        )

        async def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "member.php" in url and request.method == "GET":
                return httpx.Response(
                    200,
                    text=login_page_html,
                    headers=[
                        ("set-cookie", "dz_2132_sid=abc; Path=/; Domain=example.com"),
                        ("set-cookie", "dz_2132_sid=def; Path=/member.php; Domain=example.com"),
                    ],
                    request=request,
                )
            if "member.php" in url and request.method == "POST":
                return httpx.Response(
                    200,
                    text="reload https://example.com/",
                    headers=[
                        ("set-cookie", "dz_2132_auth=token; Path=/; Domain=example.com"),
                    ],
                    request=request,
                )
            return httpx.Response(404, text="not found", request=request)

        transport = httpx.MockTransport(handler)
        with TemporaryDirectory() as work_dir:
            async with httpx.AsyncClient(transport=transport, follow_redirects=True) as client:
                forum_client = ForumClient(
                    "https://example.com",
                    "user",
                    "pass",
                    work_dir=work_dir,
                    async_http_client=client,
                )

                self.assertTrue(await forum_client.async_login())

            reloaded_client = ForumClient(
                "https://example.com",
                "user",
                "pass",
                work_dir=work_dir,
            )

            duplicate_sid_cookies = [
                cookie
                for cookie in reloaded_client._cookies.jar
                if cookie.name == "dz_2132_sid"
            ]
            self.assertTrue(reloaded_client.is_logged_in)
            self.assertEqual(len(duplicate_sid_cookies), 2)
            forum_client.is_logged_in = False
            reloaded_client.is_logged_in = False

    async def test_async_check_login_status_retries_transient_transport_errors(self):
        attempts = 0
        base_page_html = '<html><head><meta charset="utf-8" /></head><body><section id="nav-additional"></section></body></html>'

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            if str(request.url) == "https://example.com" and attempts < 3:
                raise httpx.ConnectError("temporary eof", request=request)
            return httpx.Response(200, text=base_page_html, request=request)

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport, follow_redirects=True) as client:
            forum_client = ForumClient(
                "https://example.com",
                "user",
                "pass",
                async_http_client=client,
                request_retries=2,
                retry_backoff=0,
            )
            forum_client.is_logged_in = True

            self.assertTrue(await forum_client.async_check_login_status())
            self.assertEqual(attempts, 3)

    async def test_async_check_login_status_raises_transport_exception_after_retry_budget(self):
        attempts = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            raise httpx.ConnectError("still broken", request=request)

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport, follow_redirects=True) as client:
            forum_client = ForumClient(
                "https://example.com",
                "user",
                "pass",
                async_http_client=client,
                request_retries=1,
                retry_backoff=0,
            )
            forum_client.is_logged_in = True

            with self.assertRaises(ForumTransportException):
                await forum_client.async_check_login_status()

            self.assertTrue(forum_client.is_logged_in)
            self.assertEqual(attempts, 2)


class ForumClientSyncCompatibilityTests(unittest.TestCase):
    def test_sync_login_status_and_page_fetches_use_httpx(self):
        login_page_html = (
            '<html><head><meta charset="utf-8" /></head><body><form name="login" id="loginform_sync">'
            '<input name="formhash" value="hash456" /></form></body></html>'
        )
        list_page_html = (
            '<html><head><meta charset="utf-8" /></head><body><section id="nav-additional"></section><div id="forumnew"></div>'
            '<table><tbody><tr><th class="common"><a href="t654-1-1">同步帖子</a></th>'
            '<td class="by"><cite><a>同步作者</a></cite></td></tr></tbody></table></body></html>'
        )
        base_page_html = '<html><head><meta charset="utf-8" /></head><body><section id="nav-additional"></section></body></html>'
        thread_page_html = '<html><head><meta charset="utf-8" /></head><body>同步线程正文</body></html>'

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "member.php" in url and request.method == "GET":
                return httpx.Response(200, text=login_page_html, request=request)
            if "member.php" in url and request.method == "POST":
                data = parse_qs(request.content.decode())
                self.assertEqual(data["username"][0], "user")
                self.assertEqual(data["password"][0], "pass")
                return httpx.Response(200, text="reload https://example.com/", request=request)
            if url == "https://example.com":
                return httpx.Response(200, text=base_page_html, request=request)
            if "forum.php?mod=guide&view=newthread" in url:
                return httpx.Response(200, text=list_page_html, request=request)
            if url == "https://example.com/t654-1-1":
                return httpx.Response(200, text=thread_page_html, request=request)
            return httpx.Response(404, text="not found", request=request)

        forum_client = ForumClient(
            "https://example.com",
            "user",
            "pass",
            sync_http_transport=httpx.MockTransport(handler),
        )

        self.assertTrue(forum_client.login())
        self.assertTrue(forum_client.check_login_status())

        latest_posts_page = forum_client.fetch_latest_posts_page_sync()
        thread_page = forum_client.fetch_thread_page_sync(654)

        self.assertIn("同步帖子", latest_posts_page.html)
        self.assertEqual(thread_page.thread_id, 654)
        self.assertIn("同步线程正文", thread_page.html)

    def test_split_extractors_build_posts_and_legacy_details(self):
        list_page_html = (
            '<html><head><meta charset="utf-8" /></head><body><section id="nav-additional"></section><div id="forumnew"></div>'
            '<table><tbody><tr><th class="common"><a href="t654-1-1">同步帖子</a></th>'
            '<td class="by"><cite><a>同步作者</a></cite></td></tr></tbody></table></body></html>'
        )
        fixture_path = Path(__file__).parent / "case" / "t1009483-1-1.htm"
        html = fixture_path.read_text(encoding="utf-8")

        def handler(request: httpx.Request) -> httpx.Response:
            if str(request.url) == "https://example.com/t1009483-1-1":
                return httpx.Response(200, text=html, request=request)
            return httpx.Response(404, text="not found", request=request)

        forum_client = ForumClient(
            "https://example.com",
            "user",
            "pass",
            sync_http_transport=httpx.MockTransport(handler),
        )
        forum_client.is_logged_in = True

        latest_posts_extractor = KeylolLatestPostsPageExtractor()
        legacy_post_loader = LegacyForumPostLoader(
            forum_client,
            KeylolThreadPageExtractor(),
            KeylolForumContentParser(),
            base_url=forum_client.base_url,
        )

        latest_posts_page = forum_client._build_latest_posts_page(  # type: ignore[attr-defined]
            httpx.Response(200, text=list_page_html, request=httpx.Request("GET", "https://example.com/forum.php?mod=guide&view=newthread"))
        )
        posts = latest_posts_extractor.extract(
            latest_posts_page,
            base_url=forum_client.base_url,
            details_loader=legacy_post_loader.load_post_details,
        )

        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0].id, 654)
        self.assertEqual(posts[0].author, "同步作者")

        details = legacy_post_loader.load_post_details(1009483)

        self.assertIsNotNone(details)
        assert details is not None
        self.assertNotEqual(details["title"], "未知标题")
        self.assertTrue(details["content"])
        self.assertNotEqual(details["author"], "未知作者")

    def test_legacy_post_loader_propagates_transport_errors(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("temporary eof", request=request)

        forum_client = ForumClient(
            "https://example.com",
            "user",
            "pass",
            sync_http_transport=httpx.MockTransport(handler),
            request_retries=0,
            retry_backoff=0,
        )
        forum_client.is_logged_in = True

        legacy_post_loader = LegacyForumPostLoader(
            forum_client,
            KeylolThreadPageExtractor(),
            KeylolForumContentParser(),
            base_url=forum_client.base_url,
        )

        with self.assertRaises(ForumTransportException):
            legacy_post_loader.load_post_details(1009483)


if __name__ == "__main__":
    unittest.main()