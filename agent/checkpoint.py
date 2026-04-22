"""
Checkpoint / Durable Execution
Agent 状态快照管理，支持断点续跑
"""
import json
import logging
import os
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class CheckpointInfo:
    """Checkpoint 元信息"""
    id: str
    user_id: str
    created_at: str
    session_count: int
    description: str


class CheckpointManager:
    """
    Agent 状态快照管理
    """

    def __init__(self, base_path: str = "./storage/checkpoints"):
        self.base_path = base_path
        os.makedirs(base_path, exist_ok=True)

    def save(self, agent_state: Dict, checkpoint_id: Optional[str] = None) -> str:
        """
        保存 Agent 完整状态快照
        返回 checkpoint_id
        """
        if checkpoint_id is None:
            checkpoint_id = datetime.now().strftime("%Y%m%d_%H%M%S")

        path = os.path.join(self.base_path, f"{checkpoint_id}.json")

        # 添加元信息
        state = {
            "_meta": {
                "checkpoint_id": checkpoint_id,
                "created_at": datetime.now().isoformat(),
                "version": "3.2",
            },
            **agent_state
        }

        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)

        logger.info(f"[Checkpoint] 已保存: {checkpoint_id}")
        return checkpoint_id

    def load(self, checkpoint_id: str) -> Optional[Dict]:
        """加载快照"""
        path = os.path.join(self.base_path, f"{checkpoint_id}.json")
        if not os.path.exists(path):
            logger.warning(f"[Checkpoint] 未找到: {checkpoint_id}")
            return None

        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"[Checkpoint] 加载失败: {e}")
            return None

    def list_checkpoints(self, user_id: str = "default") -> List[CheckpointInfo]:
        """列出所有可用的 checkpoints"""
        checkpoints = []
        for filename in sorted(os.listdir(self.base_path), reverse=True):
            if not filename.endswith(".json"):
                continue
            try:
                path = os.path.join(self.base_path, filename)
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                meta = data.get("_meta", {})
                checkpoints.append(CheckpointInfo(
                    id=meta.get("checkpoint_id", filename[:-5]),
                    user_id=user_id,
                    created_at=meta.get("created_at", ""),
                    session_count=data.get("session_count", 0),
                    description=data.get("task", ""),
                ))
            except Exception:
                continue
        return checkpoints

    def delete(self, checkpoint_id: str) -> bool:
        """删除快照"""
        path = os.path.join(self.base_path, f"{checkpoint_id}.json")
        if os.path.exists(path):
            os.remove(path)
            return True
        return False

    def get_latest(self, user_id: str = "default") -> Optional[str]:
        """获取最新的 checkpoint id"""
        checkpoints = self.list_checkpoints(user_id)
        return checkpoints[0].id if checkpoints else None
