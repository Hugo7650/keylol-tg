import asyncio
import httpx
import re
import time
from typing import Optional, Callable
from datetime import datetime
import logging
import pickle
import os
import lxml.etree as etree

from domain.value_objects import FetchedLatestPostsPage
from domain.value_objects import FetchedThreadPage

class ForumLoginException(Exception):
    """论坛登录异常"""
    pass


class ForumTransportException(Exception):
    """论坛网络或传输异常"""
    pass

class CaptchaRequiredException(Exception):
    """需要验证码异常"""
    def __init__(self, captcha_image: bytes, message: str = "需要输入验证码"):
        self.captcha_image = captcha_image
        super().__init__(message)

class ForumClient:
    """论坛客户端"""
    
    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        session_file: Optional[str] = None,
        work_dir: Optional[str] = None,
        *,
        async_timeout: float = 30.0,
        async_http_client: Optional[httpx.AsyncClient] = None,
        sync_http_transport: Optional[httpx.BaseTransport] = None,
        request_retries: int = 2,
        retry_backoff: float = 1.0,
    ):
        self.base_url = base_url.rstrip('/')
        self.username = username
        self.password = password
        self.is_logged_in = False
        self.logger = logging.getLogger(__name__)
        self.async_timeout = async_timeout
        self._async_http_client = async_http_client
        self._owns_async_http_client = async_http_client is None
        self._sync_http_transport = sync_http_transport
        self.request_retries = max(0, request_retries)
        self.retry_backoff = max(0.0, retry_backoff)
        self._headers: dict[str, str] = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36'
        }
        self._cookies = httpx.Cookies()
        
        # 设置 session 文件路径
        if session_file is None:
            self.session_file = f"forum_session_{username}.pkl"
        else:
            self.session_file = session_file
        if work_dir is not None:
            self.session_file = os.path.join(work_dir, self.session_file)
        
        # 尝试加载已保存的 session
        self._load_session()

    async def fetch_thread_page(self, thread_id: int) -> FetchedThreadPage:
        """异步抓取帖子页面原始 HTML。"""
        self.logger.info(f"异步抓取帖子页面: {thread_id}")

        client = self._get_async_http_client()
        return await self._fetch_thread_page_with_client(client, thread_id)

    async def fetch_latest_posts_page(self) -> FetchedLatestPostsPage:
        """异步抓取最新帖子列表页面原始 HTML。"""
        if not self.is_logged_in:
            raise ForumLoginException("未登录，无法获取帖子")

        client = self._get_async_http_client()
        response = await self._send_async_request(
            client,
            "GET",
            f"{self.base_url}/forum.php?mod=guide&view=newthread",
            operation="抓取最新帖子列表",
        )
        return self._build_latest_posts_page(response)

    async def async_login(self, captcha_callback: Optional[Callable[[bytes], str]] = None) -> bool:
        """使用 httpx 异步登录论坛。"""
        if self.is_logged_in and await self.async_check_login_status():
            self.logger.info("已登录，无需重新登录")
            return True

        try:
            client = self._get_async_http_client()
            login_page = await self._send_async_request(
                client,
                "GET",
                f"{self.base_url}/member.php?mod=logging&action=login",
                operation="访问登录页面",
            )
            if login_page.status_code != 200:
                raise ForumLoginException("无法访问登录页面")

            tree = etree.HTML(login_page.content, parser=etree.HTMLParser())
            form = tree.xpath('//form[@name="login"]')[0]
            loginhash = form.xpath('./@id')[0].split('_')[-1]
            formhash = form.xpath('.//input[@name="formhash"]/@value')[0]

            login_data = {
                'duceapp': 'yes',
                'formhash': formhash,
                'referer': f"{self.base_url}/",
                'lssubmit': 'yes',
                'loginfield': 'auto',
                'username': self.username,
                'password': self.password,
                'questionid': '0',
                'answer': '',
                'cookietime': '2592000',
                'smscode': '',
            }

            login_url = (
                f"{self.base_url}/member.php?mod=logging&action=login"
                f"&loginsubmit=yes&loginhash={loginhash}&inajax=1"
            )
            response = await self._send_async_request(
                client,
                "POST",
                login_url,
                operation="提交论坛登录",
                data=login_data,
            )

            if captcha_callback is not None:
                pass

            if "reload" in response.text and self.base_url in response.text:
                self.is_logged_in = True
                self.logger.info("论坛登录成功")
                self._save_session()
                return True

            raise ForumLoginException("登录失败，用户名密码或验证码错误")
        except Exception as e:
            self.logger.error(f"异步登录过程出错: {e}")
            raise

    async def async_check_login_status(self) -> bool:
        """异步检查论坛登录状态。"""
        client = self._get_async_http_client()
        response = await self._send_async_request(
            client,
            "GET",
            self.base_url,
            operation="检查论坛登录状态",
        )

        tree = etree.HTML(response.content, parser=etree.HTMLParser())
        is_valid = not self._is_login_required_response(str(response.url), tree) and self.is_logged_in
        if not is_valid:
            self.is_logged_in = False
        return is_valid

    async def aclose(self):
        """关闭内部 httpx 客户端并持久化 session。"""
        if self._async_http_client is not None and self._owns_async_http_client:
            await self._async_http_client.aclose()
            self._async_http_client = None

        if self.is_logged_in:
            self._save_session()

    def _create_async_http_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            headers=dict(self._headers),
            follow_redirects=True,
            timeout=self.async_timeout,
        )

    def _create_sync_http_client(self) -> httpx.Client:
        return httpx.Client(
            headers=dict(self._headers),
            follow_redirects=True,
            timeout=self.async_timeout,
            transport=self._sync_http_transport,
        )

    def _get_async_http_client(self) -> httpx.AsyncClient:
        if self._async_http_client is None:
            self._async_http_client = self._create_async_http_client()
        return self._async_http_client

    def fetch_thread_page_sync(self, thread_id: int) -> FetchedThreadPage:
        """同步抓取帖子页面原始 HTML。"""
        with self._create_sync_http_client() as client:
            response = self._send_sync_request(
                client,
                "GET",
                f"{self.base_url}/t{thread_id}-1-1",
                operation=f"同步抓取帖子页面 {thread_id}",
            )

            page_html = self._expand_thread_page_with_pagination_sync(
                client,
                thread_id,
                response,
            )

        return self._build_thread_page(thread_id, response, html=page_html)

    def fetch_latest_posts_page_sync(self) -> FetchedLatestPostsPage:
        """同步抓取最新帖子列表页面原始 HTML。"""
        if not self.is_logged_in:
            raise ForumLoginException("未登录，无法获取帖子")

        with self._create_sync_http_client() as client:
            response = self._send_sync_request(
                client,
                "GET",
                f"{self.base_url}/forum.php?mod=guide&view=newthread",
                operation="同步抓取最新帖子列表",
            )

        return self._build_latest_posts_page(response)

    async def _fetch_thread_page_with_client(
        self,
        client: httpx.AsyncClient,
        thread_id: int,
    ) -> FetchedThreadPage:
        response = await self._send_async_request(
            client,
            "GET",
            f"{self.base_url}/t{thread_id}-1-1",
            operation=f"抓取帖子页面 {thread_id}",
        )

        page_html = await self._expand_thread_page_with_pagination_async(
            client,
            thread_id,
            response,
        )

        return self._build_thread_page(thread_id, response, html=page_html)

    async def _send_async_request(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        operation: str,
        **kwargs,
    ) -> httpx.Response:
        for attempt in range(self.request_retries + 1):
            self._sync_shared_state_to_client(client)
            try:
                response = await client.request(method, url, **kwargs)
                self._sync_client_to_shared_state(client)
            except httpx.RequestError as exc:
                if attempt >= self.request_retries:
                    raise ForumTransportException(f"{operation}失败: {exc}") from exc

                await self._wait_before_retry_async(operation, attempt, exc)
                continue

            if self._is_retryable_status(response.status_code):
                if attempt >= self.request_retries:
                    raise ForumTransportException(
                        f"{operation}失败: HTTP {response.status_code}"
                    )

                await self._wait_before_retry_async(
                    operation,
                    attempt,
                    f"HTTP {response.status_code}",
                )
                continue

            return response

        raise ForumTransportException(f"{operation}失败")

    def _send_sync_request(
        self,
        client: httpx.Client,
        method: str,
        url: str,
        *,
        operation: str,
        **kwargs,
    ) -> httpx.Response:
        for attempt in range(self.request_retries + 1):
            self._sync_shared_state_to_client(client)
            try:
                response = client.request(method, url, **kwargs)
                self._sync_client_to_shared_state(client)
            except httpx.RequestError as exc:
                if attempt >= self.request_retries:
                    raise ForumTransportException(f"{operation}失败: {exc}") from exc

                self._wait_before_retry_sync(operation, attempt, exc)
                continue

            if self._is_retryable_status(response.status_code):
                if attempt >= self.request_retries:
                    raise ForumTransportException(
                        f"{operation}失败: HTTP {response.status_code}"
                    )

                self._wait_before_retry_sync(
                    operation,
                    attempt,
                    f"HTTP {response.status_code}",
                )
                continue

            return response

        raise ForumTransportException(f"{operation}失败")

    async def _wait_before_retry_async(self, operation: str, attempt: int, reason: object):
        delay = self._retry_delay(attempt)
        self.logger.warning(
            f"{operation}第 {attempt + 1} 次尝试失败，将在 {delay:.1f}s 后重试: {reason}"
        )
        if delay > 0:
            await asyncio.sleep(delay)

    def _wait_before_retry_sync(self, operation: str, attempt: int, reason: object):
        delay = self._retry_delay(attempt)
        self.logger.warning(
            f"{operation}第 {attempt + 1} 次尝试失败，将在 {delay:.1f}s 后重试: {reason}"
        )
        if delay > 0:
            time.sleep(delay)

    def _retry_delay(self, attempt: int) -> float:
        if self.retry_backoff <= 0:
            return 0.0
        return self.retry_backoff * (2 ** attempt)

    def _is_retryable_status(self, status_code: int) -> bool:
        return status_code == 408 or status_code == 429 or status_code >= 500

    def _build_thread_page(
        self,
        thread_id: int,
        response: httpx.Response,
        *,
        html: str | None = None,
    ) -> FetchedThreadPage:
        if response.status_code != 200:
            raise ForumLoginException(f"无法访问帖子页面: {thread_id}")

        page_html = html if html is not None else response.text
        tree = etree.HTML(page_html, parser=etree.HTMLParser())
        if self._is_login_required_response(str(response.url), tree):
            self.is_logged_in = False
            self.clear_session()
            raise ForumLoginException("登录已失效")

        return FetchedThreadPage(
            thread_id=thread_id,
            url=str(response.url),
            html=page_html,
            fetched_at=datetime.now(),
        )

    async def _expand_thread_page_with_pagination_async(
        self,
        client: httpx.AsyncClient,
        thread_id: int,
        response: httpx.Response,
    ) -> str:
        page_html = response.text
        post_id, page_numbers = self._extract_root_post_pagination(page_html)
        if post_id is None or not page_numbers:
            return page_html

        merged_tree = etree.HTML(page_html, parser=etree.HTMLParser())
        if merged_tree is None:
            return page_html

        base_container = self._find_post_content_container(merged_tree, post_id)
        if base_container is None:
            return page_html

        for page_number in page_numbers:
            ajax_response = await self._send_async_request(
                client,
                "GET",
                self._build_threadindex_url(thread_id, post_id, page_number),
                operation=f"抓取帖子分页 {thread_id} cp={page_number}",
            )
            self._append_paginated_fragment(
                base_container,
                post_id,
                page_number,
                self._extract_ajax_html(ajax_response.text),
            )

        return etree.tostring(merged_tree, encoding="unicode")

    def _expand_thread_page_with_pagination_sync(
        self,
        client: httpx.Client,
        thread_id: int,
        response: httpx.Response,
    ) -> str:
        page_html = response.text
        post_id, page_numbers = self._extract_root_post_pagination(page_html)
        if post_id is None or not page_numbers:
            return page_html

        merged_tree = etree.HTML(page_html, parser=etree.HTMLParser())
        if merged_tree is None:
            return page_html

        base_container = self._find_post_content_container(merged_tree, post_id)
        if base_container is None:
            return page_html

        for page_number in page_numbers:
            ajax_response = self._send_sync_request(
                client,
                "GET",
                self._build_threadindex_url(thread_id, post_id, page_number),
                operation=f"同步抓取帖子分页 {thread_id} cp={page_number}",
            )
            self._append_paginated_fragment(
                base_container,
                post_id,
                page_number,
                self._extract_ajax_html(ajax_response.text),
            )

        return etree.tostring(merged_tree, encoding="unicode")

    def _extract_root_post_pagination(self, page_html: str) -> tuple[int | None, list[int]]:
        tree = etree.HTML(page_html, parser=etree.HTMLParser())
        if tree is None:
            return None, []

        post_elements = tree.xpath('//div[@id="postlist"]/div[starts-with(@id, "post_")]')
        if not post_elements:
            return None, []

        post_id_text = post_elements[0].get("id", "")
        try:
            post_id = int(post_id_text.split("_")[-1])
        except ValueError:
            return None, []

        page_numbers: set[int] = set()
        for value in post_elements[0].xpath('.//*[@id="threadindex"]//*[@page]/@page'):
            try:
                page_number = int(value)
            except ValueError:
                continue
            if page_number > 1:
                page_numbers.add(page_number)

        if not page_numbers:
            attributes = post_elements[0].xpath('.//@href | .//@onclick')
            for attribute in attributes:
                for match in re.findall(r'cp=(\d+)', attribute):
                    page_number = int(match)
                    if page_number > 1:
                        page_numbers.add(page_number)

        return post_id, sorted(page_numbers)

    def _build_threadindex_url(self, thread_id: int, post_id: int, page_number: int) -> str:
        return (
            f"{self.base_url}/forum.php?mod=viewthread&threadindex=yes"
            f"&tid={thread_id}&viewpid={post_id}&cp={page_number}&inajax=1"
            f"&ajaxtarget=post_{post_id}"
        )

    def _extract_ajax_html(self, response_text: str) -> str:
        match = re.search(r'<!\[CDATA\[(.*)\]\]>', response_text, re.S)
        if match:
            return match.group(1)
        return response_text

    def _find_post_content_container(
        self,
        tree: etree._Element,
        post_id: int,
    ) -> etree._Element | None:
        containers = tree.xpath(
            f'//*[@id="postmessage_{post_id}" or @id="postpw_{post_id}"]'
        )
        if not containers:
            return None
        return containers[0]

    def _append_paginated_fragment(
        self,
        base_container: etree._Element,
        post_id: int,
        page_number: int,
        fragment_html: str,
    ):
        fragment_tree = etree.HTML(fragment_html, parser=etree.HTMLParser())
        if fragment_tree is None:
            return

        page_container = self._find_post_content_container(fragment_tree, post_id)
        if page_container is None:
            return

        threadindex = page_container.xpath('.//*[@id="threadindex"]')
        for element in threadindex:
            parent = element.getparent()
            if parent is not None:
                parent.remove(element)

        separator = etree.Element(
            "div",
            attrib={
                "class": "keylol-page-break",
                "data-keylol-cp": str(page_number),
            },
        )
        separator.append(etree.Element("br"))
        separator.append(etree.Element("br"))
        base_container.append(separator)

        wrapper = etree.Element(
            "div",
            attrib={
                "class": "keylol-page-fragment",
                "data-keylol-cp": str(page_number),
                "data-keylol-container-kind": self._resolve_content_container_kind(
                    page_container
                ),
            },
        )
        if page_container.text:
            wrapper.text = page_container.text

        for child in list(page_container):
            page_container.remove(child)
            wrapper.append(child)

        base_container.append(wrapper)

    def _resolve_content_container_kind(self, page_container: etree._Element) -> str:
        container_id = page_container.get("id", "")
        if container_id.startswith("postpw_"):
            return "postpw"
        return "postmessage"

    def _build_latest_posts_page(self, response: httpx.Response) -> FetchedLatestPostsPage:
        if response.status_code != 200:
            raise ForumLoginException("无法访问最新帖子页面")

        tree = etree.HTML(response.content, parser=etree.HTMLParser())
        if self._is_login_required_response(str(response.url), tree):
            self.is_logged_in = False
            self.clear_session()
            raise ForumLoginException("登录已失效")

        return FetchedLatestPostsPage(
            url=str(response.url),
            html=response.text,
            fetched_at=datetime.now(),
        )

    def _sync_shared_state_to_client(self, client: httpx.Client | httpx.AsyncClient):
        client.headers.update(dict(self._headers))
        client.cookies.clear()
        self._restore_cookie_records(client.cookies, self._serialize_cookies())

    def _sync_client_to_shared_state(self, client: httpx.Client | httpx.AsyncClient):
        self._cookies.clear()
        self._restore_cookie_records(self._cookies, self._serialize_cookies(client.cookies))

    def _serialize_cookies(
        self,
        cookies: Optional[httpx.Cookies] = None,
    ) -> list[dict[str, str]]:
        cookie_jar = (cookies or self._cookies).jar
        serialized: list[dict[str, str]] = []
        for cookie in cookie_jar:
            if cookie.value is None:
                continue
            serialized.append(
                {
                    "name": cookie.name,
                    "value": cookie.value,
                    "domain": cookie.domain or "",
                    "path": cookie.path or "/",
                }
            )
        return serialized

    def _restore_cookie_records(
        self,
        cookies: httpx.Cookies,
        cookie_records: list[dict[str, str]],
    ):
        for cookie_record in cookie_records:
            name = cookie_record.get("name")
            value = cookie_record.get("value")
            if not name or value is None:
                continue

            domain = cookie_record.get("domain") or None
            path = cookie_record.get("path") or "/"

            if domain is not None:
                cookies.set(name, value, domain=domain, path=path)
            else:
                cookies.set(name, value, path=path)

    def _is_login_required_response(self, response_url: str, tree: Optional[etree._Element]) -> bool:
        login_markers = tree.xpath('//section[@id="nav-additional"]//text()') if tree is not None else []
        return "login" in response_url or '登录' in login_markers
    
    def _save_session(self):
        """保存 session 到文件"""
        try:
            session_data = {
                'cookies': self._serialize_cookies(),
                'headers': dict(self._headers),
                'is_logged_in': self.is_logged_in
            }
            
            with open(self.session_file, 'wb') as f:
                pickle.dump(session_data, f)
            
            self.logger.info(f"Session 已保存到 {self.session_file}")
        except NameError:
            pass
        except Exception as e:
            self.logger.error(f"保存 session 失败: {e}")
    
    def _load_session(self):
        """从文件加载 session"""
        try:
            if not os.path.exists(self.session_file):
                self.logger.info("Session 文件不存在，将创建新的 session")
                return
            
            with open(self.session_file, 'rb') as f:
                session_data = pickle.load(f)

            self._headers.update(session_data.get('headers', {}))
            
            # 恢复 cookies
            self._cookies.clear()
            stored_cookies = session_data.get('cookies', {})
            if isinstance(stored_cookies, list):
                self._restore_cookie_records(self._cookies, stored_cookies)
            elif isinstance(stored_cookies, dict):
                for name, value in stored_cookies.items():
                    self._cookies.set(name, value)
            
            # 恢复登录状态
            self.is_logged_in = session_data.get('is_logged_in', False)
            if self.is_logged_in:
                self.logger.info("Session 加载成功，登录有效性将在首次请求时验证")
            else:
                self.logger.info("Session 加载成功")
                
        except Exception as e:
            self.logger.error(f"加载 session 失败: {e}")
            self.is_logged_in = False
    
    def clear_session(self):
        """清除 session 文件"""
        try:
            if os.path.exists(self.session_file):
                os.remove(self.session_file)
                self.logger.info("Session 文件已清除")
            self._cookies.clear()
            if self._async_http_client is not None:
                self._async_http_client.cookies.clear()
            self.is_logged_in = False
        except Exception as e:
            self.logger.error(f"清除 session 失败: {e}")
    
    def login(self, captcha_callback: Optional[Callable[[bytes], str]] = None) -> bool:
        """登录论坛"""
        # 如果已经登录且 session 有效，直接返回
        if self.is_logged_in and self.check_login_status():
            self.logger.info("已登录，无需重新登录")
            return True
        
        try:
            with self._create_sync_http_client() as client:
                self._sync_shared_state_to_client(client)

                login_page = client.get(f"{self.base_url}/member.php?mod=logging&action=login")
                if login_page.status_code != 200:
                    raise ForumLoginException("无法访问登录页面")

                tree = etree.HTML(login_page.content, parser=etree.HTMLParser())
                form = tree.xpath('//form[@name="login"]')[0]
                loginhash = form.xpath('./@id')[0].split('_')[-1]
                formhash = form.xpath('.//input[@name="formhash"]/@value')[0]

                login_data = {
                    'duceapp': 'yes',
                    'formhash': formhash,
                    'referer': f"{self.base_url}/",
                    'lssubmit': 'yes',
                    'loginfield': 'auto',
                    'username': self.username,
                    'password': self.password,
                    'questionid': '0',
                    'answer': '',
                    'cookietime': '2592000',
                    'smscode': '',
                }

                login_url = f"{self.base_url}/member.php?mod=logging&action=login&loginsubmit=yes&loginhash={loginhash}&inajax=1"
                response = client.post(login_url, data=login_data)
                self._sync_client_to_shared_state(client)

                if captcha_callback is not None:
                    pass

                if "reload" in response.text and self.base_url in response.text:
                    self.is_logged_in = True
                    self.logger.info("论坛登录成功")
                    self._save_session()
                    return True

                raise ForumLoginException("登录失败，用户名密码或验证码错误")
                
        except Exception as e:
            self.logger.error(f"登录过程出错: {e}")
            raise
    
    def check_login_status(self) -> bool:
        """检查登录状态"""
        with self._create_sync_http_client() as client:
            response = self._send_sync_request(
                client,
                "GET",
                self.base_url,
                operation="同步检查论坛登录状态",
            )

        tree = etree.HTML(response.content, parser=etree.HTMLParser())
        is_valid = not self._is_login_required_response(str(response.url), tree) and self.is_logged_in
        if not is_valid:
            self.is_logged_in = False
        return is_valid
    
    def __del__(self):
        """析构函数，确保 session 被保存"""
        try:
            if hasattr(self, 'is_logged_in') and self.is_logged_in:
                self._save_session()
        except Exception:
            pass