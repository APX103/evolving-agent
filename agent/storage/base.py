"""
存储后端抽象基类
所有存储实现必须遵循此接口
"""
from abc import ABC, abstractmethod
from typing import Any


class StorageBackend(ABC):
    """存储后端抽象接口"""

    @abstractmethod
    def ensure_dir(self, path: str) -> str:
        """确保目录存在，返回规范化后的路径"""
        ...

    @abstractmethod
    def load_json(self, filename: str, directory: str, default: Any = None) -> Any:
        """从指定目录加载 JSON 文件，不存在时返回 default"""
        ...

    @abstractmethod
    def save_json(self, data: Any, filename: str, directory: str) -> None:
        """原子保存 JSON 文件到指定目录（.tmp → os.replace）"""
        ...
