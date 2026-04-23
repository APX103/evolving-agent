"""
分层记忆系统 v3.1
MemoryManager 退化为协调器，内部委托给独立的 Store
- ShortTermStore: 当前会话
- WorkingMemoryStore: 本次关键点
- LongTermStore: 知识库（向量索引 + 语义搜索 + 去重合并）
- UserProfileStore: 用户画像
- ReflectionStore: 反思日志
"""
import logging
import os
from typing import Any, Dict, List, Optional

from agent.config import Config
from agent.llm.base import LLMClient
from agent.storage.base import StorageBackend
from agent.storage.local_json import LocalJsonStorage
from agent.knowledge_graph import KnowledgeGraph
from agent.context_compressor import ContextCompressor

from agent.memory.short_term import ShortTermStore
from agent.memory.working import WorkingMemoryStore
from agent.memory.long_term import LongTermStore
from agent.memory.user_profile import UserProfileStore
from agent.memory.reflections import ReflectionStore

logger = logging.getLogger(__name__)


class MemoryManager:
    """
    记忆协调器：组合多个独立 Store，保持原有 API 不变
    """

    def __init__(
        self,
        config: Optional[Config] = None,
        storage: Optional[StorageBackend] = None,
        llm_client: Optional[LLMClient] = None,
        base_path: Optional[str] = None,
    ):
        cfg = config or Config()
        self.config = cfg
        storage_cfg = cfg.storage

        self.storage = storage or LocalJsonStorage()
        self.base_path = base_path or storage_cfg.get("base_path", "./storage")

        self.conv_path = storage_cfg.get("conversations", os.path.join(self.base_path, "conversations"))
        self.knowledge_path = storage_cfg.get("knowledge", os.path.join(self.base_path, "knowledge"))
        self.profile_path = storage_cfg.get("user_profile", os.path.join(self.base_path, "user_profile"))
        self.reflection_path = storage_cfg.get("reflections", os.path.join(self.base_path, "reflections"))

        for p in [self.conv_path, self.knowledge_path, self.profile_path, self.reflection_path]:
            self.storage.ensure_dir(p)

        # 初始化各 Store
        self._short_term = ShortTermStore(storage=self.storage, conv_path=self.conv_path)
        self._working = WorkingMemoryStore(storage=self.storage)
        self._long_term = LongTermStore(
            storage=self.storage,
            knowledge_path=self.knowledge_path,
            llm_client=llm_client,
        )
        self._profile = UserProfileStore(storage=self.storage, profile_path=self.profile_path)
        self._reflections = ReflectionStore(storage=self.storage, reflection_path=self.reflection_path)

        # LLM 客户端
        self.llm_client = llm_client

        # 知识图谱（已独立）
        self.knowledge_graph = KnowledgeGraph(
            storage_path=os.path.join(self.knowledge_path, "graph")
        )

        # 上下文压缩器
        max_turns = self.config.agent.get("max_short_term_turns", 10)
        self.context_compressor = ContextCompressor(
            llm_client=self.llm_client,
            max_turns=max_turns,
        )

    # ── 兼容属性（委托给内部 Store）──

    @property
    def short_term(self) -> List[Dict[str, Any]]:
        return self._short_term.short_term

    @property
    def working_memory(self) -> Dict[str, Any]:
        return self._working.working_memory

    @property
    def knowledge_base(self) -> List[Dict[str, Any]]:
        return self._long_term.knowledge_base

    @property
    def user_profile(self) -> Dict[str, Any]:
        return self._profile.user_profile

    @property
    def reflections(self) -> List[Dict[str, Any]]:
        return self._reflections.reflections

    @property
    def session_count(self) -> int:
        return self._profile.session_count

    @session_count.setter
    def session_count(self, value: int):
        self._profile.session_count = value

    @property
    def session_id(self) -> str:
        return self._short_term.session_id

    # ── 短期记忆 ──

    def add_turn(self, role: str, content: str):
        self._short_term.add_turn(role, content)

    def get_short_term(self, max_turns: int = 10) -> List[Dict[str, Any]]:
        return self._short_term.get_short_term(max_turns)

    def get_context_messages(self, system_prompt: str, max_turns: int = 10, compress: bool = True) -> List[Dict[str, str]]:
        if compress and self.context_compressor:
            return self.context_compressor.get_full_compressed_context(system_prompt, self.short_term)
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(self.get_short_term(max_turns))
        return messages

    # ── 工作记忆 ──

    def set_working(self, key: str, value: Any):
        self._working.set_working(key, value)

    def get_working(self, key: str) -> Optional[Any]:
        return self._working.get_working(key)

    # ── 长期记忆（委托给 LongTermStore）──

    def add_knowledge(self, category: str, content: str, source: str = "") -> Dict[str, str]:
        return self._long_term.add_knowledge(category, content, source)

    def search_knowledge(self, query: str = "", category: str = "", limit: int = 10) -> List[Dict[str, Any]]:
        return self._long_term.search_knowledge(query, category, limit)

    def cleanup_stale_knowledge(self, days: int = 60, min_access: int = 1) -> int:
        return self._long_term.cleanup_stale_knowledge(days, min_access)

    # ── 用户画像 ──

    def update_profile(self, key: str, value: Any):
        self._profile.update_profile(key, value)

    def get_profile(self, key: str = "") -> Any:
        return self._profile.get_profile(key)

    # ── 反思日志 ──

    def add_reflection(self, reflection: Dict[str, Any]):
        self._reflections.add_reflection(reflection)

    # ── 会话管理 ──

    def end_session(self):
        self._short_term.end_session()
        self._working.clear()
        self._profile.increment_session_count()

    # ── 上下文组装 ──

    def get_relevant_context(self, query_hint: str = "", limit: int = 5) -> str:
        parts = []

        # 用户画像
        profile = self.get_profile()
        if profile:
            parts.append("【关于用户】")
            for k, v in list(profile.items())[:5]:
                parts.append(f"- {k}: {v}")

        # 知识图谱上下文
        if self.knowledge_graph:
            kg_context = self.knowledge_graph.to_context_string(subject="用户", limit=5)
            if kg_context:
                parts.append(f"\n{kg_context}")

        # 语义召回知识
        if query_hint:
            relevant = self.search_knowledge(query=query_hint, limit=limit)
        else:
            relevant = self.search_knowledge(category="", limit=limit)

        if relevant:
            parts.append("\n【我记住的相关知识】")
            for item in relevant:
                sim_tag = f"(相关度{item['_similarity']})" if item.get("_similarity", 0) > 0 else ""
                parts.append(f"- [{item['category']}] {item['content']} {sim_tag}".strip())

        # 最近反思
        recent_reflections = self._reflections.get_recent(3)
        if recent_reflections:
            last = recent_reflections[-1]
            parts.append(f"\n【我的自我认知】{last.get('summary', '')}")

        return "\n".join(parts) if parts else ""
