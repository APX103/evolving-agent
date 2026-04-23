"""
Router Agent - 意图分类与 Agent 调度
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from agent.multi_agent.base import (
    BaseAgent,
    AgentContext,
    AgentResponse,
    IntentClassification,
    HandoffRequest,
    LayerType,
)
from agent.observability import get_tracer

logger = logging.getLogger(__name__)

INTENT_AGENT_MAP = {
    "chat": "companion",
    "emotional": "companion",
    "code": "coder",
    "debug": "coder",
    "research": "researcher",
    "write": "writer",
    "plan": "planner",
    "tool": "executor",
}


class RouterAgent(BaseAgent):
    """路由 Agent：分析用户意图，决定激活哪个 Specialist"""

    name = "router"
    description = "意图分类与 Agent 调度"
    system_prompt_template = """你是意图分类专家。分析用户输入，分类为以下意图之一：
- chat: 闲聊/日常对话
- emotional: 情感支持/倾诉
- code: 编程/代码问题
- debug: 调试/排错
- research: 信息检索/调研
- write: 写作/文案/报告
- plan: 复杂任务需要规划
- tool: 需要使用工具（计算/文件/Shell）

只输出 JSON 格式，不要其他内容。"""
    temperature = 0.3
    max_tokens = 512

    async def process(self, user_input: str, context: AgentContext) -> AgentResponse:
        """Router 不直接回复用户，只做分类"""
        intent = await self.classify(user_input, context)
        return AgentResponse(
            content=f"意图: {intent.primary_intent} -> {intent.target_agent}",
            agent_name=self.name,
            metadata={"intent": intent},
        )

    def can_handle(self, intent: IntentClassification) -> float:
        return 1.0  # Router 永远先处理

    async def classify(self, user_input: str, context: AgentContext) -> IntentClassification:
        """LLM 意图分类"""
        prompt = self._build_classify_prompt(user_input, context)

        try:
            intent = await self.llm.achat_structured(
                prompt,
                response_model=IntentClassification,
                system=self.system_prompt_template,
                temperature=0.3,
                max_tokens=256,
            )
            # 验证 target_agent 有效性
            if intent.target_agent not in INTENT_AGENT_MAP.values():
                intent.target_agent = INTENT_AGENT_MAP.get(intent.primary_intent, "companion")
            # 确保 confidence 在合法范围
            intent.confidence = min(1.0, max(0.0, intent.confidence))
            return intent
        except Exception as e:
            logger.warning(f"[Router] LLM 分类失败: {e}")
            return self._fallback_classify(user_input)

    def _build_classify_prompt(self, user_input: str, context: AgentContext) -> str:
        """构建分类 prompt"""
        prompt = f"""请分析以下用户输入，判断意图：

用户输入: {user_input}

请输出 JSON：
{{
  "primary_intent": "意图名称",
  "confidence": 0.0-1.0,
  "target_agent": "对应的 agent 名称(companion/coder/researcher/writer/planner/executor)",
  "parameters": {{}},
  "needs_planning": true/false
}}

意图说明：
- chat: 闲聊、打招呼、日常对话
- emotional: 情感倾诉、寻求安慰、分享心情
- code: 写代码、编程问题、技术实现
- debug: 调试、错误排查、修复 bug
- research: 调研、搜索信息、查找资料
- write: 写文章、报告、文案、总结
- plan: 复杂多步骤任务
- tool: 计算、文件操作、Shell 命令"""
        return prompt

    def _fallback_classify(self, user_input: str) -> IntentClassification:
        """关键词降级匹配"""
        text = user_input.lower()

        code_keywords = [
            "代码", "编程", "python", "javascript", "typescript", "bug", "调试", "debug",
            "函数", "class", "import", "error", "exception", "traceback", "写个", "实现",
        ]
        research_keywords = [
            "调研", "搜索", "查一下", "资料", "信息", "对比", "区别", "什么是",
            "怎么样", "推荐", "有哪些",
        ]
        emotional_keywords = [
            "难过", "伤心", "开心", "烦", "累", "孤独", "焦虑", "压力",
            "感情", "喜欢", "讨厌", "害怕",
        ]
        write_keywords = ["写", "报告", "文案", "总结", "邮件", "文档", "文章", "大纲"]
        plan_keywords = ["计划", "安排", "步骤", "流程", "先", "然后", "最后", "帮我做"]
        tool_keywords = ["/calc", "/read", "/write", "/sh", "计算", "读取文件", "执行"]

        scores: Dict[str, float] = {
            "code": sum(1 for k in code_keywords if k in text) * 0.3,
            "research": sum(1 for k in research_keywords if k in text) * 0.3,
            "emotional": sum(1 for k in emotional_keywords if k in text) * 0.4,
            "write": sum(1 for k in write_keywords if k in text) * 0.3,
            "plan": sum(1 for k in plan_keywords if k in text) * 0.2,
            "tool": sum(1 for k in tool_keywords if k in text) * 0.5,
        }

        best_intent = max(scores, key=scores.get)
        best_score = scores[best_intent]

        if best_score < 0.3:
            best_intent = "chat"
            best_score = 0.5

        return IntentClassification(
            primary_intent=best_intent,
            confidence=best_score,
            target_agent=INTENT_AGENT_MAP.get(best_intent, "companion"),
        )
