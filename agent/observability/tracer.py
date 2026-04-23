"""
分布式追踪核心抽象
支持异步上下文传播（contextvars），最小化性能开销
"""
import contextvars
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Protocol

logger = logging.getLogger(__name__)

# ── 异步上下文变量 ──
_current_trace_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("trace_id", default=None)
_current_span_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("span_id", default=None)


class SpanExporter(Protocol):
    """后端导出接口"""

    def export_span(self, span_data: Dict[str, Any]) -> None:
        ...


class TraceSpan:
    """单个追踪 Span"""

    def __init__(
        self,
        name: str,
        trace_id: str,
        span_id: Optional[str] = None,
        parent_id: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
        exporter: Optional[SpanExporter] = None,
    ):
        self.name = name
        self.trace_id = trace_id
        self.span_id = span_id or self._gen_id()
        self.parent_id = parent_id
        self.attributes: Dict[str, Any] = attributes or {}
        self.status = "ok"
        self.start_time = time.time()
        self.end_time: Optional[float] = None
        self._exporter = exporter
        self._ended = False

    @staticmethod
    def _gen_id() -> str:
        return uuid.uuid4().hex[:16]

    def set_attribute(self, key: str, value: Any) -> None:
        """设置属性（值需可 JSON 序列化）"""
        try:
            json.dumps(value)
            self.attributes[key] = value
        except (TypeError, ValueError):
            self.attributes[key] = str(value)

    def record_exception(self, exc: BaseException) -> None:
        """记录异常"""
        self.status = "error"
        self.set_attribute("error.type", type(exc).__name__)
        self.set_attribute("error.message", str(exc))

    def end(self) -> None:
        """结束 Span 并导出"""
        if self._ended:
            return
        self._ended = True
        self.end_time = time.time()
        if self._exporter:
            try:
                self._exporter.export_span(self.to_dict())
            except Exception:
                pass  # 导出失败不应影响主流程

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_id": self.parent_id,
            "name": self.name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": round((self.end_time or time.time()) - self.start_time, 4) * 1000,
            "attributes": self.attributes,
            "status": self.status,
        }

    def __enter__(self):
        """同步上下文管理器"""
        _current_trace_id.set(self.trace_id)
        _current_span_id.set(self.span_id)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_val:
            self.record_exception(exc_val)
        self.end()
        return False

    async def __aenter__(self):
        _current_trace_id.set(self.trace_id)
        _current_span_id.set(self.span_id)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_val:
            self.record_exception(exc_val)
        self.end()
        return False


class Tracer:
    """Tracer：创建 Span 并管理上下文"""

    def __init__(self, exporter: Optional[SpanExporter] = None):
        self._exporter = exporter

    def start_span(
        self,
        name: str,
        attributes: Optional[Dict[str, Any]] = None,
        parent: Optional[TraceSpan] = None,
        trace_id: Optional[str] = None,
    ) -> TraceSpan:
        """
        创建新 Span。若未指定 parent/trace_id，自动从 contextvars 获取当前上下文。
        """
        effective_trace_id = trace_id or (parent.trace_id if parent else _current_trace_id.get()) or self._gen_trace_id()
        effective_parent_id = parent.span_id if parent else _current_span_id.get()

        span = TraceSpan(
            name=name,
            trace_id=effective_trace_id,
            parent_id=effective_parent_id,
            attributes=attributes,
            exporter=self._exporter,
        )
        # 将当前 span 设为活跃上下文
        _current_trace_id.set(span.trace_id)
        _current_span_id.set(span.span_id)
        return span

    def get_current_trace_id(self) -> Optional[str]:
        return _current_trace_id.get()

    def get_current_span_id(self) -> Optional[str]:
        return _current_span_id.get()

    @staticmethod
    def _gen_trace_id() -> str:
        return uuid.uuid4().hex[:16]


class MultiExporter:
    """组合多个后端导出器"""

    def __init__(self, exporters: List[SpanExporter]):
        self.exporters = exporters

    def export_span(self, span_data: Dict[str, Any]) -> None:
        for exp in self.exporters:
            try:
                exp.export_span(span_data)
            except Exception:
                pass


class NoOpExporter:
    """空导出器（用于禁用追踪时）"""

    def export_span(self, span_data: Dict[str, Any]) -> None:
        pass


# ── 全局 Tracer 单例（延迟初始化） ──
_global_tracer: Optional[Tracer] = None


def get_tracer() -> Tracer:
    """获取全局 Tracer（首次调用时自动初始化）"""
    global _global_tracer
    if _global_tracer is None:
        _global_tracer = _create_default_tracer()
    return _global_tracer


def set_tracer(tracer: Tracer) -> None:
    """设置全局 Tracer（用于测试或自定义）"""
    global _global_tracer
    _global_tracer = tracer


def _create_default_tracer() -> Tracer:
    """创建默认 Tracer：JSONL 后端 + 可选 Langfuse"""
    from agent.observability.jsonl_backend import JsonlBackend

    exporters: List[SpanExporter] = [JsonlBackend()]

    # 可选 Langfuse（懒加载，需要环境变量）
    if os.environ.get("LANGFUSE_PUBLIC_KEY"):
        try:
            from agent.observability.langfuse_backend import LangfuseBackend
            exporters.append(LangfuseBackend())
        except Exception as e:
            logger.warning(f"[Tracer] Langfuse 初始化失败: {e}")

    return Tracer(exporter=MultiExporter(exporters))
