"""
关系档案
记录"你和 Agent 之间的故事"，不只是用户画像，而是关系演化史
"""
import json
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from agent.storage.base import StorageBackend
from agent.storage.local_json import LocalJsonStorage


class RelationshipLog:
    """
    关系日志：记录双方互动中的关键事件，构建关系档案
    """

    EVENT_TYPES = {
        "first_meet": "初次见面",
        "deep_talk": "深入交流",
        "problem_solved": "共同解决问题",
        "user_praised": "用户表扬",
        "user_corrected": "用户纠正",
        "user_frustrated": "用户不满",
        "joke_shared": "共同玩笑",
        "vulnerability": "用户袒露脆弱",
        "milestone": "重要节点",
        "routine": "日常闲聊",
    }

    def __init__(
        self,
        storage_path: str = "./storage/relationship",
        storage: Optional[StorageBackend] = None,
    ):
        self.storage = storage or LocalJsonStorage()
        self.storage_path = self.storage.ensure_dir(storage_path)

        self.events_file = os.path.join(self.storage_path, "events.json")
        self.events = self._load_events()

        # 关系亲密度 (0-1)，随正面互动增长
        self.intimacy = self._load_intimacy()
        self.trust_level = self._load_trust()

    def _load_events(self) -> List[Dict[str, Any]]:
        return self.storage.load_json("events.json", self.storage_path, default=[])

    def _save_events(self):
        self.storage.save_json(self.events, "events.json", self.storage_path)

    def _load_intimacy(self) -> float:
        meta = self.storage.load_json("meta.json", self.storage_path, default={})
        return meta.get("intimacy", 0.1)

    def _load_trust(self) -> float:
        meta = self.storage.load_json("meta.json", self.storage_path, default={})
        return meta.get("trust_level", 0.2)

    def _save_meta(self):
        self.storage.save_json({
            "intimacy": round(self.intimacy, 3),
            "trust_level": round(self.trust_level, 3),
            "updated_at": datetime.now().isoformat()
        }, "meta.json", self.storage_path)

    def add_event(self, event_type: str, description: str, sentiment: float = 0.0):
        """
        记录关系事件
        sentiment: -1 负面, 0 中性, 1 正面
        """
        if event_type not in self.EVENT_TYPES:
            event_type = "routine"

        event = {
            "type": event_type,
            "type_desc": self.EVENT_TYPES[event_type],
            "description": description,
            "sentiment": sentiment,
            "timestamp": datetime.now().isoformat()
        }
        self.events.append(event)
        self._save_events()

        # 更新亲密度和信任度
        if sentiment > 0.3:
            self.intimacy = min(1.0, self.intimacy + 0.02)
            self.trust_level = min(1.0, self.trust_level + 0.015)
        elif sentiment < -0.3:
            self.intimacy = max(0.0, self.intimacy - 0.01)
            self.trust_level = max(0.0, self.trust_level - 0.02)

        self._save_meta()

    def get_recent_events(self, limit: int = 5, days: int = 7) -> List[Dict[str, Any]]:
        """获取最近的关系事件"""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        recent = [e for e in self.events if e["timestamp"] > cutoff]
        return recent[-limit:]

    def get_relationship_context(self) -> str:
        """生成关系上下文摘要，注入系统 prompt"""
        parts = []

        # 关系阶段
        if self.intimacy < 0.2:
            stage = "刚认识不久"
        elif self.intimacy < 0.5:
            stage = "正在熟悉"
        elif self.intimacy < 0.8:
            stage = "比较熟悉的朋友"
        else:
            stage = "很亲近的伙伴"

        parts.append(f"你和用户的关系阶段：{stage}（亲密度 {self.intimacy:.2f}）")

        # 最近重要事件
        recent = self.get_recent_events(limit=3)
        if recent:
            parts.append("\n最近的重要互动：")
            for e in recent:
                emoji = {"user_praised": "🌟", "user_corrected": "🔧", "user_frustrated": "💢",
                         "deep_talk": "🌊", "joke_shared": "😄", "vulnerability": "💝",
                         "problem_solved": "🎯", "first_meet": "🤝", "milestone": "🏆"}.get(e["type"], "•")
                parts.append(f"  {emoji} {e['type_desc']}: {e['description'][:60]}")

        # 信任度影响
        if self.trust_level < 0.3:
            parts.append("\n用户对你还在观察期，回复要更加谨慎可靠。")
        elif self.trust_level > 0.8:
            parts.append("\n用户很信任你，可以稍微大胆一些，开开玩笑也没关系。")

        return "\n".join(parts)

    def get_follow_up_items(self) -> List[str]:
        """提取需要后续跟进的事项"""
        items = []
        for e in self.events[-20:]:
            desc = e["description"].lower()
            if any(kw in desc for kw in ["待确认", "下次", "之后", "到时候", "改天", "回头"]):
                items.append(e["description"])
        return items[-5:]

    def get_summary(self) -> Dict[str, Any]:
        """返回关系摘要，用于 Checkpoint 和状态展示"""
        return {
            "intimacy": round(self.intimacy, 3),
            "trust_level": round(self.trust_level, 3),
            "event_count": len(self.events),
            "recent_events": self.get_recent_events(limit=3),
        }

    def clear_session(self):
        """清空本次会话的情绪历史（ emotion 模块调用）"""
        pass
