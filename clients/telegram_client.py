from pyrogram import Client
import logging
from typing import Optional
from models.post import ForumPost
from io import BytesIO
from config import Config

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
            
            # 限制长度
            if len(message) > 2000:
                message = message[:1997] + "..."
            
            if DEBUG_FLAG:
                self.logger.info(f"准备发送帖子到频道 {channel_id}: {message}")
                return True
            
            # 发送文本消息
            await self.app.send_message(
                chat_id=channel_id,
                text=message,
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
            
            self.logger.info(f"成功发送帖子到频道: {post.title}")
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
        async def handle_message(client, message):
            if message.chat.type == "private":
                # 处理私聊消息
                if message.text:
                    self.logger.info(f"收到私聊消息: {message.chat.id}, 内容: {message.text if message.text else '无文本'}")
                    if (Config.forum_base_url in message.text):
                        pass
            # elif message.chat.type == "channel":
            #     # 处理频道消息
            #     self.logger.info(f"收到频道消息: {message.chat.id}, 内容: {message.text if message.text else '无文本'}")
            # elif message.chat.type == "group":
            #     # 处理群组消息
            #     self.logger.info(f"收到群组消息: {message.chat.id}, 内容: {message.text if message.text else '无文本'}")
            # else:
            #     self.logger.info(f"收到其他类型消息: {message.chat.id}, 内容: {message.text if message.text else '无文本'}")
        self.logger.info("Telegram消息处理器已设置")
