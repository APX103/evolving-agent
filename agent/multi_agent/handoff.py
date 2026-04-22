"""
Handoff 协议 - Agent 间状态传递
"""
import logging
from typing import Dict, List

from agent.multi_agent.base import BaseAgent, AgentContext, HandoffRequest, HandoffResult
from agent.multi_agent.registry import AgentRegistry

logger = logging.getLogger(__name__)


class HandoffProtocol:
    def __init__(self, registry: AgentRegistry):
        self.registry = registry

    async def handoff(self, request: HandoffRequest) -> HandoffResult:
        """执行 Agent 间交接"""
        agent = self.registry.get_agent(request.to_agent)
        if not agent:
            logger.error(f"[Handoff] 目标 Agent {request.to_agent} 不存在")
            return HandoffResult(
                from_agent=request.to_agent,
                response=f"[错误] Agent {request.to_agent} 未找到",
                updated_working_memory=request.working_memory
            )

        # 注入 working_memory
        agent.working_memory.update(request.working_memory)

        # 构建上下文
        if self.registry.context_manager:
            context = await self.registry.context_manager.build_context(
                user_id="handoff",
                query=request.user_input
            )
        else:
            from agent.multi_agent.base import AgentContext
            context = AgentContext(user_id="handoff", source="handoff")

        # 添加上下文摘要
        context.metadata["handoff_from"] = request.from_agent
        context.metadata["handoff_reason"] = request.handoff_reason
        context.metadata["context_summary"] = request.context_summary

        # 调用目标 Agent
        try:
            response = await agent.process(request.user_input, context)
            return HandoffResult(
                from_agent=request.to_agent,
                response=response.content,
                updated_working_memory=agent.working_memory,
                learnings=response.metadata.get("learnings", [])
            )
        except Exception as e:
            logger.error(f"[Handoff] Agent {request.to_agent} 处理失败: {e}")
            return HandoffResult(
                from_agent=request.to_agent,
                response=f"[错误] 处理失败: {e}",
                updated_working_memory=agent.working_memory
            )

    async def handoff_chain(self, requests: List[HandoffRequest]) -> List[HandoffResult]:
        """顺序执行多个 Handoff"""
        results = []
        accumulated_wm = {}
        for req in requests:
            req.working_memory.update(accumulated_wm)
            result = await self.handoff(req)
            results.append(result)
            accumulated_wm.update(result.updated_working_memory)
        return results
