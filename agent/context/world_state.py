"""
WorldState 模块
维护 Agent 对当前环境的认知：
- 工具可用性（MCP 在线状态）
- 文件系统快照
- Agent 自身资源（已用 token、会话计数）
Planner 在分解任务时查询 WorldState，基于真实可用性做决策
"""
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class WorldState:
    """
    世界状态：Agent 对自身能力和环境的显式认知
    """

    def __init__(self, mcp_client=None, base_path: str = "."):
        self.mcp_client = mcp_client
        self.base_path = os.path.abspath(base_path)
        self._tool_status: Dict[str, bool] = {}
        self._file_cache: Dict[str, Dict[str, Any]] = {}
        self._token_usage: int = 0
        self._last_updated: str = datetime.now().isoformat()

    # ── 工具状态 ──

    def refresh_tool_status(self):
        """刷新 MCP 工具可用性"""
        if self.mcp_client:
            try:
                tools = self.mcp_client.list_tools()
                self._tool_status = {t.name: True for t in tools}
            except Exception:
                self._tool_status = {}
        else:
            self._tool_status = {}
        self._last_updated = datetime.now().isoformat()

    def list_available_tools(self) -> List[str]:
        """列出当前可用工具"""
        return list(self._tool_status.keys())

    def is_tool_available(self, tool_name: str) -> bool:
        """检查某个工具是否可用"""
        return self._tool_status.get(tool_name, False)

    # ── 文件系统快照 ──

    def snapshot_files(self, path: str = ".", max_depth: int = 2) -> Dict[str, Any]:
        """
        创建文件系统快照（限制深度，避免扫描过大目录）
        """
        resolved = os.path.abspath(os.path.join(self.base_path, path))
        if not resolved.startswith(self.base_path):
            return {}

        snapshot = {}
        try:
            for root, dirs, files in os.walk(resolved):
                depth = root[len(resolved):].count(os.sep)
                if depth >= max_depth:
                    del dirs[:]
                    continue
                rel_root = os.path.relpath(root, self.base_path)
                for f in files:
                    if f.startswith("."):
                        continue
                    full = os.path.join(root, f)
                    try:
                        stat = os.stat(full)
                        snapshot[os.path.join(rel_root, f)] = {
                            "size": stat.st_size,
                            "mtime": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                        }
                    except OSError:
                        pass
        except Exception as e:
            logger.warning(f"[WorldState] 文件快照失败: {e}")

        self._file_cache = snapshot
        self._last_updated = datetime.now().isoformat()
        return snapshot

    def file_exists(self, filepath: str) -> bool:
        """检查文件是否存在"""
        resolved = os.path.abspath(os.path.join(self.base_path, filepath))
        if not resolved.startswith(self.base_path):
            return False
        return os.path.exists(resolved)

    # ── 资源追踪 ──

    def record_token_usage(self, tokens: int):
        """记录 token 消耗"""
        self._token_usage += tokens

    def get_token_usage(self) -> int:
        return self._token_usage

    # ── 快照汇总 ──

    def to_context_string(self) -> str:
        """生成给 LLM 的环境上下文描述"""
        parts = ["【环境状态】"]

        tools = self.list_available_tools()
        if tools:
            parts.append(f"可用工具: {', '.join(tools)}")
        else:
            parts.append("可用工具: 基础工具（calc, read, write, edit, map, test, git）")

        if self._file_cache:
            py_files = [f for f in self._file_cache if f.endswith(".py")]
            parts.append(f"项目文件: {len(self._file_cache)} 个（{len(py_files)} 个 Python 文件）")

        parts.append(f"累计 token 消耗: {self._token_usage}")
        parts.append(f"状态更新时间: {self._last_updated}")

        return "\n".join(parts)
