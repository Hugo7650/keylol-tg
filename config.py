import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

@dataclass
class Config:
    # Telegram配置
    telegram_api_id: int = int(os.getenv('TELEGRAM_API_ID', '0'))
    telegram_api_hash: str = os.getenv('TELEGRAM_API_HASH', '')
    telegram_bot_token: str = os.getenv('TELEGRAM_BOT_TOKEN', '')
    telegram_channel_id: int = int(os.getenv('TELEGRAM_CHANNEL_ID', '0'))
    telegram_admin_id: int = int(os.getenv('TELEGRAM_ADMIN_ID', '0'))
    
    # 论坛配置
    forum_base_url: str = os.getenv('FORUM_BASE_URL', '')
    forum_username: str = os.getenv('FORUM_USERNAME', '')
    forum_password: str = os.getenv('FORUM_PASSWORD', '')
    
    # 其他配置
    check_interval: int = int(os.getenv('CHECK_INTERVAL', '300'))  # 5分钟
    max_posts_per_check: int = int(os.getenv('MAX_POSTS_PER_CHECK', '10'))
    
    def validate(self) -> bool:
        """验证配置是否完整"""
        required_fields = [
            self.telegram_api_id, self.telegram_api_hash,
            self.telegram_channel_id, self.forum_base_url
        ]
        return all(field for field in required_fields)
