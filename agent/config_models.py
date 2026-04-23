"""
配置 Pydantic 模型
为 config.yaml 提供 Schema 校验
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class LLMConfig(BaseModel):
    """LLM 配置"""
    model_config = ConfigDict(extra="ignore")

    api_key: str = ""
    base_url: str = "https://api.moonshot.cn/v1"
    model: str = "kimi-latest"
    max_tokens: int = 4096
    temperature: float = 0.7
    embedding_model: str = "text-embedding"
    user_agent: str = ""


class AgentConfig(BaseModel):
    """Agent 配置"""
    model_config = ConfigDict(extra="ignore")

    name: str = "evolving-agent"
    description: str = ""
    system_prompt: str = ""
    temperature: float = 0.7
    max_tokens: int = 4096


class StorageConfig(BaseModel):
    """存储配置"""
    model_config = ConfigDict(extra="ignore")

    path: str = "storage"
    conversation_retention_days: int = 30


class AppConfig(BaseModel):
    """应用根配置"""
    model_config = ConfigDict(extra="ignore")

    kimi: LLMConfig = Field(default_factory=LLMConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
