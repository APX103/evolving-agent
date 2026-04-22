"""
多 Agent 协作系统 - 基础设施模块
"""
from agent.multi_agent.base import (
    BaseAgent,
    AgentContext,
    AgentResponse,
    IntentClassification,
    HandoffRequest,
    HandoffResult,
    LayerType,
)
from agent.multi_agent.context_manager import ContextManager
from agent.multi_agent.registry import AgentRegistry
from agent.multi_agent.handoff import HandoffProtocol
from agent.multi_agent.token_counter import TokenCounter

__all__ = [
    "BaseAgent",
    "AgentContext",
    "AgentResponse",
    "IntentClassification",
    "HandoffRequest",
    "HandoffResult",
    "LayerType",
    "ContextManager",
    "AgentRegistry",
    "HandoffProtocol",
    "TokenCounter",
]
