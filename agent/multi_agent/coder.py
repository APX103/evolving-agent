"""
Coder Agent - 程序员：代码编写、调试、文件操作
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from agent.multi_agent.base import BaseAgent, AgentContext, AgentResponse, IntentClassification

logger = logging.getLogger(__name__)


class CoderAgent(BaseAgent):
    """编程 Agent：代码生成、调试、技术实现"""

    name = "coder"
    description = "代码编写、调试、文件操作、技术实现"
    model_tier = "heavy"
    system_prompt_template = """你是一个专业的编程助手。擅长 Python、JavaScript、TypeScript、Rust 等语言。

核心能力：
- 编写清晰、可运行、有注释的代码
- 调试排错：分析错误信息，给出修复方案
- 代码审查：指出潜在问题和优化点
- 技术选型：根据场景推荐合适的技术方案

原则：
- 先理解需求，再写代码
- 提供完整的可运行示例
- 解释关键逻辑和设计决策
- 如果代码有安全风险，明确标注
- 使用最新稳定版的语法和最佳实践"""
    temperature = 0.2
    max_tokens = 4096

    async def process(self, user_input: str, context: AgentContext) -> AgentResponse:
        system_prompt = self.build_system_prompt(context)

        # 检查是否需要代码执行
        needs_execution = self._detect_code_execution(user_input)
        if needs_execution:
            system_prompt += "\n\n【注意】用户需要运行代码，请提供可执行的完整代码块。"

        messages = context.to_messages(system_prompt)
        messages.append({"role": "user", "content": user_input})

        try:
            response_text = await self._call_llm(messages)
            return AgentResponse(
                content=response_text,
                agent_name=self.name,
                response_type="markdown",
                metadata={"temperature": self.temperature, "needs_execution": needs_execution},
            )
        except Exception as e:
            logger.error(f"[Coder] 处理失败: {e}")
            return AgentResponse(
                content=f"代码处理时出错: {e}",
                agent_name=self.name,
                metadata={"error": str(e)},
            )

    def can_handle(self, intent: IntentClassification) -> float:
        if intent.primary_intent in ("code", "debug"):
            return 0.95
        if intent.primary_intent == "tool":
            return 0.3
        return 0.0

    def _detect_code_execution(self, user_input: str) -> bool:
        """检测用户是否需要执行代码"""
        keywords = ["运行", "执行", "测试", "看看结果", "输出什么", "试试"]
        return any(k in user_input for k in keywords)
