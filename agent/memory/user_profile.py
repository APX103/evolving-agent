"""
用户画像 Store
"""
from datetime import datetime
from typing import Any, Dict, Optional

from agent.memory.base import MemoryStore


class UserProfileStore(MemoryStore):
    """用户画像：持久化的用户偏好和特征"""

    def __init__(self, storage=None, profile_path: str = "./storage/user_profile"):
        super().__init__(storage)
        self.profile_path = self.storage.ensure_dir(profile_path)
        self.user_profile = self.storage.load_json("user_profile.json", self.profile_path, default={})
        self.session_count = self.user_profile.get("session_count", 0)

    def update_profile(self, key: str, value: Any):
        if "data" not in self.user_profile:
            self.user_profile["data"] = {}
        self.user_profile["data"][key] = {
            "value": value,
            "updated_at": datetime.now().isoformat()
        }
        self.user_profile["session_count"] = self.session_count
        self.storage.save_json(self.user_profile, "user_profile.json", self.profile_path)

    def get_profile(self, key: str = "") -> Any:
        data = self.user_profile.get("data", {})
        if key:
            entry = data.get(key)
            return entry["value"] if entry else None
        return {k: v["value"] for k, v in data.items()}

    def increment_session_count(self) -> int:
        self.session_count += 1
        self.user_profile["session_count"] = self.session_count
        self.storage.save_json(self.user_profile, "user_profile.json", self.profile_path)
        return self.session_count
