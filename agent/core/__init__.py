"""
Core 模块：核心引擎与基础设施
"""
from agent.core.config import Config
from agent.core.config_models import AppConfig, LLMConfig, AgentConfig
from agent.core.events import EventBus, default_bus
from agent.core.checkpoint import CheckpointManager, CheckpointInfo
from agent.core.utils import now_str, pretty_json

__all__ = [
    "Config",
    "AppConfig",
    "LLMConfig",
    "AgentConfig",
    "EventBus",
    "default_bus",
    "CheckpointManager",
    "CheckpointInfo",
    "now_str",
    "pretty_json",
    "EvolvingAgent",
]


def __getattr__(name: str):
    if name == "EvolvingAgent":
        from agent.core.agent import EvolvingAgent
        return EvolvingAgent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
