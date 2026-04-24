"""
性能监控 - 各 Agent 成功率、延迟、token 消耗统计
单机部署，纯内存 + 可选持久化到本地 JSON
"""
import logging
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# 全局单例（延迟初始化）
_global_perf_monitor: Optional["PerformanceMonitor"] = None


def get_performance_monitor() -> "PerformanceMonitor":
    """获取全局 PerformanceMonitor 单例"""
    global _global_perf_monitor
    if _global_perf_monitor is None:
        _global_perf_monitor = PerformanceMonitor()
    return _global_perf_monitor


@dataclass
class AgentMetrics:
    """单个 Agent 的性能指标"""
    agent_name: str
    total_calls: int = 0
    success_calls: int = 0
    failed_calls: int = 0
    total_latency_ms: float = 0.0
    total_tokens_input: int = 0
    total_tokens_output: int = 0
    last_called_at: str = ""
    errors: List[str] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        if self.total_calls == 0:
            return 0.0
        return self.success_calls / self.total_calls

    @property
    def avg_latency_ms(self) -> float:
        if self.total_calls == 0:
            return 0.0
        return self.total_latency_ms / self.total_calls

    @property
    def total_tokens(self) -> int:
        return self.total_tokens_input + self.total_tokens_output

    def to_dict(self) -> Dict:
        return {
            **asdict(self),
            "success_rate": round(self.success_rate, 3),
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "total_tokens": self.total_tokens,
        }


