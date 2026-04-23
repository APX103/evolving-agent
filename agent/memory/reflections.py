"""
反思日志 Store
"""
from datetime import datetime
from typing import Any, Dict, List

from agent.memory.base import MemoryStore


class ReflectionStore(MemoryStore):
    """反思日志：Agent 的自我反思记录"""

    def __init__(self, storage=None, reflection_path: str = "./storage/reflections"):
        super().__init__(storage)
        self.reflection_path = self.storage.ensure_dir(reflection_path)
        self.reflections: List[Dict[str, Any]] = self.storage.load_json("reflections.json", self.reflection_path, default=[])

    def add_reflection(self, reflection: Dict[str, Any]):
        reflection["created_at"] = datetime.now().isoformat()
        self.reflections.append(reflection)
        self.storage.save_json(self.reflections, "reflections.json", self.reflection_path)

    def get_recent(self, n: int = 3) -> List[Dict[str, Any]]:
        return self.reflections[-n:] if self.reflections else []
