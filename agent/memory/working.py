"""
工作记忆 Store
本次会话的关键点和临时状态
"""
from datetime import datetime
from typing import Any, Dict, Optional

from agent.memory.base import MemoryStore


class WorkingMemoryStore(MemoryStore):
    """工作记忆：会话内的关键点"""

    def __init__(self, storage=None):
        super().__init__(storage)
        self.working_memory: Dict[str, Any] = {}

    def set_working(self, key: str, value: Any):
        self.working_memory[key] = {
            "value": value,
            "timestamp": datetime.now().isoformat()
        }

    def get_working(self, key: str) -> Optional[Any]:
        entry = self.working_memory.get(key)
        return entry["value"] if entry else None

    def clear(self):
        self.working_memory = {}
