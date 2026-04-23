"""
A2A (Agent-to-Agent) Protocol support for Evolving Agent.
"""
from agent.a2a.models import (
    AgentCard,
    AgentCapability,
    AgentSkill,
    Artifact,
    Message,
    Task,
    TaskSendParams,
    TaskState,
    TextPart,
    FilePart,
    DataPart,
)
from agent.a2a.discovery import AgentDiscovery
from agent.a2a.client import A2AClient
from agent.a2a.server import create_a2a_router

__all__ = [
    "AgentCard",
    "AgentCapability",
    "AgentSkill",
    "Artifact",
    "Message",
    "Task",
    "TaskSendParams",
    "TaskState",
    "TextPart",
    "FilePart",
    "DataPart",
    "AgentDiscovery",
    "A2AClient",
    "create_a2a_router",
]