class PerformanceMonitor:
    """
    性能监控器
    收集各 Agent 的调用统计、延迟、token 消耗
    支持内存统计和本地 JSON 持久化
    """

    def __init__(self, storage_path: str = "./storage/metrics"):
        self.storage_path = storage_path
        self._metrics: Dict[str, AgentMetrics] = {}
        self._call_timers: Dict[str, float] = {}  # 正在进行的调用计时
        self._hourly_stats: Dict[str, List[Dict]] = defaultdict(list)
        self.logger = logging.getLogger(__name__)

        # 确保目录存在
        os.makedirs(storage_path, exist_ok=True)

        # 加载历史数据
        self._load_history()

    def start_call(self, agent_name: str, call_id: str = "") -> str:
        """
        开始记录一次调用
        返回 call_id 用于 end_call 时配对
        """
        call_key = f"{agent_name}_{call_id or str(time.time())}"
        self._call_timers[call_key] = time.time()
        return call_key

    def end_call(self, call_key: str, agent_name: str, success: bool = True,
                 tokens_input: int = 0, tokens_output: int = 0,
                 error: str = ""):
        """
        结束记录一次调用
        """
        start_time = self._call_timers.pop(call_key, None)
        latency_ms = (time.time() - start_time) * 1000 if start_time else 0

        # 获取或创建指标
        metrics = self._get_or_create_metrics(agent_name)

        metrics.total_calls += 1
        if success:
            metrics.success_calls += 1
        else:
            metrics.failed_calls += 1
            if error:
                metrics.errors.append(f"{datetime.now().isoformat()[:19]}: {error}")
                metrics.errors = metrics.errors[-20:]  # 保留最近 20 条

        metrics.total_latency_ms += latency_ms
        metrics.total_tokens_input += tokens_input
        metrics.total_tokens_output += tokens_output
        metrics.last_called_at = datetime.now().isoformat()

        # 记录小时级统计
        hour_key = datetime.now().strftime("%Y-%m-%d-%H")
        self._hourly_stats[agent_name].append({
            "timestamp": datetime.now().isoformat(),
            "success": success,
            "latency_ms": round(latency_ms, 2),
            "tokens_input": tokens_input,
            "tokens_output": tokens_output,
        })
        # 只保留最近 100 条小时记录
        self._hourly_stats[agent_name] = self._hourly_stats[agent_name][-100:]

        self.logger.debug(
            f"[PerfMon] {agent_name}: latency={latency_ms:.0f}ms, "
            f"tokens={tokens_input}+{tokens_output}, success={success}"
        )

        # 若当前在追踪上下文中，附加一个 metric span
        try:
            from agent.observability import get_tracer
            tracer = get_tracer()
            trace_id = tracer.get_current_trace_id()
            if trace_id:
                span = tracer.start_span("perfmon.metric", attributes={
                    "agent": agent_name,
                    "latency_ms": round(latency_ms, 2),
                    "tokens_input": tokens_input,
                    "tokens_output": tokens_output,
                    "success": success,
                })
                if not success and error:
                    span.set_attribute("error", error)
                span.end()
        except Exception:
            pass

    def record_token_usage(self, agent_name: str, tokens_input: int, tokens_output: int):
        """单独记录 token 使用量（如果 end_call 时未提供）"""
        metrics = self._get_or_create_metrics(agent_name)
        metrics.total_tokens_input += tokens_input
        metrics.total_tokens_output += tokens_output

    def get_metrics(self, agent_name: str) -> Optional[AgentMetrics]:
        """获取指定 Agent 的指标"""
        return self._metrics.get(agent_name)

    def get_all_metrics(self) -> Dict[str, Dict]:
        """获取所有 Agent 的指标摘要"""
        return {name: m.to_dict() for name, m in self._metrics.items()}

    def get_summary(self) -> Dict:
        """获取整体摘要"""
        total_calls = sum(m.total_calls for m in self._metrics.values())
        total_success = sum(m.success_calls for m in self._metrics.values())
        total_latency = sum(m.total_latency_ms for m in self._metrics.values())
        total_tokens = sum(m.total_tokens for m in self._metrics.values())

        return {
            "total_calls": total_calls,
            "total_success": total_success,
            "total_failed": sum(m.failed_calls for m in self._metrics.values()),
            "overall_success_rate": round(total_success / total_calls, 3) if total_calls > 0 else 0,
            "avg_latency_ms": round(total_latency / total_calls, 2) if total_calls > 0 else 0,
            "total_tokens": total_tokens,
            "agents": {name: m.to_dict() for name, m in self._metrics.items()},
            "generated_at": datetime.now().isoformat(),
        }

    def get_hourly_report(self, agent_name: str = "", hours: int = 24) -> Dict:
        """
        获取小时级报告
        """
        result = {}
        agents = [agent_name] if agent_name else list(self._hourly_stats.keys())

        for agent in agents:
            records = self._hourly_stats.get(agent, [])
            if not records:
                continue

            # 按小时聚合
            hourly = defaultdict(lambda: {"calls": 0, "success": 0, "latency_sum": 0, "tokens_sum": 0})
            for r in records:
                hour = r["timestamp"][:13]  # "2024-01-01T10"
                hourly[hour]["calls"] += 1
                if r["success"]:
                    hourly[hour]["success"] += 1
                hourly[hour]["latency_sum"] += r["latency_ms"]
                hourly[hour]["tokens_sum"] += r["tokens_input"] + r["tokens_output"]

            result[agent] = {
                h: {
                    "calls": d["calls"],
                    "success_rate": round(d["success"] / d["calls"], 3) if d["calls"] > 0 else 0,
                    "avg_latency_ms": round(d["latency_sum"] / d["calls"], 2) if d["calls"] > 0 else 0,
                    "total_tokens": d["tokens_sum"],
                }
                for h, d in sorted(hourly.items())
            }

        return result

    def save(self):
        """持久化到本地 JSON"""
        try:
            filepath = os.path.join(self.storage_path, "performance.json")
            import json
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(self.get_summary(), f, ensure_ascii=False, indent=2)
            self.logger.info("[PerfMon] 性能数据已保存")
        except Exception as e:
            self.logger.error(f"[PerfMon] 保存失败: {e}")

    def _get_or_create_metrics(self, agent_name: str) -> AgentMetrics:
        if agent_name not in self._metrics:
            self._metrics[agent_name] = AgentMetrics(agent_name=agent_name)
        return self._metrics[agent_name]

    def _load_history(self):
        """加载历史性能数据"""
        try:
            filepath = os.path.join(self.storage_path, "performance.json")
            if os.path.exists(filepath):
                import json
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                for name, m in data.get("agents", {}).items():
                    self._metrics[name] = AgentMetrics(
                        agent_name=name,
                        total_calls=m.get("total_calls", 0),
                        success_calls=m.get("success_calls", 0),
                        failed_calls=m.get("failed_calls", 0),
                        total_latency_ms=m.get("total_latency_ms", 0),
                        total_tokens_input=m.get("total_tokens_input", 0),
                        total_tokens_output=m.get("total_tokens_output", 0),
                    )
                self.logger.info(f"[PerfMon] 加载了 {len(self._metrics)} 个 Agent 的历史数据")
        except Exception as e:
            self.logger.debug(f"[PerfMon] 加载历史数据失败: {e}")

    def reset(self, agent_name: str = ""):
        """重置统计"""
        if agent_name:
            self._metrics.pop(agent_name, None)
            self._hourly_stats.pop(agent_name, None)
            self.logger.info(f"[PerfMon] 已重置 {agent_name} 的统计")
        else:
            self._metrics.clear()
            self._hourly_stats.clear()
            self.logger.info("[PerfMon] 已重置所有统计")
