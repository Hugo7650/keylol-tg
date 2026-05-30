import asyncio
import logging
from typing import Literal, Optional, Set, TYPE_CHECKING, cast
from datetime import datetime
import json
import os

from clients.forum_client import ForumClient, CaptchaRequiredException, ForumLoginException
from clients.forum_client import ForumTransportException
from infrastructure.services import KeylolForumContentParser
from infrastructure.services import KeylolThreadPageExtractor
from infrastructure.services import TelegramFormatter
from infrastructure.services.latest_posts_page_extractor import KeylolLatestPostsPageExtractor
from infrastructure.services.legacy_forum_post_loader import LegacyForumPostLoader
from models.post import ForumPost
from services.post_processing_service import PostProcessingService
from domain.value_objects import TelegramPayload

if TYPE_CHECKING:
    from clients.telegram_client import TelegramClient

StructuredPipelineMode = Literal["structured", "legacy", "compare"]

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
        legacy_post_loader: Optional[LegacyForumPostLoader] = None,
        structured_pipeline_mode: str = "structured",
    ):
        self.forum_client = forum_client
        self.telegram_client = telegram_client
        self.channel_id = channel_id
        self.admin_id = admin_id
        self.max_posts = max_posts
        self.logger = logging.getLogger(__name__)
        thread_page_extractor = KeylolThreadPageExtractor()
        content_parser = KeylolForumContentParser()
        formatter = TelegramFormatter()
        self.post_processing_service = post_processing_service or PostProcessingService(
            forum_client,
            thread_page_extractor,
            content_parser,
            formatter,
        )
        self.latest_posts_extractor = latest_posts_extractor or KeylolLatestPostsPageExtractor()
        self.legacy_post_loader = legacy_post_loader or LegacyForumPostLoader(
            forum_client,
            thread_page_extractor,
            content_parser,
            base_url=forum_client.base_url,
        )
        self.structured_pipeline_mode = self._normalize_structured_pipeline_mode(
            structured_pipeline_mode
        )
        
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

    def _normalize_structured_pipeline_mode(self, mode: str) -> StructuredPipelineMode:
        normalized = mode.strip().lower()
        if normalized not in {"structured", "legacy", "compare"}:
            self.logger.warning(
                f"未知的 STRUCTURED_PIPELINE_MODE={mode}，回退到 structured"
            )
            return "structured"
        return cast(StructuredPipelineMode, normalized)

    async def _load_latest_posts(self) -> list[ForumPost]:
        latest_posts_page = await self.forum_client.fetch_latest_posts_page()
        return self.latest_posts_extractor.extract(
            latest_posts_page,
            base_url=self.forum_client.base_url,
            details_loader=self.legacy_post_loader.load_post_details,
            limit=self.max_posts,
        )

    async def _deliver_post_to_channel(self, post: ForumPost) -> bool:
        if self.structured_pipeline_mode == "legacy":
            legacy_payload = await self._build_legacy_payload_for_post(
                post,
                disable_web_page_preview=False,
            )
            return await self.telegram_client.send_payload_to_channel(
                self.channel_id,
                legacy_payload,
            )

        try:
            processed_thread = await self.post_processing_service.process_thread(post.id)
        except ForumTransportException:
            raise
        except Exception:
            if self.structured_pipeline_mode != "compare":
                raise

            self.logger.warning(f"结构化发送失败，回退到 legacy 路径: {post.id}")
            legacy_payload = await self._build_legacy_payload_for_post(
                post,
                disable_web_page_preview=False,
            )
            return await self.telegram_client.send_payload_to_channel(
                self.channel_id,
                legacy_payload,
            )

        if self.structured_pipeline_mode == "compare":
            try:
                legacy_payload = await self._build_legacy_payload_for_post(
                    post,
                    disable_web_page_preview=False,
                )
            except ForumTransportException as e:
                self.logger.warning(
                    f"帖子 {post.id} 的 legacy 对比路径因网络异常被跳过: {e}"
                )
            else:
                await self._report_payload_differences(
                    post.id,
                    legacy_payload,
                    processed_thread.telegram_payload,
                )

        return await self.telegram_client.send_payload_to_channel(
            self.channel_id,
            processed_thread.telegram_payload,
        )

    async def _deliver_thread_to_user(self, thread_id: int, user_id: int) -> bool:
        legacy_post = self.legacy_post_loader.create_post(thread_id)

        if self.structured_pipeline_mode == "legacy":
            legacy_payload = await self._build_legacy_payload_for_post(
                legacy_post,
                disable_web_page_preview=True,
            )
            return await self.telegram_client.send_payload_to_user(user_id, legacy_payload)

        try:
            processed_thread = await self.post_processing_service.process_thread(thread_id)
        except ForumTransportException:
            raise
        except Exception:
            if self.structured_pipeline_mode != "compare":
                raise

            self.logger.warning(f"结构化私聊发送失败，回退到 legacy 路径: {thread_id}")
            legacy_payload = await self._build_legacy_payload_for_post(
                legacy_post,
                disable_web_page_preview=True,
            )
            return await self.telegram_client.send_payload_to_user(user_id, legacy_payload)

        if self.structured_pipeline_mode == "compare":
            try:
                legacy_payload = await self._build_legacy_payload_for_post(
                    legacy_post,
                    disable_web_page_preview=True,
                )
            except ForumTransportException as e:
                self.logger.warning(
                    f"帖子 {thread_id} 的 legacy 私聊对比路径因网络异常被跳过: {e}"
                )
            else:
                await self._report_payload_differences(
                    thread_id,
                    legacy_payload,
                    processed_thread.telegram_payload,
                )

        return await self.telegram_client.send_payload_to_user(
            user_id,
            processed_thread.telegram_payload,
        )

    async def _build_legacy_payload_for_post(
        self,
        post: ForumPost,
        *,
        disable_web_page_preview: bool,
    ) -> TelegramPayload:
        return await asyncio.to_thread(
            self.telegram_client.build_legacy_payload_for_post,
            post,
            disable_web_page_preview=disable_web_page_preview,
        )

    async def _report_payload_differences(
        self,
        thread_id: int,
        legacy_payload: TelegramPayload,
        structured_payload: TelegramPayload,
    ):
        differences: list[str] = []
        if legacy_payload.text != structured_payload.text:
            differences.append("text")
        if legacy_payload.media_urls != structured_payload.media_urls:
            differences.append("media")
        if (
            legacy_payload.disable_web_page_preview
            != structured_payload.disable_web_page_preview
        ):
            differences.append("preview")

        if not differences:
            return

        self.logger.warning(
            f"帖子 {thread_id} 的 structured/legacy 输出不一致: {', '.join(differences)}"
        )
        await self.telegram_client.send_admin_notification(
            self.admin_id,
            f"帖子 {thread_id} 的 structured/legacy 输出不一致: {', '.join(differences)}",
        )
    
