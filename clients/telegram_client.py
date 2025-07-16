from pyrogram import Client
from pyrogram.types import Message
from pyrogram.enums import ChatType
import logging
from typing import Optional, TYPE_CHECKING
from models.post import ForumPost
from io import BytesIO
from config import Config
import re

if TYPE_CHECKING:
    from services.post_service import PostService

DEBUG_FLAG = False

class TelegramClient:
    """Telegram客户端"""

    def __init__(self, api_id: int, api_hash: str, bot_token: str, work_dir: Optional[str] = None):
        self.api_id = api_id
        self.api_hash = api_hash
        self.bot_token = bot_token
        self.app: Client
        self.logger = logging.getLogger(__name__)
        self.work_dir = work_dir
        self.post_service: Optional['PostService'] = None
    
    def set_post_service(self, post_service: 'PostService'):
        """设置帖子服务引用"""
        self.post_service = post_service
    
    async def start(self):
        """启动Telegram客户端"""
        try:
            if self.bot_token:
                self.app = Client(
                    "keylol_bot",
                    api_id=self.api_id,
                    api_hash=self.api_hash,
                    bot_token=self.bot_token,
                    workdir=self.work_dir if self.work_dir else ''
                )
            else:
                self.app = Client(
                    "keylol_user",
                    api_id=self.api_id,
                    api_hash=self.api_hash
                )
            self.setup_handlers()
            
            await self.app.start()
            self.logger.info("Telegram客户端启动成功")

        except Exception as e:
            self.logger.error(f"Telegram客户端启动失败: {e}")
            raise
    
    async def stop(self):
        """停止Telegram客户端"""
        if self.app:
            await self.app.stop()
    
    async def send_post_to_channel(self, channel_id: int, post: ForumPost) -> bool:
        """发送帖子到频道"""
        try:
            message = post.to_telegram_message()
            
            if DEBUG_FLAG:
                self.logger.info(f"准备发送帖子到频道 {channel_id}: {message}")
                return True
            
            # 发送文本消息
            await self.app.send_message(
                chat_id=channel_id,
                text=message,
                disable_web_page_preview=False
            )
            
            # 如果有图片，发送图片
            # if post.images:
            #     for img_url in post.images[:3]:  # 最多发送3张图片
            #         try:
            #             await self.app.send_photo(
            #                 chat_id=channel_id,
            #                 photo=img_url,
            #                 caption=message
            #             )
            #         except Exception as e:
            #             self.logger.warning(f"发送图片失败: {e}")
            
            self.logger.info(f"成功发送帖子到频道: {post.id} {post.title}")
            return True
            
        except Exception as e:
            self.logger.error(f"发送帖子到频道失败: {channel_id}, 错误: {e}")
            return False
    
    async def send_admin_notification(self, admin_id: int, message: str, 
                                    captcha_image: Optional[bytes] = None) -> bool:
        """发送管理员通知"""
        try:
            if message:
                if DEBUG_FLAG:
                    self.logger.info(f"准备发送管理员通知: {message}")
                    return True
                await self.app.send_message(
                    chat_id=admin_id,
                    text=message,
                    disable_web_page_preview=False
                )
            # 如果有验证码图片，发送图片
            if captcha_image:
                if DEBUG_FLAG:
                    self.logger.info("准备发送验证码图片给管理员")
                    return True
                await self.app.send_photo(
                    chat_id=admin_id,
                    photo=BytesIO(captcha_image),
                    caption="请输入验证码 (回复此消息)"
                )
            
            return True
            
        except Exception as e:
            self.logger.error(f"发送管理员通知失败: {e}")
            return False
    
    async def wait_for_captcha_input(self, admin_id: str, timeout: int = 300) -> Optional[str]:
        """等待管理员输入验证码"""
        # 这里需要实现一个等待用户回复的机制
        # 可以使用pyrogram的对话功能或者消息监听
        pass
    
    def setup_handlers(self):
        """设置消息处理器"""
        @self.app.on_message()
        async def handle_message(client, message: Message):
            if message.chat.type == ChatType.PRIVATE:
                # 处理私聊消息
                if message.text:
                    self.logger.info(f"收到私聊消息: {message.chat.id}, 内容: {message.text if message.text else '无文本'}")
                    
                    # 检查是否包含论坛链接
                    if Config.forum_base_url in message.text:
                        await self._handle_forum_link_message(message)
            
        self.logger.info("Telegram消息处理器已设置")
    
    async def _handle_forum_link_message(self, message: Message):
        """处理包含论坛链接的消息"""
        try:
            # 提取论坛链接
            threads = self._extract_forum_links(message.text)
            
            if not threads:
                return
            
            # 处理每个链接
            for tid in threads:
                if self.post_service:
                    success = await self.post_service.process_single_thread(tid, message.chat.id)
                    if not success:
                        await self.app.send_message(
                            chat_id=message.chat.id,
                            text=f"抓取失败: {tid}"
                        )
                else:
                    await self.app.send_message(
                        chat_id=message.chat.id,
                        text="服务未初始化，无法处理链接"
                    )
                    
        except Exception as e:
            self.logger.error(f"处理论坛链接消息失败: {e}")
            await self.app.send_message(
                chat_id=message.chat.id,
                text=f"处理链接时出错: {str(e)}"
            )
    
    def _extract_forum_links(self, text: str) -> list[int]:
        """从文本中提取论坛链接"""
        # 匹配论坛帖子链接的正则表达式
        patterns = [
            rf"{re.escape(Config.forum_base_url)}/thread-(\d+)",
            rf"{re.escape(Config.forum_base_url)}/t(\d+)",
        ]
        threads = []
        for pattern in patterns:
            matches = re.findall(pattern, text)
            threads.extend([int(match) for match in matches if match.isdigit()])
        return list(set(threads))
    
    async def send_post_to_user(self, user_id: int, post: ForumPost) -> bool:
        """发送帖子给用户"""
        try:
            message = post.to_telegram_message()
            
            if DEBUG_FLAG:
                self.logger.info(f"准备发送帖子给用户 {user_id}: {message}")
                return True
            
            # 发送文本消息
            await self.app.send_message(
                chat_id=user_id,
                text=message,
                disable_web_page_preview=True
            )
            
            self.logger.info(f"成功发送帖子给用户 {user_id}: {post.id} {post.title}")
            return True
            
        except Exception as e:
            self.logger.error(f"发送帖子给用户失败: {user_id}, 错误: {e}")
            return False
