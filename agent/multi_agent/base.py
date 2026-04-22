"""
多 Agent 基础设施 - 基类与数据模型
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any, AsyncGenerator
import logging

logger = logging.getLogger(__name__)


class LayerType(str, Enum):
    SYSTEM = "system"
    ETERNAL = "eternal"
    SUMMARIES = "summaries"
    WORKING = "working"
    RECENT = "recent"
    RULES = "rules"


@dataclass
class IntentClassification:
    """意图分类结果"""
    primary_intent: str
    confidence: float
    target_agent: Optional[str]
    parameters: Dict[str, Any] = field(default_factory=dict)
    needs_planning: bool = False


@dataclass
class AgentResponse:
    """Agent 响应"""
    content: str
    agent_name: str
    response_type: str = "text"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentContext:
    """Agent 上下文 - 分层架构"""
    user_id: str
    source: str
    layers: Dict[LayerType, str] = field(default_factory=dict)
    short_term: List[Dict] = field(default_factory=list)
    working_memory: Dict = field(default_factory=dict)
    metadata: Dict = field(default_factory=dict)

    def to_messages(self, system_prompt: str) -> List[Dict[str, str]]:
        """
        构建消息列表，针对 RoPE Context Rot 和 Lost-in-the-Middle 优化：
        1. Eternal Memory 合并到 system prompt（确保核心画像获得最强注意力）
        2. Working Context 紧随 system prompt 后（当前任务需要最近位置）
        3. Rules 次之（行为策略）
        4. Summaries 最后（历史信息，可容忍衰减）
        5. short_term 放在最后（最近对话天然在最后，符合 U 形注意力优势）
        """
        # Layer 1: Eternal Memory 合并到 system prompt
        eternal = self.layers.get(LayerType.ETERNAL, "")
        if eternal:
            system_prompt = f"{system_prompt}\n\n【用户核心画像】\n{eternal}"

        messages = [{"role": "system", "content": system_prompt}]

        # 按重要性排序：WORKING > RULES > SUMMARIES
        for lt in [LayerType.WORKING, LayerType.RULES, LayerType.SUMMARIES]:
            content = self.layers.get(lt, "")
            if content:
                messages.append({"role": "system", "content": f"[{lt.value}]\n{content}"})

        messages.extend(self.short_term)
        return messages

    def get_layer(self, layer_type: LayerType) -> str:
        return self.layers.get(layer_type, "")


@dataclass
class HandoffRequest:
    from_agent: str
    to_agent: str
    user_input: str
    context_summary: str
    working_memory: Dict
    handoff_reason: str


@dataclass
class HandoffResult:
    from_agent: str
    response: str
    updated_working_memory: Dict
    learnings: List[Dict] = field(default_factory=list)


class BaseAgent(ABC):
    """Agent 抽象基类"""
    name: str = "base"
    description: str = "基础 Agent"
    system_prompt_template: str = ""
    temperature: float = 0.7
    max_tokens: int = 4096

    def __init__(self, agent_id: str, memory, llm_client, config: Optional[Dict] = None):
        self.agent_id = agent_id
        self.memory = memory
        self.llm = llm_client
        self.config = config or {}
        self.working_memory: Dict = {}
        self.logger = logging.getLogger(f"agent.{self.name}")

    @abstractmethod
    async def process(self, user_input: str, context: AgentContext) -> AgentResponse:
        """处理用户输入，返回响应"""
        pass

    @abstractmethod
    def can_handle(self, intent: IntentClassification) -> float:
        """返回置信度 0.0-1.0"""
        pass

    def build_system_prompt(self, context: AgentContext) -> str:
        parts = [self.system_prompt_template]
        eternal = context.get_layer(LayerType.ETERNAL)
        if eternal:
            parts.append(f"【用户核心画像】\n{eternal}")
        working = context.get_layer(LayerType.WORKING)
        if working:
            parts.append(f"【当前任务】\n{working}")
        return "\n\n".join(parts)

    async def _call_llm(self, messages: List[Dict], **kwargs) -> str:
        temperature = kwargs.get("temperature", self.temperature)
        max_tokens = kwargs.get("max_tokens", self.max_tokens)
        if hasattr(self.llm, "achat"):
            return await self.llm.achat(messages, temperature=temperature, max_tokens=max_tokens)
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.llm.chat(messages, temperature=temperature, max_tokens=max_tokens, stream=False)
        )

    async def _stream_llm(self, messages: List[Dict], **kwargs) -> AsyncGenerator[str, None]:
        temperature = kwargs.get("temperature", self.temperature)
        max_tokens = kwargs.get("max_tokens", self.max_tokens)
        if hasattr(self.llm, "astream_chat"):
            async for chunk in self.llm.astream_chat(messages, temperature=temperature, max_tokens=max_tokens):
                yield chunk
        elif hasattr(self.llm, "chat"):
            import asyncio
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self.llm.chat(messages, temperature=temperature, max_tokens=max_tokens, stream=True)
            )
            if hasattr(result, '__iter__'):
                for chunk in result:
                    yield chunk
            else:
                yield str(result)
        else:
            result = await self._call_llm(messages, **kwargs)
            yield result
