"""
Langfuse 集成（可选）
仅在 LANGFUSE_PUBLIC_KEY 环境变量设置时启用
"""
import logging
import os
from typing import Any, Dict

logger = logging.getLogger(__name__)


class LangfuseBackend:
    """
    Langfuse 追踪后端（懒加载）
    需要: pip install langfuse
    环境变量: LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST
    """

    def __init__(self):
        self._langfuse = None
        self._init()

    def _init(self):
        try:
            from langfuse import Langfuse
            self._langfuse = Langfuse(
                public_key=os.environ.get("LANGFUSE_PUBLIC_KEY"),
                secret_key=os.environ.get("LANGFUSE_SECRET_KEY"),
                host=os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com"),
            )
            logger.info("[LangfuseBackend] 已连接 Langfuse")
        except ImportError:
            logger.warning("[LangfuseBackend] langfuse 包未安装，跳过")
        except Exception as e:
            logger.warning(f"[LangfuseBackend] 初始化失败: {e}")

    def export_span(self, span_data: Dict[str, Any]) -> None:
        if self._langfuse is None:
            return

        try:
            trace_id = span_data.get("trace_id")
            span_id = span_data.get("span_id")
            parent_id = span_data.get("parent_id")
            name = span_data.get("name", "span")
            start_time = span_data.get("start_time")
            end_time = span_data.get("end_time")
            attributes = span_data.get("attributes", {})
            status = span_data.get("status", "ok")

            # Langfuse trace（root span 时创建/获取）
            if not parent_id:
                self._langfuse.trace(
                    id=trace_id,
                    name=name,
                    metadata=attributes,
                )

            # Langfuse span
            self._langfuse.span(
                id=span_id,
                trace_id=trace_id,
                parent_observation_id=parent_id,
                name=name,
                start_time=start_time,
                end_time=end_time,
                metadata=attributes,
                level="ERROR" if status == "error" else "DEFAULT",
            )
        except Exception as e:
            logger.debug(f"[LangfuseBackend] 导出失败: {e}")
