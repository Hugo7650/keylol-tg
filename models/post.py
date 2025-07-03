from datetime import datetime
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from clients.forum_client import ForumClient

class ForumPost:
    """论坛帖子数据模型 - 支持懒加载"""
    
    def __init__(self, id: int, title: str, url: str, author: str, 
                 forum_client: Optional['ForumClient'] = None):
        # 基本字段（立即可用）
        self.id = id
        self.title = title
        self.url = url
        self.author = author
        
        # 懒加载字段
        self._content: Optional[str] = None
        self._publish_time: Optional[datetime] = None
        self._images: Optional[List[str]] = None
        self._tags: Optional[List[str]] = None
        
        # 用于懒加载的客户端
        self._forum_client = forum_client
        self._is_loaded = False
    
    def _load_details(self):
        """加载详细信息"""
        if self._is_loaded or not self._forum_client:
            return
        
        try:
            # 使用forum_client加载详细信息
            post_details = self._forum_client.load_post_details(self.url)
            if post_details:
                self._content = post_details.get('content', '')
                self._publish_time = post_details.get('publish_time', datetime.now())
                self._images = post_details.get('images', [])
                self._tags = post_details.get('tags', [])
                self._is_loaded = True
        except Exception as _:
            # 设置默认值
            self._content = "内容加载失败"
            self._publish_time = datetime.now()
            self._images = []
            self._tags = []
            self._is_loaded = True
    
    @property
    def content(self) -> str:
        """内容 - 懒加载"""
        if self._content is None:
            self._load_details()
        return self._content or ""
    
    @property
    def publish_time(self) -> datetime:
        """发布时间 - 懒加载"""
        if self._publish_time is None:
            self._load_details()
        return self._publish_time or datetime.now()
    
    @property
    def images(self) -> List[str]:
        """图片列表 - 懒加载"""
        if self._images is None:
            self._load_details()
        return self._images or []
    
    @property
    def tags(self) -> List[str]:
        """标签列表 - 懒加载"""
        if self._tags is None:
            self._load_details()
        return self._tags or []
    
    def to_telegram_message(self) -> str:
        """转换为Telegram消息格式"""
        message = f"🆕 **{self.title}**\n"
        message += f"👤 作者: {self.author}\n"
        message += f"🕐 时间: {self.publish_time.strftime('%Y-%m-%d %H:%M')}\n"
        
        if self.tags:
            message += f"🏷️ 标签: {', '.join(self.tags)}\n"
        
        # message += f"📖 内容预览:\n{self.content[:1000]}..."
        if len(self.content) > 1000:
            message += f"📖 内容预览:\n{self.content[:1000]}...\n"
        else:
            message += f"📖 内容预览:\n{self.content}\n"
        message += f"\n🔗 [查看原帖]({self.url})"
        
        return message
    
    def is_details_loaded(self) -> bool:
        """检查详细信息是否已加载"""
        return self._is_loaded
    
    def preload_details(self):
        """预加载详细信息"""
        if not self._is_loaded:
            self._load_details()