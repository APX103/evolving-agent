"""
Google A2A (Agent-to-Agent) Protocol Pydantic Models
Reference: https://google.github.io/A2A/
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field


class TaskState(str, Enum):
    SUBMITTED = "submitted"
    WORKING = "working"
    INPUT_REQUIRED = "input-required"
    COMPLETED = "completed"
    CANCELED = "canceled"
    FAILED = "failed"
    UNKNOWN = "unknown"


class TextPart(BaseModel):
    type: str = "text"
    text: str


class FilePart(BaseModel):
    type: str = "file"
    file: Dict[str, Any] = Field(default_factory=dict)


class DataPart(BaseModel):
    type: str = "data"
    data: Dict[str, Any] = Field(default_factory=dict)


Part = Union[TextPart, FilePart, DataPart]


class Message(BaseModel):
    role: str  # "user" | "agent"
    parts: List[Part] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class Artifact(BaseModel):
    name: Optional[str] = None
    parts: List[Part] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    index: int = 0


class Task(BaseModel):
    id: str
    sessionId: Optional[str] = None
    state: TaskState = TaskState.SUBMITTED
    messages: List[Message] = Field(default_factory=list)
    artifacts: List[Artifact] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    status: Optional[Dict[str, Any]] = None


class TaskSendParams(BaseModel):
    id: str
    sessionId: Optional[str] = None
    message: Message
    acceptedOutputModes: Optional[List[str]] = None
    pushNotification: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AgentCapability(BaseModel):
    streaming: bool = False
    pushNotifications: bool = False
    stateTransitionHistory: bool = False


class AgentSkill(BaseModel):
    id: str
    name: str
    description: str
    tags: List[str] = Field(default_factory=list)
    examples: List[str] = Field(default_factory=list)
    inputModes: List[str] = Field(default_factory=list)
    outputModes: List[str] = Field(default_factory=list)


class AgentCard(BaseModel):
    name: str
    description: str
    url: str
    version: str = "1.0.0"
    capabilities: AgentCapability = Field(default_factory=AgentCapability)
    defaultInputModes: List[str] = Field(default_factory=lambda: ["text"])
    defaultOutputModes: List[str] = Field(default_factory=lambda: ["text"])
    skills: List[AgentSkill] = Field(default_factory=list)
    authentication: Optional[Dict[str, Any]] = None


class TaskStatusUpdateEvent(BaseModel):
    id: str
    status: Dict[str, Any]
    final: bool = False


class TaskArtifactUpdateEvent(BaseModel):
    id: str
    artifact: Artifact


class SendTaskRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: Optional[Union[str, int]] = None
    method: str = "tasks/send"
    params: TaskSendParams


class SendTaskStreamingRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: Optional[Union[str, int]] = None
    method: str = "tasks/sendSubscribe"
    params: TaskSendParams


class GetTaskRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: Optional[Union[str, int]] = None
    method: str = "tasks/get"
    params: Dict[str, Any]


class CancelTaskRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: Optional[Union[str, int]] = None
    method: str = "tasks/cancel"
    params: Dict[str, Any]


class JSONRPCResponse(BaseModel):
    jsonrpc: str = "2.0"
    id: Optional[Union[str, int]] = None
    result: Optional[Any] = None
    error: Optional[Dict[str, Any]] = None
