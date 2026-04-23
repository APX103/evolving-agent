"""
记忆 Store 模块
将 MemoryManager 拆分为独立的存储层
"""
# 从 memory.py 重新导出 MemoryManager（避免 import 冲突）
from agent.memory_module import MemoryManager  # noqa: F401

from agent.memory.base import MemoryStore
from agent.memory.short_term import ShortTermStore
from agent.memory.working import WorkingMemoryStore
from agent.memory.long_term import LongTermStore
from agent.memory.user_profile import UserProfileStore
from agent.memory.reflections import ReflectionStore

__all__ = [
    "MemoryManager",
    "MemoryStore",
    "ShortTermStore",
    "WorkingMemoryStore",
    "LongTermStore",
    "UserProfileStore",
    "ReflectionStore",
]
