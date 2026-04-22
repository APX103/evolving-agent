"""
Researcher Agent - 研究员：信息检索、网页浏览、调研
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from agent.multi_agent.base import BaseAgent, AgentContext, AgentResponse, IntentClassification

logger = logging.getLogger(__name__)


class ResearcherAgent(BaseAgent):
    """研究 Agent：信息检索、资料收集、数据分析"""

    name = "researcher"
    description = "信息检索、网页浏览、调研分析"
    system_prompt_template = """你是一个高效的研究员。擅长信息检索、资料收集和数据分析。

工作流程：
1. 理解研究目标和范围
2. 制定检索策略
3. 收集和整理信息
4. 分析对比，提取洞察
5. 结构化输出研究结果

原则：
- 引用来源，标注数据时效性
- 多角度对比，不片面
- 区分事实和观点
- 信息不足时诚实说明"""
    temperature = 0.4
    max_tokens = 4096

    async def process(self, user_input: str, context: AgentContext) -> AgentResponse:
        system_prompt = self.build_system_prompt(context)

        # 注入已有研究结果（如果有）
        prior_research = context.working_memory.get("research_results", "")
        if prior_research:
            system_prompt += f"\n\n【已有研究资料】\n{prior_research}"

        messages = context.to_messages(system_prompt)
        messages.append({"role": "user", "content": user_input})

        try:
            response_text = await self._call_llm(messages)

            # 将研究结果存入 working_memory
            self.working_memory["last_research"] = response_text[:2000]

            return AgentResponse(
                content=response_text,
                agent_name=self.name,
                response_type="markdown",
                metadata={
                    "temperature": self.temperature,
                    "has_prior_research": bool(prior_research),
                },
            )
        except Exception as e:
            logger.error(f"[Researcher] 处理失败: {e}")
            return AgentResponse(
                content=f"调研时出错: {e}",
                agent_name=self.name,
                metadata={"error": str(e)},
            )

    def can_handle(self, intent: IntentClassification) -> float:
        if intent.primary_intent == "research":
            return 0.95
        if intent.primary_intent == "plan":
            return 0.2
        return 0.0
