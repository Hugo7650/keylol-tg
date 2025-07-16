from dataclasses import dataclass
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
    images: List[str] = []  
    tags: List[str] = []
    posts: List[ForumPost] = []

    def to_telegram_message(self) -> str:
        """转换为Telegram消息格式"""
        message = f"**{self.title}**\n"
        message += f"{self.author} \\ {self.publish_time.strftime('%Y-%m-%d %H:%M')}\n"

        if self.tags:
            message += f"标签: {', '.join(self.tags)}\n"
        
        message += f"\n[查看原帖]({self.url})"
        
        return message
