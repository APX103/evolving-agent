"""
记忆命名空间 - 多 Agent 隔离的记忆存储
shared/ (所有 Agent 共享) + agent_private/ (各 Agent 私有) + working/ (临时工作区)
"""
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class MemoryNamespace:
    """
    记忆命名空间管理
    按 user_id 隔离，支持共享/私有/工作区三级存储
    """

    def __init__(self, user_id: str, storage, base_path: str = "./storage"):
        self.user_id = user_id
        self.storage = storage
        self.base_path = os.path.join(base_path, user_id)
        self.logger = logging.getLogger(__name__)

        # 确保目录结构存在
        for subdir in ["shared", "companion", "coder", "researcher",
                       "writer", "planner", "executor", "reviewer", "working"]:
            path = os.path.join(self.base_path, subdir)
            if hasattr(storage, 'ensure_dir'):
                storage.ensure_dir(path)
            elif not os.path.exists(path):
                os.makedirs(path, exist_ok=True)

    # ── 共享记忆 (所有 Agent 只读/写) ──
    def _shared_path(self, filename: str) -> str:
        return os.path.join(self.base_path, "shared", filename)

    def load_shared(self, filename: str, default: Any = None) -> Any:
        """加载共享记忆"""
        try:
            dir_path = os.path.join(self.base_path, "shared")
            if hasattr(self.storage, 'load_json'):
                return self.storage.load_json(filename, dir_path, default=default)
        except Exception as e:
            self.logger.debug(f"[MemoryNamespace] 加载 shared/{filename} 失败: {e}")
        return default

    def save_shared(self, data: Any, filename: str):
        """保存共享记忆"""
        try:
            dir_path = os.path.join(self.base_path, "shared")
            if hasattr(self.storage, 'save_json'):
                self.storage.save_json(data, filename, dir_path)
            else:
                import json
                filepath = os.path.join(dir_path, filename)
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.error(f"[MemoryNamespace] 保存 shared/{filename} 失败: {e}")

    # ── Agent 私有记忆 ──
    def _agent_path(self, agent_name: str, filename: str) -> str:
        return os.path.join(self.base_path, agent_name, filename)

    def load_private(self, agent_name: str, filename: str, default: Any = None) -> Any:
        """加载 Agent 私有记忆"""
        try:
            dir_path = os.path.join(self.base_path, agent_name)
            if hasattr(self.storage, 'load_json'):
                return self.storage.load_json(filename, dir_path, default=default)
        except Exception as e:
            self.logger.debug(f"[MemoryNamespace] 加载 {agent_name}/{filename} 失败: {e}")
        return default

    def save_private(self, agent_name: str, data: Any, filename: str):
        """保存 Agent 私有记忆"""
        try:
            dir_path = os.path.join(self.base_path, agent_name)
            if hasattr(self.storage, 'save_json'):
                self.storage.save_json(data, filename, dir_path)
        except Exception as e:
            self.logger.error(f"[MemoryNamespace] 保存 {agent_name}/{filename} 失败: {e}")

    # ── 工作区 (临时) ──
    def _working_path(self, filename: str) -> str:
        return os.path.join(self.base_path, "working", filename)

    def load_working(self, filename: str, default: Any = None) -> Any:
        """加载工作区数据"""
        try:
            dir_path = os.path.join(self.base_path, "working")
            if hasattr(self.storage, 'load_json'):
                return self.storage.load_json(filename, dir_path, default=default)
        except Exception:
            pass
        return default

    def save_working(self, data: Any, filename: str):
        """保存工作区数据"""
        try:
            dir_path = os.path.join(self.base_path, "working")
            if hasattr(self.storage, 'save_json'):
                self.storage.save_json(data, filename, dir_path)
        except Exception as e:
            self.logger.error(f"[MemoryNamespace] 保存 working/{filename} 失败: {e}")

    def clear_working(self):
        """清空工作区"""
        import glob
        working_dir = os.path.join(self.base_path, "working")
        for f in glob.glob(os.path.join(working_dir, "*.json")):
            try:
                os.remove(f)
            except Exception:
                pass
        self.logger.info(f"[MemoryNamespace] 工作区已清空")

    # ── 便捷方法：知识库 (统一写入 shared，带 source_agent 标签) ──
    def add_knowledge(self, content: str, category: str = "general",
                      source_agent: str = "", confidence: float = 0.7) -> Dict:
        """添加知识到共享知识库，自动标记来源 Agent"""
        kb = self.load_shared("knowledge_base.json", default=[])

        item = {
            "id": f"k_{int(time.time() * 1000)}_{len(kb)}",
            "content": content,
            "category": category,
            "source_agent": source_agent,
            "confidence": confidence,
            "created_at": __import__('datetime').datetime.now().isoformat(),
        }
        kb.append(item)
        self.save_shared(kb, "knowledge_base.json")
        return item

    # ── 目录结构报告 ──
    def get_structure(self) -> Dict:
        """获取当前命名空间结构"""
        import time
        result = {"user_id": self.user_id, "base_path": self.base_path, "directories": {}}
        for subdir in ["shared", "companion", "coder", "researcher",
                       "writer", "planner", "executor", "reviewer", "working"]:
            path = os.path.join(self.base_path, subdir)
            if os.path.exists(path):
                files = [f for f in os.listdir(path) if f.endswith('.json')]
                result["directories"][subdir] = len(files)
        return result
