"""
Planner Agent - 规划师：复杂任务分解为可执行计划
集成现有的 PlanningFlow (planner.py + executor.py)
"""
import logging
from typing import Dict, List, Optional, Any

from pydantic import BaseModel, Field

from agent.multi_agent.base import BaseAgent, AgentContext, AgentResponse, IntentClassification
from agent.planning.plan import Plan, Step, StepStatus

logger = logging.getLogger(__name__)

PLANNER_SYSTEM_PROMPT = """你是任务规划专家。将用户请求分解为清晰的执行步骤。

可用工具:
- llm: 大语言模型推理、分析、写作
- mcp:fetch: 获取网页内容
- mcp:filesystem: 读写本地文件
- sandbox: 执行 Python 代码
- skill:calc: 数学计算

规划原则:
1. 每个步骤只做一件事
2. 步骤间有明确依赖关系时标注 depends_on
3. 能用代码/工具完成的，不要交给 llm
4. 最后一步总是"总结"，汇总前面结果

只输出 JSON，不要解释。"""


class PlannerStep(BaseModel):
    """规划步骤 Schema"""
    id: int
    description: str
    tool: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    depends_on: List[int] = Field(default_factory=list)


class PlannerDecision(BaseModel):
    """规划决策 Schema"""
    needs_planning: bool
    steps: List[PlannerStep]
    reason: str = ""


class PlannerAgent(BaseAgent):
    """规划 Agent：将复杂任务分解为可执行的计划"""

    name = "planner"
    description = "任务规划与分解"
    system_prompt_template = """你是一个任务规划专家。你擅长将复杂的用户需求分解为清晰、可执行的步骤计划。

工作流程：
1. 分析用户需求的复杂度和范围
2. 判断是否需要多步骤规划（简单问题直接回答）
3. 如需规划，分解为最小可执行单元
4. 标注步骤间的依赖关系
5. 为每个步骤选择最合适的工具

输出格式：严格的 JSON，包含 steps 数组。"""
    temperature = 0.3
    max_tokens = 2048

    async def process(self, user_input: str, context: AgentContext) -> AgentResponse:
        """分解任务为 Plan，存入 working_memory"""
        plan = await self._decompose_task(user_input, context)

        if plan is None:
            # 不需要规划，直接回答
            return AgentResponse(
                content="这个任务比较简单，我直接帮你处理。",
                agent_name=self.name,
                metadata={"needs_planning": False}
            )

        # 保存计划到 working_memory
        self.working_memory["current_plan"] = plan.to_dict()

        # 生成计划摘要
        plan_summary = self._format_plan_summary(plan)

        return AgentResponse(
            content=plan_summary,
            agent_name=self.name,
            response_type="markdown",
            metadata={
                "needs_planning": True,
                "plan": plan.to_dict(),
                "step_count": len(plan.steps)
            }
        )

    def can_handle(self, intent: IntentClassification) -> float:
        if intent.primary_intent == "plan":
            return 0.95
        if intent.needs_planning:
            return 0.8
        if intent.primary_intent in ("research", "write"):
            return 0.3
        return 0.1

    async def _decompose_task(self, task: str, context: AgentContext) -> Optional[Plan]:
        """使用 LLM 分解任务为 Plan"""
        tools_text = """- llm: 大语言模型推理、分析、写作
- mcp:fetch: 获取网页内容
- mcp:filesystem: 文件操作
- sandbox: Python 代码执行
- skill:calc: 数学计算"""

        prompt = f"""请将以下任务分解为执行步骤：

任务: {task}

可用工具:
{tools_text}

输出格式（JSON）：
{{
  "needs_planning": true/false,
  "steps": [
    {{
      "id": 1,
      "description": "步骤描述",
      "tool": "工具名",
      "arguments": {{"参数": "值"}},
      "depends_on": []
    }}
  ],
  "reason": "规划理由"
}}

注意:
- id 从 1 开始递增
- depends_on 填依赖的 id 列表
- tool 必须是可用工具之一
- 如果任务很简单不需要多步规划，设置 needs_planning: false"""

        try:
            decision = await self.llm.achat_structured(
                prompt,
                response_model=PlannerDecision,
                system=PLANNER_SYSTEM_PROMPT,
                temperature=0.3,
                max_tokens=1024,
            )

            if not decision.needs_planning:
                return None

            steps = []
            for s in decision.steps:
                steps.append(Step(
                    id=s.id,
                    description=s.description,
                    tool=s.tool,
                    arguments=s.arguments,
                    depends_on=s.depends_on,
                    status=StepStatus.PENDING,
                ))

            return Plan(task=task, steps=steps)

        except Exception as e:
            logger.warning(f"[PlannerAgent] 规划失败: {e}")
            return None

    def _format_plan_summary(self, plan: Plan) -> str:
        """格式化计划为可读文本"""
        lines = [f"📋 任务计划: {plan.task}", ""]
        for step in plan.steps:
            status_emoji = "⬜"
            deps = f" (依赖: {step.depends_on})" if step.depends_on else ""
            lines.append(f"  {status_emoji} 步骤 {step.id}: {step.description} [{step.tool}]{deps}")
        lines.append("")
        lines.append("我将按顺序执行这些步骤。")
        return "\n".join(lines)

    def should_plan(self, user_input: str) -> bool:
        """快速判断是否需要规划"""
        text = user_input.strip()
        if text.startswith("/plan"):
            return True
        planning_signals = ["然后", "接着", "第一步", "先", "再", "最后", "帮我", "给我", "整理", "总结"]
        signal_count = sum(1 for s in planning_signals if s in text)
        return signal_count >= 2 and len(text) > 20
