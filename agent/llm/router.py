"""
Model Router - multi-tier model routing with fallback
"""
import logging
import re
from typing import Any, AsyncGenerator, Dict, Generator, List, Optional, Union

import numpy as np

from agent.llm.base import LLMClient, StructuredOutputError
from agent.llm.kimi_client import KimiLLMClient
from agent.config import Config

logger = logging.getLogger(__name__)

_SIMPLE_PATTERNS = [
    r"^(hi|hello|hey|你好|您好|哈嘶|嗨|在吗|在么)\s*[!！\.]*$",
    r"^(good morning|good afternoon|good evening|早上好|下午好|晚上好)\s*[!！\.]*$",
    r"^(bye|goodbye|再见|拜拜|拜)\s*[!！\.]*$",
    r"^(thanks|thank you|谢谢|感谢|多谢)\s*[!！\.]*$",
    r"^(ok|okay|好的|知道了|明白|嗯|哦)\s*[!！\.]*$",
    r"^(how are you|你好吗|最近怎么样|最近如何)\s*[?？]*$",
    r"^(开心|难过|伤心|累|烦|无聊|孤独|焦虑|兴奋|生气|愤怒|害怕)\s*[!！\.]*$",
]

_HEAVY_INDICATORS = [
    r"(写代码|代码|编程|programming|implement|debug|traceback|error|exception)",
    r"(多步|multi.step|plan|reasoning|analyze deeply|深度分析|推理|逻辑导派)",
    r"(class\s+\w+|def\s+\w+|function\s+\w+|import\s+\w+)",
    r"(算法|algorithm|optimize|优化|refactor|重构|architecture|架构)",
]


