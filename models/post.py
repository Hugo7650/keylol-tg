from dataclasses import dataclass


@dataclass
class ForumPost:
    """论坛帖子列表项数据模型。"""

    id: int
    title: str
    url: str
    author: str
