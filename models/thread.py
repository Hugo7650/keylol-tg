from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional
from models.post import ForumPost

@dataclass
class ForumThread:
    """论坛主题数据模型"""
    id: str
    title: str
    author: str
    publish_time: datetime
    url: str
    images: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    posts: List[ForumPost] = field(default_factory=list)

    def to_telegram_message(self) -> str:
        """转换为Telegram消息格式"""
        from infrastructure.services import LegacyTelegramPayloadAdapter

        payload = LegacyTelegramPayloadAdapter().from_forum_thread(
            self,
            disable_web_page_preview=False,
        )
        return payload.text
