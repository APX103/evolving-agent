"""
Configuration Pydantic models
Provide schema validation for config.yaml
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class LLMConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    api_key: str = ""
    base_url: str = "https://api.moonshot.cn/v1"
    model: str = "kimi-latest"
    max_tokens: int = 4096
    temperature: float = 0.7
    embedding_model: str = "text-embedding"
    user_agent: str = ""


class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = "evolving-agent"
    description: str = ""
    system_prompt: str = ""
    temperature: float = 0.7
    max_tokens: int = 4096


class StorageConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    path: str = "storage"
    conversation_retention_days: int = 30


class MCPServerConfigModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    transport: str = "stdio"
    command: Optional[str] = None
    args: List[str] = Field(default_factory=list)
    url: Optional[str] = None
    env: Optional[Dict[str, str]] = None


class MCPSecurityPolicyConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    low: str = "allow"
    medium: str = "allow"
    high: str = "require_approval"
    critical: str = "block"


class MCPSecurityConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = True
    policy: MCPSecurityPolicyConfig = Field(default_factory=MCPSecurityPolicyConfig)
    blocked_tools: List[str] = Field(default_factory=list)


class MCPConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = False
    servers: List[MCPServerConfigModel] = Field(default_factory=list)
    security: MCPSecurityConfig = Field(default_factory=MCPSecurityConfig)


class A2AConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = False
    external_agents: List[str] = Field(default_factory=list)
    discovery_ttl_seconds: int = 300


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    kimi: LLMConfig = Field(default_factory=LLMConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    a2a: A2AConfig = Field(default_factory=A2AConfig)
