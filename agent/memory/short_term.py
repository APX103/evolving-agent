"""
短期记忆 Store
当前会话的对话记录
"""
import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from agent.memory.base import MemoryStore

logger = logging.getLogger(__name__)


class ShortTermStore(MemoryStore):
    """短期记忆：当前会话的对话轮次"""

    def __init__(self, storage=None, conv_path: str = "./storage/conversations"):
        super().__init__(storage)
        self.conv_path = self.storage.ensure_dir(conv_path)
        self.short_term: List[Dict[str, Any]] = []
        self.session_id: str = self._new_session_id()

    def _new_session_id(self) -> str:
        return datetime.now().strftime("%Y%m%d_%H%M%S")

    def add_turn(self, role: str, content: str, image: Optional[str] = None):
        turn = {
            "role": role,
            "content": content,
            "image": image,
            "timestamp": datetime.now().isoformat()
        }
        self.short_term.append(turn)

    def get_short_term(self, max_turns: int = 10) -> List[Dict[str, Any]]:
        return self.short_term[-max_turns:]

    def end_session(self):
        """保存当前会话到文件，然后清空"""
        if not self.short_term:
            return {}
        session_data = {
            "session_id": self.session_id,
            "started_at": self.short_term[0]["timestamp"],
            "ended_at": datetime.now().isoformat(),
            "turn_count": len(self.short_term),
            "messages": self.short_term,
        }
        filepath = os.path.join(self.conv_path, f"session_{self.session_id}.json")
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(session_data, f, ensure_ascii=False, indent=2)
        self.short_term = []
        self.session_id = self._new_session_id()
        return session_data
