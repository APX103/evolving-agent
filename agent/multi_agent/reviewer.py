"""
Reviewer Agent - 审稿人：质量检查、反思、纠错
"""
import logging
from typing import Dict

from agent.multi_agent.base import BaseAgent, AgentContext, AgentResponse, IntentClassification

logger = logging.getLogger(__name__)


class ReviewerAgent(BaseAgent):
    """审稿 Agent：质量检查、反思、纠错"""

    name = "reviewer"
    description = "质量审核、反思、纠错"
    system_prompt_template = """你是一个严格的审稿人。你的职责是检查输出质量，找出问题和改进空间。

审核维度：
1. 准确性：事实是否正确，逻辑是否自洽
2. 完整性：是否遗漏了重要内容
3. 清晰度：表达是否清晰易懂
4. 安全性：是否有潜在风险或敏感信息
5. 实用性：是否真正解决了用户的问题

审核原则：
- 严格但建设性，指出问题同时给出改进建议
- 区分"必须修复"和"建议优化"
- 如果质量合格，明确通过"""
    temperature = 0.3
    max_tokens = 2048

    async def process(self, user_input: str, context: AgentContext) -> AgentResponse:
        """审核内容质量"""
        # 从 working_memory 获取待审核内容
        content_to_review = context.working_memory.get("draft_content") or context.working_memory.get("last_research") or user_input

        system_prompt = self.build_system_prompt(context)
        system_prompt += "\n\n【审核任务】\n请审核以下内容的质量，按维度给出评价。"

        messages = context.to_messages(system_prompt)
        messages.append({"role": "user", "content": f"请审核以下内容:\n\n{content_to_review}"})

        try:
            review_result = await self._call_llm(messages, temperature=0.3, max_tokens=1024)

            # 将审核结果存入 working_memory
            self.working_memory["last_review"] = review_result

            # 判断质量是否通过（简化：看是否有"通过"或"合格"字样）
            passed = any(k in review_result for k in ["通过", "合格", "质量良好", "approved"])

            return AgentResponse(
                content=review_result,
                agent_name=self.name,
                response_type="markdown",
                metadata={
                    "review_passed": passed,
                    "content_length": len(content_to_review)
                }
            )
        except Exception as e:
            logger.error(f"[Reviewer] 审核失败: {e}")
            return AgentResponse(
                content=f"审核过程出错: {e}",
                agent_name=self.name,
                metadata={"error": str(e)}
            )

    def can_handle(self, intent: IntentClassification) -> float:
        if intent.primary_intent == "review":
            return 0.95
        if intent.primary_intent in ("plan", "write"):
            return 0.2
        return 0.0

    async def review_plan_execution(self, plan_results: Dict) -> AgentResponse:
        """专门审核计划执行结果"""
        summary = plan_results.get("summary", "")
        success_count = plan_results.get("success_count", 0)
        total_count = plan_results.get("total_count", 0)

        review_prompt = f"""请审核以下计划执行结果：

执行摘要: {summary}
成功率: {success_count}/{total_count}

请评估：
1. 所有步骤是否按计划完成
2. 结果是否满足原始需求
3. 是否有遗漏或需要补充的"""

        messages = [{"role": "user", "content": review_prompt}]
        try:
            result = await self._call_llm(messages, temperature=0.3, max_tokens=512)
            return AgentResponse(
                content=result,
                agent_name=self.name,
                metadata={"review_type": "plan_execution"}
            )
        except Exception as e:
            return AgentResponse(
                content=f"审核失败: {e}",
                agent_name=self.name,
                metadata={"error": str(e)}
            )
