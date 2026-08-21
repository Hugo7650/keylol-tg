import asyncio
import logging
from typing import Optional, Set, TYPE_CHECKING
from datetime import datetime
import json
import os

from clients.forum_client import ForumClient, CaptchaRequiredException, ForumLoginException
from clients.forum_client import ForumTransportException
from clients.forum_client import ForumThreadUnavailableException
from infrastructure.services import KeylolForumContentParser
from infrastructure.services import KeylolThreadPageExtractor
from infrastructure.services import TelegramFormatter
from infrastructure.services.latest_posts_page_extractor import KeylolLatestPostsPageExtractor
from models.post import ForumPost
from services.post_processing_service import PostProcessingService

if TYPE_CHECKING:
    from clients.telegram_client import TelegramClient

class PostService:
    """帖子处理服务"""
    
    def __init__(
        self,
        forum_client: ForumClient,
        telegram_client: 'TelegramClient',
        channel_id: int,
        admin_id: int,
        max_posts: int = 10,
        work_dir: Optional[str] = None,
        post_processing_service: Optional[PostProcessingService] = None,
        latest_posts_extractor: Optional[KeylolLatestPostsPageExtractor] = None,
    ):
        self.forum_client = forum_client
        self.telegram_client = telegram_client
        self.channel_id = channel_id
        self.admin_id = admin_id
        self.max_posts = max_posts
        self.logger = logging.getLogger(__name__)
        thread_page_extractor = KeylolThreadPageExtractor()
        content_parser = KeylolForumContentParser()
        self.telegram_formatter = TelegramFormatter()
        self.post_processing_service = post_processing_service or PostProcessingService(
            forum_client,
            thread_page_extractor,
            content_parser,
            self.telegram_formatter,
        )
        self.latest_posts_extractor = latest_posts_extractor or KeylolLatestPostsPageExtractor()
        
        # 已处理的帖子ID集合
        self.processed_posts: Set[int] = set()
        self.last_post: int = 0
        self.cache_file = os.path.join(work_dir, "processed_posts.json") if work_dir else "processed_posts.json"
        self._load_processed_posts()
    
    def _load_processed_posts(self):
        """加载已处理的帖子ID"""
        try:
            if os.path.exists(self.cache_file):
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.processed_posts = set(data.get('posts', []))
                    self.last_post = data.get('last_post', 0)
                    self.logger.info(f"加载了 {len(self.processed_posts)} 个已处理的帖子ID")
        except Exception as e:
            self.logger.error(f"加载已处理帖子失败: {e}")
    
    def _save_processed_posts(self):
        """保存已处理的帖子ID"""
        try:
            # 只保留最大的200个帖子ID，避免文件过大
            posts_to_save = sorted(self.processed_posts, reverse=True)[:200]
            last_post = max(posts_to_save, default=0)
            data = {
                'posts': posts_to_save,
                'last_update': datetime.now().isoformat(),
                'last_post': last_post
            }
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.error(f"保存已处理帖子失败: {e}")
    
    async def check_and_send_new_posts(self):
        """检查并发送新帖子"""
        try:
            # 检查论坛登录状态
            if not await self.forum_client.async_check_login_status():
                await self._handle_login_required()
                return
            
            posts = await self._load_latest_posts()
            new_posts = [post for post in posts if post.id not in self.processed_posts]
            
            if not new_posts:
                self.logger.info("没有新帖子")
                return
            
            self.logger.info(f"发现 {len(new_posts)} 个新帖子")
            
            # 发送新帖子到频道
            for post in new_posts:
                success = await self._deliver_post_to_channel(post)
                
                if success:
                    self.processed_posts.add(post.id)
                    self._save_processed_posts()
                    await asyncio.sleep(2)  # 避免发送过快
            
        except ForumLoginException as e:
            self.logger.warning(f"论坛登录异常: {e}")
            await self._handle_login_required()

        except ForumTransportException as e:
            self.logger.warning(f"论坛网络异常，本轮跳过: {e}")
            
        except CaptchaRequiredException as e:
            self.logger.warning("需要输入验证码")
            await self._handle_captcha_required(e.captcha_image)
            
        except Exception as e:
            self.logger.error(f"检查新帖子时出错: {e}")
            await self.telegram_client.send_admin_notification(
                self.admin_id,
                f"检查新帖子时出错: {str(e)}"
            )
    
    async def _handle_login_required(self):
        """处理需要重新登录的情况"""
        try:
            # 尝试自动登录
            success = await self.forum_client.async_login()
            if success:
                await self.telegram_client.send_admin_notification(
                    self.admin_id,
                    "论坛自动重新登录成功"
                )
            else:
                await self.telegram_client.send_admin_notification(
                    self.admin_id,
                    "论坛登录失效，自动登录失败，请检查账号状态"
                )
        except ForumTransportException as e:
            self.logger.warning(f"论坛网络异常，暂不重登: {e}")
            await self.telegram_client.send_admin_notification(
                self.admin_id,
                f"论坛网络异常，暂时无法重新登录: {str(e)}"
            )
        except CaptchaRequiredException as e:
            await self._handle_captcha_required(e.captcha_image)
        except Exception as e:
            await self.telegram_client.send_admin_notification(
                self.admin_id,
                f"重新登录失败: {str(e)}"
            )
    
    async def _handle_captcha_required(self, captcha_image: bytes):
        """处理需要验证码的情况"""
        await self.telegram_client.send_admin_notification(
            self.admin_id,
            "论坛需要输入验证码，请查看下方图片并回复验证码",
            captcha_image
        )
        
        # 这里可以实现等待管理员输入验证码的逻辑
        # captcha_code = await self.telegram_client.wait_for_captcha_input(self.admin_id)
        # if captcha_code:
        #     # 使用验证码重新登录
        #     pass
    
    async def process_single_thread(self, thread_id: int, user_id: int) -> bool:
        """处理单个帖子"""
        try:
            # 检查论坛登录状态
            if not await self.forum_client.async_check_login_status():
                await self._handle_login_required()
                # 如果登录失败，通知用户
                if not await self.forum_client.async_check_login_status():
                    await self.telegram_client.send_admin_notification(
                        user_id,
                        "论坛登录失效，无法抓取帖子内容"
                    )
                    return False

            try:
                success = await self._deliver_thread_to_user(thread_id, user_id)
            except ForumThreadUnavailableException as e:
                self.logger.info(
                    f"帖子不可用: {thread_id}, 论坛提示: {e.forum_message}"
                )
                await self.telegram_client.send_admin_notification(
                    user_id,
                    f"论坛提示：{e.forum_message}"
                )
                return False
            except ForumTransportException:
                raise
            except Exception as e:
                self.logger.error(f"处理帖子失败: {thread_id}, 错误: {e}")
                await self.telegram_client.send_admin_notification(
                    user_id,
                    "无法获取帖子内容，可能是链接无效或需要权限"
                )
                return False

            if success:
                self.logger.info(f"成功处理单个帖子: {thread_id}")
                return True

            await self.telegram_client.send_admin_notification(
                user_id,
                "帖子内容获取成功，但发送失败"
            )
            return False

        except ForumTransportException as e:
            self.logger.warning(f"处理单个帖子时论坛网络异常: {e}")
            await self.telegram_client.send_admin_notification(
                user_id,
                "论坛连接不稳定，请稍后重试"
            )
            return False
                
        except ForumLoginException as e:
            self.logger.warning(f"处理单个帖子时论坛登录异常: {e}")
            await self._handle_login_required()
            await self.telegram_client.send_admin_notification(
                user_id,
                f"论坛登录异常: {str(e)}"
            )
            return False
            
        except CaptchaRequiredException as e:
            self.logger.warning("处理单个帖子时需要输入验证码")
            await self._handle_captcha_required(e.captcha_image)
            await self.telegram_client.send_admin_notification(
                user_id,
                "需要输入验证码才能继续抓取"
            )
            return False
            
        except Exception as e:
            self.logger.error(f"处理单个帖子链接时出错: {e}")
            await self.telegram_client.send_admin_notification(
                user_id,
                f"处理帖子链接时出错: {str(e)}"
            )
            return False

    async def _load_latest_posts(self) -> list[ForumPost]:
        latest_posts_page = await self.forum_client.fetch_latest_posts_page()
        return self.latest_posts_extractor.extract(
            latest_posts_page,
            base_url=self.forum_client.base_url,
            limit=self.max_posts,
        )

    async def _deliver_post_to_channel(self, post: ForumPost) -> bool:
        try:
            processed_thread = await self.post_processing_service.process_thread(post.id)
        except ForumThreadUnavailableException as e:
            self.logger.info(
                f"发送论坛提示到频道: {post.id}, 论坛提示: {e.forum_message}"
            )
            unavailable_payload = self.telegram_formatter.format_unavailable_post(
                post,
                e.forum_message,
            )
            return await self.telegram_client.send_payload_to_channel(
                self.channel_id,
                unavailable_payload,
            )
        except ForumTransportException:
            raise
        return await self.telegram_client.send_payload_to_channel(
            self.channel_id,
            processed_thread.telegram_payload,
        )

    async def _deliver_thread_to_user(self, thread_id: int, user_id: int) -> bool:
        try:
            processed_thread = await self.post_processing_service.process_thread(thread_id)
        except ForumTransportException:
            raise
        return await self.telegram_client.send_payload_to_user(
            user_id,
            processed_thread.telegram_payload,
        )

