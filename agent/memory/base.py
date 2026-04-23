"""
记忆 Store 抽象基类
"""
from abc import ABC
from typing import Any, Dict, Optional

from agent.storage.base import StorageBackend
from agent.storage.local_json import LocalJsonStorage


class MemoryStore(ABC):
    """记忆存储抽象基类"""

    def __init__(self, storage: Optional[StorageBackend] = None):
        self.storage = storage or LocalJsonStorage()
