"""
Kimi API 客户端封装（兼容层）
原实现已迁移至 agent.llm.kimi_client.KimiLLMClient
此文件保留以兼容旧 import，内部转发到新实现
"""
import warnings
from typing import List, Dict, Optional

from agent.llm.kimi_client import KimiLLMClient

warnings.warn(
    "agent.kimi_client 已弃用，请改用 agent.llm.KimiLLMClient",
    DeprecationWarning,
    stacklevel=2
)


class KimiClient:
    """兼容旧接口的包装器"""

    def __init__(self, config_path: str = "config.yaml"):
        self._client = KimiLLMClient()
        # 透传常用属性
        self.model = self._client.model
        self.max_tokens = self._client.max_tokens
        self.temperature = self._client.temperature

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stream: bool = False
    ):
        return self._client.chat(messages, temperature, max_tokens, stream)

    def quick_chat(self, prompt: str, system: str = "") -> str:
        return self._client.quick_chat(prompt, system)