class ModelRouter(LLMClient):
    """Model router: auto-select lightweight/standard/heavy models by task complexity"""

    def __init__(
        self,
        config: Optional[Config] = None,
        clients: Optional[Dict[str, LLMClient]] = None,
    ):
        self.cfg = config or Config()
        self._costs: Dict[str, Dict[str, float]] = {
            "lightweight": {"calls": 0.0, "prompt_tokens": 0.0, "completion_tokens": 0.0, "cost": 0.0},
            "standard": {"calls": 0.0, "prompt_tokens": 0.0, "completion_tokens": 0.0, "cost": 0.0},
            "heavy": {"calls": 0.0, "prompt_tokens": 0.0, "completion_tokens": 0.0, "cost": 0.0},
        }
        self._cost_per_1k: Dict[str, Dict[str, float]] = {
            "lightweight": {"prompt": 0.0, "completion": 0.0},
            "standard": {"prompt": 0.0, "completion": 0.0},
            "heavy": {"prompt": 0.0, "completion": 0.0},
        }
        self._clients: Dict[str, LLMClient] = {}
        self._default_tier: Optional[str] = None

        if clients:
            self._clients = dict(clients)
            self._init_cost_config()
        else:
            self._init_from_config()

    def _init_cost_config(self) -> None:
        tier_cfg = self.cfg.raw.get("model_tiers", {})
        for tier in ("lightweight", "standard", "heavy"):
            cost = tier_cfg.get("cost_per_1k_tokens", {}).get(tier, {})
            self._cost_per_1k[tier] = {
                "prompt": cost.get("prompt", 0.0),
                "completion": cost.get("completion", 0.0),
            }

    def _init_from_config(self) -> None:
        kimi_cfg = self.cfg.kimi
        base_model = kimi_cfg.get("model", "kimi-latest")
        tier_cfg = self.cfg.raw.get("model_tiers", {})

        has_tiers = any(
            tier_cfg.get(f"{t}_model") for t in ("lightweight", "standard", "heavy")
        )

        if not has_tiers:
            client = KimiLLMClient(self.cfg)
            self._clients = {"lightweight": client, "standard": client, "heavy": client}
            self._init_cost_config()
            return

        for tier in ("lightweight", "standard", "heavy"):
            tier_model = tier_cfg.get(f"{tier}_model", base_model)
            client = KimiLLMClient(self.cfg, model=tier_model)
            self._clients[tier] = client

        self._init_cost_config()

    @property
    def default_tier(self) -> Optional[str]:
        return self._default_tier

    @default_tier.setter
    def default_tier(self, tier: Optional[str]) -> None:
        if tier is not None and tier not in self._clients:
            logger.warning("[ModelRouter] Unknown tier %s, ignoring", tier)
            return
        self._default_tier = tier

    def select_model(self, task_complexity: str) -> LLMClient:
        tier = self._complexity_to_tier(task_complexity)
        return self._clients.get(tier, self._clients["standard"])

    def _complexity_to_tier(self, complexity: str) -> str:
        mapping = {
            "simple": "lightweight",
            "standard": "standard",
            "heavy": "heavy",
        }
        return mapping.get(complexity, "standard")

    def estimate_complexity(self, prompt: Union[str, List[Dict[str, str]]]) -> str:
        if isinstance(prompt, list):
            prompt_text = "".join(m.get("content", "") for m in prompt)
        else:
            prompt_text = prompt

        text_lower = prompt_text.strip().lower()

        for pattern in _SIMPLE_PATTERNS:
            if re.match(pattern, text_lower):
                return "simple"

        stripped = prompt_text.strip()
        if len(stripped) < 150:
            # Even short texts can be heavy (e.g. code snippets)
            for ind in _HEAVY_INDICATORS:
                if re.search(ind, stripped, re.IGNORECASE):
                    return "heavy"
            if re.match(r"^[^，。！；\n]{1,150}[?？]$", stripped):
                return "simple"
            if len(stripped) < 30:
                return "simple"

        for ind in _HEAVY_INDICATORS:
            if re.search(ind, prompt_text, re.IGNORECASE):
                return "heavy"

        return "standard"

    def _resolve_tier(self, prompt: Optional[Union[str, List[Dict[str, str]]]] = None) -> str:
        if self._default_tier:
            return self._default_tier
        if prompt is not None:
            return self._complexity_to_tier(self.estimate_complexity(prompt))
        return "standard"

    def _track_cost(self, tier: str, prompt_tokens: int, completion_tokens: int) -> None:
        self._costs[tier]["calls"] += 1
        self._costs[tier]["prompt_tokens"] += prompt_tokens
        self._costs[tier]["completion_tokens"] += completion_tokens
        p_cost = (prompt_tokens / 1000.0) * self._cost_per_1k[tier]["prompt"]
        c_cost = (completion_tokens / 1000.0) * self._cost_per_1k[tier]["completion"]
        self._costs[tier]["cost"] += p_cost + c_cost

    def _read_client_usage(self, client: LLMClient) -> tuple[int, int]:
        prompt = getattr(client, "_last_prompt_tokens", 0) or 0
        completion = getattr(client, "_last_completion_tokens", 0) or 0
        return int(prompt), int(completion)

    def get_cost_summary(self) -> Dict[str, Any]:
        total = {
            "calls": sum(t["calls"] for t in self._costs.values()),
            "prompt_tokens": sum(t["prompt_tokens"] for t in self._costs.values()),
            "completion_tokens": sum(t["completion_tokens"] for t in self._costs.values()),
            "cost": sum(t["cost"] for t in self._costs.values()),
        }
        return {
            "lightweight": dict(self._costs["lightweight"]),
            "standard": dict(self._costs["standard"]),
            "heavy": dict(self._costs["heavy"]),
            "total": total,
        }

    # ------------------------------------------------------------------
    # Sync interface
    # ------------------------------------------------------------------

    def chat(
        self,
        messages: List[Dict[str, Any]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stream: bool = False,
    ) -> Union[str, Generator[str, None, None]]:
        tier = self._resolve_tier(messages)
        client = self._clients.get(tier, self._clients["standard"])

        if stream:
            return client.chat(messages, temperature=temperature, max_tokens=max_tokens, stream=True)

        tiers_order = ["lightweight", "standard", "heavy"]
        start = tiers_order.index(tier) if tier in tiers_order else 1
        for i in range(start, len(tiers_order)):
            t = tiers_order[i]
            c = self._clients.get(t)
            if c is None:
                continue
            try:
                result = c.chat(messages, temperature=temperature, max_tokens=max_tokens, stream=False)
                pt, ct = self._read_client_usage(c)
                self._track_cost(t, pt, ct)
                return result
            except Exception as e:
                logger.warning("[ModelRouter] tier %s failed: %s", t, e)
        raise RuntimeError(f"All model tiers failed starting from {tier}")

    def quick_chat(self, prompt: str, system: str = "") -> str:
        tier = self._resolve_tier(prompt)
        tiers_order = ["lightweight", "standard", "heavy"]
        start = tiers_order.index(tier) if tier in tiers_order else 1
        for i in range(start, len(tiers_order)):
            t = tiers_order[i]
            c = self._clients.get(t)
            if c is None:
                continue
            try:
                result = c.quick_chat(prompt, system=system)
                pt, ct = self._read_client_usage(c)
                self._track_cost(t, pt, ct)
                return result
            except Exception as e:
                logger.warning("[ModelRouter] tier %s failed: %s", t, e)
        raise RuntimeError(f"All model tiers failed starting from {tier}")

    def embed(self, texts: Union[str, List[str]]) -> np.ndarray:
        client = self._clients.get("standard", list(self._clients.values())[0])
        return client.embed(texts)

    def cosine_similarity(self, query_vec: np.ndarray, doc_vecs: np.ndarray) -> np.ndarray:
        client = self._clients.get("standard", list(self._clients.values())[0])
        return client.cosine_similarity(query_vec, doc_vecs)

    # ------------------------------------------------------------------
    # Async interface
    # ------------------------------------------------------------------

    async def achat(
        self,
        messages: List[Dict[str, Any]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stream: bool = False,
    ) -> Union[str, AsyncGenerator[str, None]]:
        tier = self._resolve_tier(messages)
        client = self._clients.get(tier, self._clients["standard"])

        if stream:
            return await client.achat(messages, temperature=temperature, max_tokens=max_tokens, stream=True)

        tiers_order = ["lightweight", "standard", "heavy"]
        start = tiers_order.index(tier) if tier in tiers_order else 1
        for i in range(start, len(tiers_order)):
            t = tiers_order[i]
            c = self._clients.get(t)
            if c is None:
                continue
            try:
                result = await c.achat(messages, temperature=temperature, max_tokens=max_tokens, stream=False)
                pt, ct = self._read_client_usage(c)
                self._track_cost(t, pt, ct)
                return result
            except Exception as e:
                logger.warning("[ModelRouter] tier %s failed: %s", t, e)
        raise RuntimeError(f"All model tiers failed starting from {tier}")

    async def aquick_chat(self, prompt: str, system: str = "") -> str:
        tier = self._resolve_tier(prompt)
        tiers_order = ["lightweight", "standard", "heavy"]
        start = tiers_order.index(tier) if tier in tiers_order else 1
        for i in range(start, len(tiers_order)):
            t = tiers_order[i]
            c = self._clients.get(t)
            if c is None:
                continue
            try:
                result = await c.aquick_chat(prompt, system=system)
                pt, ct = self._read_client_usage(c)
                self._track_cost(t, pt, ct)
                return result
            except Exception as e:
                logger.warning("[ModelRouter] tier %s failed: %s", t, e)
        raise RuntimeError(f"All model tiers failed starting from {tier}")

    async def aembed(self, texts: Union[str, List[str]]) -> np.ndarray:
        client = self._clients.get("standard", list(self._clients.values())[0])
        return await client.aembed(texts)
