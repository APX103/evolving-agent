"""
Companion Agent - 陪伴者：日常对话、情感交流
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict

from agent.multi_agent.base import BaseAgent, AgentContext, AgentResponse, IntentClassification

logger = logging.getLogger(__name__)


class CompanionAgent(BaseAgent):
    """陪伴 Agent：温暖贴心的日常对话伙伴"""

    name = "companion"
    description = "温暖陪伴、日常对话、情感支持"
    system_prompt_template = """你是一个温暖贴心的 AI 伙伴。你的目标是建立长期关系，让用户感到被理解和陪伴。

核心特质：
- 真诚共情：理解用户的情绪和感受
- 自然对话：像朋友一样聊天，不过度礼貌
- 记住细节：自然引用用户之前说过的话
- 适度幽默：在合适的时候轻松一下
- 尊重边界：不越界、不评判

记住：你是用户的伙伴，不是客服。"""
    temperature = 0.8
    max_tokens = 2048

    async def process(self, user_input: str, context: AgentContext) -> AgentResponse:
        system_prompt = self.build_system_prompt(context)

        # 注入情绪感知指令
        emotion_instruction = self._get_emotion_instruction(context)
        if emotion_instruction:
            system_prompt += f"\n\n【情绪适配】\n{emotion_instruction}"

        # 注入人格参数
        behavior = self._get_behavior_instructions()
        if behavior:
            system_prompt += f"\n\n【风格指令】\n{behavior}"

        messages = context.to_messages(system_prompt)
        messages.append({"role": "user", "content": user_input})

        # 动态选择模型层级：问候/短句用 lightweight，深层对话用 standard
        self._select_tier(user_input)

        try:
            response_text = await self._call_llm(messages)
            return AgentResponse(
                content=response_text,
                agent_name=self.name,
                metadata={"temperature": self.temperature},
            )
        except Exception as e:
            logger.error(f"[Companion] 处理失败: {e}")
            return AgentResponse(
                content="唔，我刚才走神了，能再说一遍吗？",
                agent_name=self.name,
                metadata={"error": str(e)},
            )

    def _select_tier(self, user_input: str) -> None:
        """根据输入内容动态选择模型层级"""
        text = user_input.strip()
        # 问候/短句 -> lightweight
        simple_patterns = [
            r"^(hi|hello|hey|你好|您好|哈喽|嗨|在吗|在么|早上好|下午好|晚上好|再见|拜拜|拜|好的|知道了|明白|嗯|哦)",
        ]
        if len(text) < 30:
            for pat in simple_patterns:
                if re.match(pat, text, re.IGNORECASE):
                    self.model_tier = "lightweight"
                    return
        # 深层对话/长文本 -> standard
        if len(text) > 100 or re.search(r"(为什么|怎么|感受|想法|建议|意义)", text):
            self.model_tier = "standard"
            return
        # 默认保持继承值或 lightweight
        if not self.model_tier:
            self.model_tier = "lightweight"

    def can_handle(self, intent: IntentClassification) -> float:
        if intent.primary_intent in ("chat", "emotional"):
            return 0.9
        if intent.primary_intent in ("write", "plan"):
            return 0.1
        return 0.0

    def _get_emotion_instruction(self, context: AgentContext) -> str:
        """从 context 中提取情绪指令"""
        meta = context.metadata
        emotion = meta.get("emotion", {})
        if emotion:
            label = emotion.get("label", "")
            intensity = emotion.get("intensity", 0)
            if label and intensity > 0.4:
                instructions: Dict[str, str] = {
                    "疲惫": "用户看起来很累，回应要简短温柔，不要追问太多。",
                    "焦虑": "用户有些焦虑，回应要安抚、给予确定性，不要制造紧迫感。",
                    "兴奋": "用户很兴奋，回应要积极、跟上情绪，可以一起开心。",
                    "沮丧": "用户情绪低落，回应要温暖支持，承认感受，给予鼓励。",
                    "愤怒": "用户在生气，回应要冷静、不辩解、先倾听。",
                }
                return instructions.get(label, f"用户情绪: {label}，请适当适配回应风格。")
        return ""

    def _get_behavior_instructions(self) -> str:
        """获取人格行为指令"""
        try:
            if hasattr(self.memory, "personality") and self.memory.personality:
                p = self.memory.personality
                if hasattr(p, "get_behavior_instructions"):
                    return p.get_behavior_instructions()
        except Exception:
            pass
        return ""
