import asyncio
import logging
from typing import Optional, Set, TYPE_CHECKING
from datetime import datetime
import json
import os
import re

from clients.forum_client import ForumClient, CaptchaRequiredException, ForumLoginException
from models.post import ForumPost

if TYPE_CHECKING:
    from clients.telegram_client import TelegramClient

class PostService:
    """帖子处理服务"""
    
    def __init__(self, forum_client: ForumClient, telegram_client: 'TelegramClient',
                 channel_id: int, admin_id: int, max_posts: int = 10, work_dir: Optional[str] = None):
        self.forum_client = forum_client
        self.telegram_client = telegram_client
        self.channel_id = channel_id
        self.admin_id = admin_id
        self.max_posts = max_posts
        self.logger = logging.getLogger(__name__)
        
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
            if not self.forum_client.check_login_status():
                await self._handle_login_required()
                return
            
            # 获取最新帖子
            posts = self.forum_client.get_latest_posts(self.max_posts)
            new_posts = [post for post in posts if post.id not in self.processed_posts]
            
            if not new_posts:
                self.logger.info("没有新帖子")
                return
            
            self.logger.info(f"发现 {len(new_posts)} 个新帖子")
            
            # 发送新帖子到频道
            for post in new_posts:
                success = await self.telegram_client.send_post_to_channel(
                    self.channel_id, post
                )
                
                if success:
                    self.processed_posts.add(post.id)
                    await asyncio.sleep(2)  # 避免发送过快
            
            # 保存已处理的帖子ID
            self._save_processed_posts()
            
        except ForumLoginException as e:
            self.logger.warning(f"论坛登录异常: {e}")
            await self._handle_login_required()
            
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
            success = self.forum_client.login()
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
            if not self.forum_client.check_login_status():
                await self._handle_login_required()
                # 如果登录失败，通知用户
                if not self.forum_client.check_login_status():
                    await self.telegram_client.send_admin_notification(
                        user_id,
                        "论坛登录失效，无法抓取帖子内容"
                    )
                    return False
            
            # 获取帖子详细信息
            post_details = self.forum_client.load_post_details(thread_id)
            if not post_details:
                await self.telegram_client.send_admin_notification(
                    user_id,
                    "无法获取帖子内容，可能是链接无效或需要权限"
                )
                return False
            
            # 创建ForumPost对象
            # 由于我们只有id，需要先尝试获取基本信息
            post = self._create_post_from_link_and_details(thread_id, post_details)
            
            # 发送帖子给用户
            success = await self.telegram_client.send_post_to_user(user_id, post)
            
            if success:
                self.logger.info(f"成功处理单个帖子: {thread_id}")
                return True
            else:
                await self.telegram_client.send_admin_notification(
                    user_id,
                    "帖子内容获取成功，但发送失败"
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
    
    def _create_post_from_link_and_details(self, thread_id: int, post_details: dict) -> ForumPost:
        """从链接和详情创建ForumPost对象"""
        try:
            # 尝试从详情中获取标题，如果没有则使用默认标题
            title = post_details.get('title', f"帖子 {thread_id}")
            
            # 尝试从详情中获取作者，如果没有则使用默认作者
            author = post_details.get('author', "未知作者")
            
            # 创建ForumPost对象
            post = ForumPost(
                id=thread_id,
                title=title,
                url=f"{self.forum_client.base_url}/t{thread_id}-1-1",
                author=author,
                forum_client=self.forum_client
            )
            
            # 手动设置已加载的详情
            post._content = post_details.get('content', '')
            post._publish_time = post_details.get('publish_time', datetime.now())
            post._images = post_details.get('images', [])
            post._tags = post_details.get('tags', [])
            post._is_loaded = True
            
            return post
            
        except Exception as e:
            self.logger.error(f"创建帖子对象失败: {e}")
            # 返回基本的帖子对象
            return ForumPost(
                id=thread_id,
                title=f"帖子 {thread_id}",
                url=f"{self.forum_client.base_url}/t{thread_id}-1-1",
                author="未知作者",
                forum_client=self.forum_client
            )
