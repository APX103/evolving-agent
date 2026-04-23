"""
程序记忆 (Procedural Memory)
记录从交互中学习到的有效行为策略，自动注入 system prompt
支持关键词匹配 + 向量语义检索 hybrid 召回
"""
import json
import logging
import os
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)


class ProceduralRule:
    """单条程序规则"""
    def __init__(
        self,
        pattern: str,
        action: str,
        confidence: float = 0.5,
        usage_count: int = 0,
        created_at: Optional[str] = None,
        last_used: Optional[str] = None,
    ):
        self.pattern = pattern
        self.action = action
        self.confidence = confidence
        self.usage_count = usage_count
        self.created_at = created_at or datetime.now().isoformat()
        self.last_used = last_used or self.created_at

    def to_dict(self) -> Dict:
        return {
            "pattern": self.pattern,
            "action": self.action,
            "confidence": self.confidence,
            "usage_count": self.usage_count,
            "created_at": self.created_at,
            "last_used": self.last_used,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "ProceduralRule":
        return cls(**d)


class ProceduralMemory:
    """
    程序记忆管理器
    - 存储行为规则（当用户...时，我应该...）
    - 基于简单关键词匹配检索相关规则
    - 高置信度规则自动注入 system prompt
    """

    CONFIDENCE_THRESHOLD = 0.7
    MAX_RULES_IN_PROMPT = 5

    def __init__(self, storage_path: str, storage=None, llm_client=None):
        from agent.storage.local_json import LocalJsonStorage
        self.storage = storage or LocalJsonStorage()
        self.storage_path = storage_path
        self.storage.ensure_dir(self.storage_path)
        self.llm_client = llm_client
        self._embedding_available = llm_client is not None
        self._vectors: Optional[np.ndarray] = None
        self._rules: List[ProceduralRule] = []
        self._load()
        self._build_vectors()

    # ── 持久化 ──

    def _file_path(self) -> str:
        return os.path.join(self.storage_path, "procedural_memory.json")

    def _load(self):
        data = self.storage.load_json("procedural_memory.json", self.storage_path, default=[])
        self._rules = [ProceduralRule.from_dict(r) for r in data]
        logger.info(f"[ProceduralMemory] 加载 {len(self._rules)} 条规则")

    def _save(self):
        data = [r.to_dict() for r in self._rules]
        self.storage.save_json(data, "procedural_memory.json", self.storage_path)

    # ── 规则管理 ──

    def add_rule(self, pattern: str, action: str, confidence: float = 0.7) -> ProceduralRule:
        """添加新规则（如果 pattern 已存在则合并/升级）"""
        for rule in self._rules:
            if rule.pattern.lower() == pattern.lower():
                rule.confidence = max(rule.confidence, confidence)
                rule.action = action
                rule.usage_count += 1
                rule.last_used = datetime.now().isoformat()
                self._save()
                logger.info(f"[ProceduralMemory] 升级规则: {pattern}")
                return rule

        rule = ProceduralRule(pattern=pattern, action=action, confidence=confidence)
        self._rules.append(rule)
        self._save()
        logger.info(f"[ProceduralMemory] 新增规则: {pattern}")
        return rule

    def remove_rule(self, pattern: str) -> bool:
        """删除规则"""
        for i, rule in enumerate(self._rules):
            if rule.pattern.lower() == pattern.lower():
                self._rules.pop(i)
                self._save()
                return True
        return False

    def list_rules(self) -> List[ProceduralRule]:
        return list(self._rules)

    # ── 检索 ──

    def _build_vectors(self):
        """为所有规则构建向量索引"""
        if not self._embedding_available or not self._rules:
            self._vectors = None
            return
        try:
            texts = [f"{r.pattern} {r.action}" for r in self._rules]
            self._vectors = self.llm_client.embed(texts)
        except Exception as e:
            logger.debug(f"[ProceduralMemory] 向量构建失败: {e}")
            self._vectors = None

    def _rebuild_vector_for(self, rule: ProceduralRule):
        """为单条规则重建向量"""
        if not self._embedding_available:
            return
        self._build_vectors()

    def get_relevant_rules(self, query: str, top_k: int = 5) -> List[ProceduralRule]:
        """
        Hybrid 检索：关键词匹配 + 向量语义检索
        综合评分后返回最相关的规则
        """
        if not self._rules:
            return []

        query_lower = query.lower()
        keyword_scores: Dict[int, float] = {}

        # 1. 关键词匹配评分
        for i, rule in enumerate(self._rules):
            score = 0.0
            if rule.pattern.lower() in query_lower or query_lower in rule.pattern.lower():
                score += 2.0
            if rule.action.lower() in query_lower or query_lower in rule.action.lower():
                score += 1.0
            query_words = set(query_lower.split())
            pattern_words = set(rule.pattern.lower().split())
            action_words = set(rule.action.lower().split())
            overlap = len(query_words & pattern_words) + len(query_words & action_words)
            score += overlap * 0.5
            score += rule.confidence * 1.5 + min(rule.usage_count, 10) * 0.1
            if score > 0:
                keyword_scores[i] = score

        # 2. 向量语义检索（如果有 LLM client）
        vector_scores: Dict[int, float] = {}
        if self._embedding_available and self._vectors is not None and len(self._vectors) == len(self._rules):
            try:
                query_vec = self.llm_client.embed(query)
                sims = self.llm_client.cosine_similarity(query_vec[0], self._vectors)
                for i, sim in enumerate(sims):
                    if sim > 0.5:
                        vector_scores[i] = float(sim) * 3.0  # 向量匹配权重
            except Exception as e:
                logger.debug(f"[ProceduralMemory] 向量检索失败: {e}")

        # 3. 综合评分
        all_indices = set(keyword_scores.keys()) | set(vector_scores.keys())
        scored = []
        for idx in all_indices:
            total = keyword_scores.get(idx, 0) + vector_scores.get(idx, 0)
            scored.append((total, self._rules[idx]))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in scored[:top_k]]

    def get_prompt_text(self, query: str = "") -> str:
        """生成可注入 system prompt 的规则文本"""
        rules = self.get_relevant_rules(query, top_k=self.MAX_RULES_IN_PROMPT)
        high_confidence = [r for r in rules if r.confidence >= self.CONFIDENCE_THRESHOLD]
        if not high_confidence:
            return ""
        lines = ["【 learned behaviors 】"]
        for i, rule in enumerate(high_confidence, 1):
            lines.append(f"{i}. 当用户{rule.pattern}时，{rule.action}")
        return "\n".join(lines)

    # ── 学习接口 ──

    def learn_from_feedback(
        self,
        user_input: str,
        agent_response: str,
        feedback: str,  # "positive" | "negative" | "corrected"
        correction: str = "",
    ):
        """
        从用户反馈中学习程序规则
        简单启发式：如果反馈是 positive，尝试提取行为模式
        """
        if feedback == "positive":
            # 简单规则：用户问技术问题 → 先确认技术栈
            if any(kw in user_input.lower() for kw in ["怎么", "如何", "为什么", "错误", "bug"]):
                self.add_rule(
                    pattern="询问技术问题",
                    action="先确认用户使用的技术栈和版本，再给出针对性建议",
                    confidence=0.75,
                )
        elif feedback == "corrected" and correction:
            self.add_rule(
                pattern=f"类似 '{user_input[:30]}...' 的场景",
                action=f"注意：{correction}",
                confidence=0.85,
            )
