"""
Executor Agent - 执行员：按计划调用工具完成动作
支持 Handoff 到 Specialist 执行具体步骤
"""
import asyncio
import logging
import re
from typing import Any, Dict, List, Optional

from agent.multi_agent.base import BaseAgent, AgentContext, AgentResponse, IntentClassification
from agent.multi_agent.handoff import HandoffRequest, HandoffProtocol
from agent.plan import Plan, Step, StepStatus

logger = logging.getLogger(__name__)


class ExecutorAgent(BaseAgent):
    """执行 Agent：按计划调用工具，支持 Handoff 到 Specialist"""

    name = "executor"
    description = "计划执行与工具调用"
    system_prompt_template = """你是一个高效的执行员。你的职责是严格按照计划执行每一步，确保任务高质量完成。

执行原则：
1. 严格按照计划步骤执行，不跳过、不遗漏
2. 每步执行后记录结果
3. 遇到失败时尝试重试（最多 2 次）
4. 所有步骤完成后生成总结
5. 不确定时寻求澄清，不猜测"""
    temperature = 0.2
    max_tokens = 4096

    def __init__(self, agent_id: str, memory, llm_client, config: Dict = None,
                 handoff_protocol: Optional[HandoffProtocol] = None):
        super().__init__(agent_id, memory, llm_client, config)
        self.handoff = handoff_protocol
        self.max_retries = 2

    async def process(self, user_input: str, context: AgentContext) -> AgentResponse:
        """执行当前计划"""
        # 从 working_memory 获取计划
        plan_dict = context.working_memory.get("current_plan")
        if not plan_dict:
            # 尝试从自己的 working_memory 获取
            plan_dict = self.working_memory.get("current_plan")

        if not plan_dict:
            return AgentResponse(
                content="没有找到可执行的计划。请先让 Planner 生成计划。",
                agent_name=self.name,
                metadata={"error": "no_plan"}
            )

        plan = self._dict_to_plan(plan_dict)
        executed_plan = await self._execute_plan(plan, context)

        # 更新 working_memory
        self.working_memory["current_plan"] = executed_plan.to_dict()
        self.working_memory["execution_results"] = {
            s.id: {"result": s.result, "status": s.status.value, "error": s.error}
            for s in executed_plan.steps
        }

        summary = self._generate_summary(executed_plan)

        return AgentResponse(
            content=summary,
            agent_name=self.name,
            response_type="markdown",
            metadata={
                "plan_status": executed_plan.status.value,
                "success_count": sum(1 for s in executed_plan.steps if s.status == StepStatus.SUCCESS),
                "total_count": len(executed_plan.steps)
            }
        )

    def can_handle(self, intent: IntentClassification) -> float:
        if intent.primary_intent in ("plan", "execute"):
            return 0.9
        if intent.primary_intent == "tool":
            return 0.7
        return 0.0

    async def _execute_plan(self, plan: Plan, context: AgentContext) -> Plan:
        """执行完整计划"""
        logger.info(f"[Executor] 开始执行计划: {plan.task} ({len(plan.steps)} 步)")
        plan.status = StepStatus.RUNNING

        while not plan.is_complete():
            ready_steps = plan.get_ready_steps()
            if not ready_steps:
                unresolved = [s for s in plan.steps if s.status == StepStatus.PENDING]
                if unresolved:
                    logger.error(f"[Executor] 死锁: {len(unresolved)} 步无法执行")
                    for s in unresolved:
                        s.status = StepStatus.FAILED
                        s.error = "依赖无法满足"
                break

            if len(ready_steps) == 1:
                await self._execute_step(ready_steps[0], context)
            else:
                logger.info(f"[Executor] 并行执行 {len(ready_steps)} 步")
                await asyncio.gather(*[
                    self._execute_step(s, context) for s in ready_steps
                ])

        plan.status = StepStatus.SUCCESS if plan.is_success() else StepStatus.FAILED
        plan.summary = self._generate_summary(plan)
        logger.info(f"[Executor] 计划执行完成: {plan.status.value}")
        return plan

    async def _execute_step(self, step: Step, context: AgentContext):
        """执行单个步骤"""
        logger.info(f"[Executor] Step {step.id}: {step.description} [{step.tool}]")
        step.status = StepStatus.RUNNING

        try:
            result = await self._invoke_tool_for_step(step, context)
            step.result = str(result) if result is not None else ""
            step.status = StepStatus.SUCCESS
            logger.info(f"[Executor] Step {step.id} 成功")
        except Exception as e:
            step.error = str(e)
            step.retry_count += 1

            if step.retry_count <= self.max_retries:
                step.status = StepStatus.RETRYING
                logger.warning(f"[Executor] Step {step.id} 重试 {step.retry_count}/{self.max_retries}")
                await asyncio.sleep(1)
                try:
                    result = await self._invoke_tool_for_step(step, context)
                    step.result = str(result) if result is not None else ""
                    step.status = StepStatus.SUCCESS
                    step.error = None
                    logger.info(f"[Executor] Step {step.id} 重试成功")
                except Exception as e2:
                    step.error = f"{e} -> 重试失败: {e2}"
                    step.status = StepStatus.FAILED
                    logger.error(f"[Executor] Step {step.id} 最终失败")
            else:
                step.status = StepStatus.FAILED
                logger.error(f"[Executor] Step {step.id} 失败（已达最大重试）")

    async def _invoke_tool_for_step(self, step: Step, context: AgentContext) -> Any:
        """调用步骤对应的工具"""
        tool = step.tool
        arguments = self._resolve_arguments(step.arguments, context)

        # LLM 推理
        if tool == "llm":
            prompt = arguments.get("prompt", step.description)
            system = arguments.get("system", "你是一个有帮助的助手。")
            messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
            return await self._call_llm(messages)

        # Handoff 到 Coder (code/debug 相关)
        if tool in ("sandbox", "code"):
            if self.handoff:
                req = HandoffRequest(
                    from_agent=self.name,
                    to_agent="coder",
                    user_input=arguments.get("code", arguments.get("input", step.description)),
                    context_summary=f"执行计划步骤 {step.id}: {step.description}",
                    working_memory={"code_task": step.description, "arguments": arguments},
                    handoff_reason=f"计划步骤 {step.id} 需要代码执行"
                )
                result = await self.handoff.handoff(req)
                return result.response
            else:
                return "[警告] 代码执行需要 Coder Agent，但 Handoff 未配置"

        # Handoff 到 Researcher (fetch/research 相关)
        if tool in ("mcp:fetch", "research", "fetch"):
            if self.handoff:
                req = HandoffRequest(
                    from_agent=self.name,
                    to_agent="researcher",
                    user_input=step.description,
                    context_summary=f"执行计划步骤 {step.id}: {step.description}",
                    working_memory={"research_task": step.description, "arguments": arguments},
                    handoff_reason=f"计划步骤 {step.id} 需要信息检索"
                )
                result = await self.handoff.handoff(req)
                return result.response
            else:
                return "[警告] 信息检索需要 Researcher Agent，但 Handoff 未配置"

        # MCP 工具
        if tool.startswith("mcp:"):
            return f"[MCP 工具] {tool} 执行: {arguments}"

        # Skill
        if tool.startswith("skill:"):
            skill_name = tool[6:]
            return f"[Skill] {skill_name} 执行: {arguments}"

        # 未知工具 - fallback 到 LLM
        logger.warning(f"[Executor] 未知工具 '{tool}'，fallback 到 LLM")
        messages = [{"role": "user", "content": f"请完成以下任务: {step.description}"}]
        return await self._call_llm(messages)

    def _resolve_arguments(self, arguments: Dict, context: AgentContext) -> Dict:
        """解析参数中的变量引用"""
        resolved = {}
        results = self.working_memory.get("execution_results", {})

        for key, val in arguments.items():
            if isinstance(val, str):
                # 替换 {{stepN.result}}
                def replacer(match):
                    ref_id = match.group(1)
                    ref = results.get(ref_id, {})
                    return ref.get("result", match.group(0))
                val = re.sub(r"\{\{step(\d+)\.result\}\}", replacer, val)
            resolved[key] = val
        return resolved

    def _generate_summary(self, plan: Plan) -> str:
        total = len(plan.steps)
        success = sum(1 for s in plan.steps if s.status == StepStatus.SUCCESS)
        failed = sum(1 for s in plan.steps if s.status == StepStatus.FAILED)

        parts = [f"✅ 计划执行完成: {success}/{total} 步成功"]
        if failed > 0:
            parts.append(f"❌ {failed} 步失败")

        for s in plan.steps:
            if s.result:
                preview = s.result[:200] + "..." if len(s.result) > 200 else s.result
                parts.append(f"\n【步骤 {s.id}: {s.description}】\n{preview}")

        return "\n".join(parts)

    def _dict_to_plan(self, data: Dict) -> Plan:
        """从 dict 恢复 Plan 对象"""
        steps = []
        for s in data.get("steps", []):
            steps.append(Step(
                id=s["id"],
                description=s["description"],
                tool=s["tool"],
                arguments=s.get("arguments", {}),
                depends_on=s.get("depends_on", []),
                status=StepStatus(s.get("status", "pending")),
                result=s.get("result"),
                error=s.get("error"),
                retry_count=s.get("retry_count", 0),
            ))
        return Plan(
            task=data.get("task", ""),
            steps=steps,
            status=StepStatus(data.get("status", "pending")),
            summary=data.get("summary")
        )
