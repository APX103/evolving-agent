
"""
计划执行器
支持串行 + 并行步骤执行，管理状态流转
同步 + 异步双模式

v2: 基于 Graph 引擎的拓扑执行，支持条件分支、重试循环、子图嵌套
"""
import asyncio
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, Optional

from simpleeval import SimpleEval

from agent.llm.base import LLMClient
from agent.plan import Plan, Step, StepStatus
from agent.mcp_client import MCPClient
from agent.sandbox import PythonSandbox
from agent.workflow.graph import Graph, Node, Edge
from agent.checkpoint import CheckpointManager

logger = logging.getLogger(__name__)


class Executor:
    """
    计划执行器
    支持并行执行无依赖关系的步骤
    """

    def __init__(
        self,
        llm_client: LLMClient,
        mcp_client: Optional[MCPClient] = None,
        skills=None,
        sandbox: Optional[PythonSandbox] = None,
        max_workers: int = 4,
        checkpoint_mgr: Optional[CheckpointManager] = None,
    ):
        self.llm_client = llm_client
        self.mcp_client = mcp_client
        self.skills = skills
        self.sandbox = sandbox or PythonSandbox()
        self.max_retries = 2
        self.max_workers = max_workers
        self.checkpoint_mgr = checkpoint_mgr

    # -- 同步接口（兼容层）--

    def run(self, plan: Plan) -> Plan:
        """
        同步包装：在无事件循环的环境中启动异步执行
        如果已有 running loop，则无法使用（应改用 arun）
        """
        try:
            loop = asyncio.get_running_loop()
            logger.warning("[Executor] 在异步上下文中调用了 sync run()，尝试创建新任务")
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, self.arun(plan))
                return future.result()
        except RuntimeError:
            return asyncio.run(self.arun(plan))

    # -- 异步核心 --

    async def arun(self, plan: Plan) -> Plan:
        """
        异步执行完整计划（基于 Graph 引擎）
        返回执行后的 Plan（包含每步结果）
        """
        logger.info(f"[Executor] 开始执行计划: {plan.task}")
        plan.status = StepStatus.RUNNING

        graph = self._plan_to_graph(plan)
        state: Dict[str, Any] = {"plan": plan}

        await graph.execute(state)

        plan.status = StepStatus.SUCCESS if plan.is_success() else StepStatus.FAILED
        plan.summary = self._generate_summary(plan)
        logger.info(f"[Executor] 计划执行完成: {plan.status.value}")
        return plan

    def _plan_to_graph(self, plan: Plan) -> Graph:
        """将 Plan 转换为 Graph"""
        graph = Graph(name=f"plan_{plan.task[:20]}")

        # Create nodes
        for step in plan.steps:
            node_name = f"step_{step.id}"
            max_retries = step.max_retries if step.max_retries > 0 else self.max_retries
            node = Node(
                name=node_name,
                func=self._make_step_func(step, plan),
                retry_count=max_retries if step.on_failure != "retry" else max_retries,
            )
            graph.add_node(node)

        # Create dependency edges with success condition
        for step in plan.steps:
            target = f"step_{step.id}"
            for dep_id in step.depends_on:
                source = f"step_{dep_id}"
                graph.add_edge(Edge(
                    source=source,
                    target=target,
                    condition=lambda s, src=source: s.get(src) != "__FAILED__",
                ))

        # Create fallback edges for on_failure pointing to a step id
        for step in plan.steps:
            if step.on_failure not in ("", "abort", "retry"):
                source = f"step_{step.id}"
                target = f"step_{step.on_failure}"
                graph.add_edge(Edge(
                    source=source,
                    target=target,
                    condition=lambda s, src=source: s.get(src) == "__FAILED__",
                ))

        return graph

    def _make_step_func(self, step: Step, plan: Plan):
        """为 Step 创建 Graph Node 执行函数"""
        async def _node_func(state: Dict) -> Any:
            # 1. Evaluate condition
            if step.condition and not self._eval_condition(step.condition, state):
                logger.info(f"[Executor] Step {step.id} condition False, skipping")
                step.status = StepStatus.SUCCESS
                step.result = "__SKIPPED__"
                return step.result

            # 2. Pre-checkpoint
            if self.checkpoint_mgr:
                self.checkpoint_mgr.save(
                    {"plan": plan.to_dict(), "state": state},
                    checkpoint_id=f"pre_step_{step.id}"
                )

            step.status = StepStatus.RUNNING
            arguments = self._resolve_arguments(step.arguments, plan)

            try:
                result = await self._ainvoke_tool(step.tool, arguments, step.description)
                step.result = str(result) if result is not None else ""
                step.status = StepStatus.SUCCESS
                step.error = None
                logger.info(f"[Executor] Step {step.id} 成功")
            except Exception as e:
                step.error = str(e)
                step.retry_count += 1

                max_retries = step.max_retries if step.max_retries > 0 else self.max_retries
                if step.retry_count <= max_retries:
                    step.status = StepStatus.RETRYING
                    logger.warning(
                        f"[Executor] Step {step.id} 失败，重试 {step.retry_count}/{max_retries}: {e}"
                    )
                    raise  # Graph engine will retry
                else:
                    if step.on_failure == "abort" or step.on_failure == "":
                        step.status = StepStatus.FAILED
                        logger.error(f"[Executor] Step {step.id} 失败（已达最大重试）: {e}")
                        raise
                    elif step.on_failure == "retry":
                        step.status = StepStatus.FAILED
                        logger.error(f"[Executor] Step {step.id} 重试耗尽仍失败: {e}")
                        raise
                    else:
                        step.status = StepStatus.FAILED
                        logger.warning(
                            f"[Executor] Step {step.id} 失败，触发 fallback -> {step.on_failure}: {e}"
                        )
                        return "__FAILED__"

            # 3. Post-checkpoint
            if self.checkpoint_mgr:
                self.checkpoint_mgr.save(
                    {"plan": plan.to_dict(), "state": state},
                    checkpoint_id=f"post_step_{step.id}"
                )

            return step.result

        return _node_func

    def _eval_condition(self, condition: str, state: Dict) -> bool:
        """Evaluate a simple condition string against state using safe evaluator"""
        try:
            evaluator = SimpleEval(names=state, functions={})
            result = evaluator.eval(condition)
            return bool(result)
        except Exception as e:
            logger.warning(f"[Executor] Condition eval error '{condition}': {e}")
            return False

    # -- 异步工具调用 --

    async def _ainvoke_tool(self, tool: str, arguments: Dict, context: str = "") -> Any:
        """异步调用具体工具"""
        if tool == "llm":
            prompt = arguments.get("prompt", context)
            return await self.llm_client.aquick_chat(
                prompt,
                system=arguments.get("system", "你是一个有帮助的助手。")
            )

        if tool.startswith("mcp:") and self.mcp_client:
            tool_name = tool[4:]
            result = await self.mcp_client.call_tool_by_name(tool_name, arguments)
            if result.success:
                return result.content
            raise RuntimeError(f"MCP tool '{tool_name}' 失败: {result.error}")

        if tool == "sandbox":
            code = arguments.get("code", arguments.get("input", ""))
            result = self.sandbox.execute(code)
            if result.success:
                return result.output
            raise RuntimeError(f"沙箱执行失败: {result.error}")

        if tool.startswith("skill:") and self.skills:
            skill_name = tool[6:]
            fake_input = f"/{skill_name} {arguments.get('input', '')}"
            handler = self.skills.find_handler(fake_input, {})
            if handler:
                result = handler.execute(fake_input, {})
                return result.content
            raise RuntimeError(f"Skill '{skill_name}' 未找到")

        raise RuntimeError(f"未知工具: {tool}")

    # -- 同步步骤执行（供 run() 的 ThreadPoolExecutor 使用）--

    def _execute_steps_parallel(self, plan: Plan, steps: list):
        """同步并行执行多个步骤（ThreadPoolExecutor）"""
        with ThreadPoolExecutor(max_workers=min(len(steps), self.max_workers)) as pool:
            future_to_step = {
                pool.submit(self._execute_step_worker, plan, step): step
                for step in steps
            }
            for future in as_completed(future_to_step):
                step = future_to_step[future]
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"[Executor] Step {step.id} 并行执行异常: {e}")
                    step.status = StepStatus.FAILED
                    step.error = str(e)

    def _execute_step(self, plan: Plan, step: Step):
        """执行单个步骤（同步包装）"""
        self._execute_step_worker(plan, step)

    def _execute_step_worker(self, plan: Plan, step: Step):
        """执行单个步骤的核心逻辑（同步版本）"""
        logger.info(f"[Executor] Step {step.id}: {step.description} [{step.tool}]")
        step.status = StepStatus.RUNNING

        arguments = self._resolve_arguments(step.arguments, plan)

        try:
            result = self._invoke_tool(step.tool, arguments, step.description)
            step.result = str(result) if result is not None else ""
            step.status = StepStatus.SUCCESS
            logger.info(f"[Executor] Step {step.id} 成功")
        except Exception as e:
            step.error = str(e)
            step.retry_count += 1

            max_retries = step.max_retries if step.max_retries > 0 else self.max_retries
            if step.retry_count <= max_retries:
                step.status = StepStatus.RETRYING
                logger.warning(f"[Executor] Step {step.id} 失败，重试 {step.retry_count}/{max_retries}: {e}")
                try:
                    result = self._invoke_tool(step.tool, arguments, step.description)
                    step.result = str(result) if result is not None else ""
                    step.status = StepStatus.SUCCESS
                    step.error = None
                    logger.info(f"[Executor] Step {step.id} 重试成功")
                except Exception as e2:
                    step.error = f"{e} -> 重试失败: {e2}"
                    step.status = StepStatus.FAILED
                    logger.error(f"[Executor] Step {step.id} 重试后仍失败: {e2}")
            else:
                step.status = StepStatus.FAILED
                logger.error(f"[Executor] Step {step.id} 失败（已达最大重试）: {e}")

    def _invoke_tool(self, tool: str, arguments: Dict, context: str = "") -> Any:
        """调用具体工具（同步版本，兼容层）"""
        if tool == "llm":
            prompt = arguments.get("prompt", context)
            return self.llm_client.quick_chat(
                prompt,
                system=arguments.get("system", "你是一个有帮助的助手。")
            )

        if tool.startswith("mcp:") and self.mcp_client:
            tool_name = tool[4:]
            try:
                loop = asyncio.get_running_loop()
                raise RuntimeError(
                    "在异步上下文中调用 sync _invoke_tool 的 MCP 工具。"
                    "请使用 Executor.arun() 替代 Executor.run()"
                )
            except RuntimeError:
                loop = asyncio.new_event_loop()
                try:
                    result = loop.run_until_complete(
                        self.mcp_client.call_tool_by_name(tool_name, arguments)
                    )
                finally:
                    loop.close()
            if result.success:
                return result.content
            raise RuntimeError(f"MCP tool '{tool_name}' 失败: {result.error}")

        if tool == "sandbox":
            code = arguments.get("code", arguments.get("input", ""))
            result = self.sandbox.execute(code)
            if result.success:
                return result.output
            raise RuntimeError(f"沙箱执行失败: {result.error}")

        if tool.startswith("skill:") and self.skills:
            skill_name = tool[6:]
            fake_input = f"/{skill_name} {arguments.get('input', '')}"
            handler = self.skills.find_handler(fake_input, {})
            if handler:
                result = handler.execute(fake_input, {})
                return result.content
            raise RuntimeError(f"Skill '{skill_name}' 未找到")

        raise RuntimeError(f"未知工具: {tool}")

    def _resolve_arguments(self, arguments: Dict, plan: Plan) -> Dict:
        """
        解析参数中的变量引用
        支持 {{stepN.result}} 和 {{stepN.description}}
        """
        resolved = {}
        for key, val in arguments.items():
            if isinstance(val, str):
                def replacer(match):
                    ref_id = int(match.group(1))
                    ref_step = plan.get_step(ref_id)
                    if ref_step and ref_step.result is not None:
                        return ref_step.result
                    return match.group(0)
                val = re.sub(r"\{\{step(\d+)\.result\}\}", replacer, val)

                def desc_replacer(match):
                    ref_id = int(match.group(1))
                    ref_step = plan.get_step(ref_id)
                    if ref_step:
                        return ref_step.description
                    return match.group(0)
                val = re.sub(r"\{\{step(\d+)\.description\}\}", desc_replacer, val)
            resolved[key] = val
        return resolved

    def _generate_summary(self, plan: Plan) -> str:
        """生成计划执行摘要"""
        total = len(plan.steps)
        success = sum(1 for s in plan.steps if s.status == StepStatus.SUCCESS)
        failed = sum(1 for s in plan.steps if s.status == StepStatus.FAILED)

        parts = [f"计划执行完成: {success}/{total} 步成功"]
        if failed > 0:
            parts.append(f"{failed} 步失败")

        for s in plan.steps:
            if s.result and len(s.result) > 0:
                preview = s.result[:200] + "..." if len(s.result) > 200 else s.result
                parts.append(f"\n【{s.description}】\n{preview}")

        return "\n".join(parts)
