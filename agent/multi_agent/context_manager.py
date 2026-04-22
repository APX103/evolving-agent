"""
上下文管理器 - 六层架构，总预算 3500 tokens
"""
import asyncio
import logging
import json
import os
from datetime import datetime
from typing import Dict, List, Optional, Any

from agent.multi_agent.base import AgentContext, LayerType
from agent.multi_agent.token_counter import TokenCounter

logger = logging.getLogger(__name__)


class ContextManager:
    BUDGET = {
        LayerType.SYSTEM: 500,
        LayerType.ETERNAL: 300,
        LayerType.SUMMARIES: 800,
        LayerType.WORKING: 200,
        LayerType.RECENT: 1500,
        LayerType.RULES: 200,
    }
    TOTAL_BUDGET = 3500
    NEW_SESSION_BUDGET = 1800

    def __init__(self, memory, llm_client, config: Optional[Dict] = None):
        self.memory = memory
        self.llm = llm_client
        self.config = config or {}
        self._token_counter = TokenCounter()
        self._summaries_cache: Dict[str, List[str]] = {}

    def _estimate_tokens(self, text: str) -> int:
        return self._token_counter.count(text)

    def _estimate_messages_tokens(self, messages: List[Dict]) -> int:
        return self._token_counter.count_messages(messages)

    async def build_context(self, user_id: str, query: str = "", source: str = "cli") -> AgentContext:
        layers = {}

        # Layer 1: Eternal Memory
        eternal = self._load_eternal_memory(user_id)
        if eternal:
            eternal_text = self._trim_to_budget(eternal, self.BUDGET[LayerType.ETERNAL])
            layers[LayerType.ETERNAL] = eternal_text

        # Layer 2: Session Summaries
        summaries = self._load_session_summaries(user_id)
        if summaries:
            summaries_text = self._format_summaries(summaries)
            summaries_text = self._trim_to_budget(summaries_text, self.BUDGET[LayerType.SUMMARIES])
            layers[LayerType.SUMMARIES] = summaries_text

        # Layer 3: Working Context
        working = self._load_working_context(user_id)
        if working:
            working_text = json.dumps(working, ensure_ascii=False, indent=2)
            working_text = self._trim_to_budget(working_text, self.BUDGET[LayerType.WORKING])
            layers[LayerType.WORKING] = working_text

        # Layer 5: Procedural Rules
        rules = self._load_procedural_rules(user_id)
        if rules:
            rules_text = self._format_rules(rules)
            rules_text = self._trim_to_budget(rules_text, self.BUDGET[LayerType.RULES])
            layers[LayerType.RULES] = rules_text

        # Layer 4: Recent Turns (from memory.short_term)
        short_term = self.memory.short_term.copy() if hasattr(self.memory, 'short_term') else []

        # 检查是否需要压缩
        if short_term:
            short_term = await self.compress_if_needed(user_id, short_term)

        return AgentContext(
            user_id=user_id,
            source=source,
            layers=layers,
            short_term=short_term,
            working_memory={},
            metadata={"query": query, "timestamp": datetime.now().isoformat()}
        )

    async def on_new_session(self, user_id: str) -> AgentContext:
        """新会话启动：L1(必带) + L2(裁剪) + L3 + L5，前置 ~1800 tokens"""
        ctx = await self.build_context(user_id, source="cli")
        ctx.metadata["session_start"] = True
        return ctx

    async def compress_if_needed(self, user_id: str, short_term: List[Dict]) -> List[Dict]:
        if not short_term:
            return short_term

        tokens = self._estimate_messages_tokens(short_term)
        budget = self.BUDGET[LayerType.RECENT]

        if tokens <= budget:
            return short_term

        # 超限时：最旧 50% 轮次 → LLM 摘要 → 移至 Layer 2
        cutoff = len(short_term) // 2
        to_summarize = short_term[:cutoff]
        kept = short_term[cutoff:]

        summary = await self._generate_summary(to_summarize)
        if summary:
            self._append_session_summary(user_id, summary)
            logger.info(f"[ContextManager] 压缩 {len(to_summarize)} 条消息为摘要 ({self._estimate_tokens(summary)} tokens)")

        return kept

    async def _generate_summary(self, turns: List[Dict]) -> str:
        if not turns:
            return ""

        transcript = []
        for turn in turns:
            role = "User" if turn.get("role") == "user" else "Assistant"
            content = turn.get("content", "")
            if len(content) > 200:
                content = content[:200] + "..."
            transcript.append(f"{role}: {content}")

        if self.llm and len(turns) >= 4:
            try:
                prompt = (
                    "请将以下对话压缩为一段简洁摘要，保留关键决策、用户意图和重要信息，"
                    "丢弃重复和无关细节。用中文输出，不超过 200 字：\n\n"
                    + "\n".join(transcript)
                    + "\n\n摘要："
                )
                import asyncio
                if hasattr(self.llm, 'quick_chat'):
                    loop = asyncio.get_event_loop()
                    summary = await loop.run_in_executor(None, lambda: self.llm.quick_chat(prompt, ""))
                else:
                    summary = ""
                return summary.strip()
            except Exception as e:
                logger.warning(f"[ContextManager] LLM 摘要失败: {e}")

        return self._simple_summarize(turns)

    def _simple_summarize(self, turns: List[Dict]) -> str:
        parts = []
        for turn in turns:
            role = turn.get("role", "")
            content = turn.get("content", "")[:120]
            parts.append(f"{role}: {content}")
        return "\n".join(parts)

    def _trim_to_budget(self, text: str, budget: int) -> str:
        if self._estimate_tokens(text) <= budget:
            return text
        # 二分查找裁剪点
        low, high = 0, len(text)
        while low < high:
            mid = (low + high + 1) // 2
            if self._estimate_tokens(text[:mid]) <= budget:
                low = mid
            else:
                high = mid - 1
        return text[:low]

    def _load_eternal_memory(self, user_id: str) -> str:
        try:
            profile = self.memory.get_profile() if hasattr(self.memory, 'get_profile') else {}
            if profile:
                items = [f"- {k}: {v}" for k, v in list(profile.items())[:5]]
                return "\n".join(items)
        except Exception as e:
            logger.debug(f"[ContextManager] 加载 eternal memory 失败: {e}")
        return ""

    def _load_session_summaries(self, user_id: str) -> List[str]:
        return self._summaries_cache.get(user_id, [])

    def _append_session_summary(self, user_id: str, summary: str):
        if user_id not in self._summaries_cache:
            self._summaries_cache[user_id] = []
        self._summaries_cache[user_id].append(summary)

    def _load_working_context(self, user_id: str) -> Dict:
        try:
            if hasattr(self.memory, 'working_memory'):
                return self.memory.working_memory
        except Exception:
            pass
        return {}

    def _load_procedural_rules(self, user_id: str) -> List[Dict]:
        try:
            if hasattr(self.memory, 'procedural_memory'):
                pm = self.memory.procedural_memory
                if hasattr(pm, 'rules'):
                    return pm.rules[:5]
        except Exception:
            pass
        return []

    def _format_summaries(self, summaries: List[str]) -> str:
        parts = ["【历史会话摘要】"]
        for i, s in enumerate(reversed(summaries[-10:])):
            parts.append(f"会话 {len(summaries)-i}: {s}")
        return "\n".join(parts)

    def _format_rules(self, rules: List[Dict]) -> str:
        parts = ["【行为策略】"]
        for r in rules[:5]:
            content = r.get("content", r.get("rule", str(r)))
            parts.append(f"- {content}")
        return "\n".join(parts)
