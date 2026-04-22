"""
轻量级同步事件总线
用于解耦 Agent 核心与各子系统，便于后续扩展审计、指标、webhook 等
"""
from typing import Any, Callable, Dict, List


class EventBus:
    """简易同步事件总线"""

    def __init__(self):
        self._handlers: Dict[str, List[Callable[[Any], None]]] = {}

    def subscribe(self, event_type: str, handler: Callable[[Any], None]):
        """订阅事件"""
        self._handlers.setdefault(event_type, []).append(handler)

    def publish(self, event_type: str, payload: Any = None):
        """发布事件（同步顺序执行，异常隔离）"""
        for handler in self._handlers.get(event_type, []):
            try:
                handler(payload)
            except Exception:
                # 事件处理异常不应影响主流程
                pass

    def unsubscribe(self, event_type: str, handler: Callable[[Any], None]):
        """取消订阅"""
        if event_type in self._handlers:
            self._handlers[event_type] = [h for h in self._handlers[event_type] if h is not handler]


# 全局默认事件总线（单进程内共享）
default_bus = EventBus()
