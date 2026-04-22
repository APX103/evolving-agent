"""
多用户隔离上下文
为每个 user_id 生成独立的存储命名空间
"""
import os
from typing import Dict, Optional


class UserContext:
    """
    管理单个用户的存储路径和配置
    所有子系统通过 UserContext 获取路径，实现多用户隔离
    """

    def __init__(self, user_id: str, base_path: str = "./storage"):
        self.user_id = user_id
        self.base_path = os.path.join(base_path, user_id)

    def path(self, *subpaths: str) -> str:
        """返回用户专属路径"""
        return os.path.join(self.base_path, *subpaths)

    def ensure_dirs(self, storage):
        """确保用户所有子目录存在"""
        for sub in ["conversations", "knowledge", "user_profile", "reflections",
                    "personality", "relationship", "mood", "checkpoints",
                    "procedural_memory", "semantic_cache"]:
            storage.ensure_dir(self.path(sub))

    def to_dict(self) -> Dict[str, str]:
        return {
            "user_id": self.user_id,
            "base_path": self.base_path,
        }
