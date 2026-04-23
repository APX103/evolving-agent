"""
LLM 调用专用日志器
记录每次 LLM 调用的模型、token、延迟、成本、样本
"""
import json
import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 默认成本: $/1M tokens（可覆盖）
DEFAULT_COST_RATES: Dict[str, Dict[str, float]] = {
    "kimi-latest": {"input": 2.0, "output": 8.0},
    "kimi-k2-0711": {"input": 2.0, "output": 8.0},
    "moonshot-v1-8k": {"input": 1.0, "output": 2.0},
    "moonshot-v1-32k": {"input": 2.0, "output": 4.0},
    "moonshot-v1-128k": {"input": 4.0, "output": 8.0},
    "text-embedding": {"input": 0.5, "output": 0.0},
    "gpt-4o": {"input": 5.0, "output": 15.0},
    "gpt-4o-mini": {"input": 0.15, "output": 0.6},
    "claude-3-5-sonnet": {"input": 3.0, "output": 15.0},
    "default": {"input": 2.0, "output": 8.0},
}


class LLMLogger:
    """
    记录 LLM 调用详情到 storage/logs/llm_calls.jsonl
    """

    def __init__(
        self,
        log_path: str = "./storage/logs/llm_calls.jsonl",
        cost_rates: Optional[Dict[str, Dict[str, float]]] = None,
    ):
        self.log_path = log_path
        self.cost_rates = cost_rates or DEFAULT_COST_RATES
        os.makedirs(os.path.dirname(log_path), exist_ok=True)

    def log_call(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: float,
        prompt_sample: str = "",
        response_sample: str = "",
        trace_id: Optional[str] = None,
        span_id: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """记录一次 LLM 调用，返回记录对象（含 cost_usd）"""
        cost_usd = self.calculate_cost(model, prompt_tokens, completion_tokens)
        record = {
            "timestamp": datetime.now().isoformat(),
            "trace_id": trace_id,
            "span_id": span_id,
            "model": model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "latency_ms": round(latency_ms, 2),
            "cost_usd": round(cost_usd, 6),
            "prompt_sample": self._truncate(prompt_sample, 500),
            "response_sample": self._truncate(response_sample, 500),
        }
        if extra:
            record.update(extra)

        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except Exception as e:
            logger.warning(f"[LLMLogger] 写入失败: {e}")

        return record

    def calculate_cost(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        """计算调用成本（USD）"""
        rates = self.cost_rates.get(model, self.cost_rates.get("default", {"input": 0, "output": 0}))
        input_rate = rates.get("input", 0)
        output_rate = rates.get("output", 0)
        return (prompt_tokens * input_rate + completion_tokens * output_rate) / 1_000_000

    @staticmethod
    def _truncate(text: str, max_len: int) -> str:
        if not text:
            return ""
        return text[:max_len] + ("..." if len(text) > max_len else "")

    def get_recent(self, hours: int = 24, limit: int = 1000) -> List[Dict[str, Any]]:
        """获取最近 LLM 调用记录"""
        if not os.path.exists(self.log_path):
            return []

        cutoff = time.time() - hours * 3600
        records = []
        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    rec = json.loads(line)
                    ts_str = rec.get("timestamp", "")
                    try:
                        ts = datetime.fromisoformat(ts_str).timestamp()
                    except Exception:
                        ts = 0
                    if ts >= cutoff:
                        records.append(rec)
        except Exception as e:
            logger.warning(f"[LLMLogger] 读取失败: {e}")

        records.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return records[:limit]

    def get_aggregates(self, hours: int = 24) -> Dict[str, Any]:
        """聚合统计"""
        records = self.get_recent(hours=hours, limit=100_000)
        if not records:
            return {"total_calls": 0, "total_tokens": 0, "total_cost_usd": 0, "avg_latency_ms": 0}

        total_calls = len(records)
        total_tokens = sum(r.get("total_tokens", 0) for r in records)
        total_cost = sum(r.get("cost_usd", 0) for r in records)
        avg_latency = sum(r.get("latency_ms", 0) for r in records) / total_calls

        return {
            "total_calls": total_calls,
            "total_tokens": total_tokens,
            "total_cost_usd": round(total_cost, 4),
            "avg_latency_ms": round(avg_latency, 2),
            "period_hours": hours,
        }


# 全局单例
_global_llm_logger: Optional[LLMLogger] = None


def get_llm_logger() -> LLMLogger:
    global _global_llm_logger
    if _global_llm_logger is None:
        _global_llm_logger = LLMLogger()
    return _global_llm_logger


def set_llm_logger(logger_instance: LLMLogger) -> None:
    global _global_llm_logger
    _global_llm_logger = logger_instance
