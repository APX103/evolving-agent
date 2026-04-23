"""
Handoff 协议 - Agent 间状态传递
支持：单步 Handoff、Chain Handoff、Debate、Verifier
"""
import logging
from typing import Dict, List

from pydantic import BaseModel, Field

from agent.multi_agent.base import BaseAgent, AgentContext, AgentResponse, HandoffRequest, HandoffResult
from agent.multi_agent.registry import AgentRegistry
from agent.observability import get_tracer

logger = logging.getLogger(__name__)


class VerificationResult(BaseModel):
    """内容审查结果 Schema"""
    passed: bool
    feedback: str
    score: float = Field(default=0.0, ge=0.0, le=1.0)


class HandoffProtocol:
    def __init__(self, registry: AgentRegistry):
        self.registry = registry
        self.llm = registry.llm if hasattr(registry, 'llm') else None

    async def handoff(self, request: HandoffRequest) -> HandoffResult:
        """执行 Agent 间交接"""
        tracer = get_tracer()
        span = tracer.start_span("handoff.handoff", attributes={
            "source_agent": request.from_agent,
            "target_agent": request.to_agent,
            "reason": request.handoff_reason,
        })

        agent = self.registry.get_agent(request.to_agent)
        if not agent:
            logger.error(f"[Handoff] 目标 Agent {request.to_agent} 不存在")
            span.set_attribute("error", "agent_not_found")
            span.end()
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
            span.set_attribute("response_length", len(response.content))
            span.end()
            return HandoffResult(
                from_agent=request.to_agent,
                response=response.content,
                updated_working_memory=agent.working_memory,
                learnings=response.metadata.get("learnings", [])
            )
        except Exception as e:
            logger.error(f"[Handoff] Agent {request.to_agent} 处理失败: {e}")
            span.record_exception(e)
            span.end()
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

    # ── Debate：多 Agent 辩论 ──

    async def debate(
        self,
        topic: str,
        agent_names: List[str],
        context: AgentContext,
        aggregator_prompt: str = ""
    ) -> AgentResponse:
        """
        多个 Agent 各自出方案，LLM aggregator 选最优
        """
        logger.info(f"[Debate] 主题: {topic[:50]}... | 参与者: {agent_names}")

        proposals = []
        for name in agent_names:
            agent = self.registry.get_agent(name)
            if not agent:
                continue
            try:
                response = await agent.process(topic, context)
                proposals.append({"agent": name, "proposal": response.content})
                logger.info(f"[Debate] {name} 已提交方案 ({len(response.content)} 字符)")
            except Exception as e:
                logger.warning(f"[Debate] {name} 失败: {e}")

        if not proposals:
            return AgentResponse(
                content="没有 Agent 能参与辩论。",
                agent_name="debate",
                metadata={"error": "no_proposals"}
            )

        if len(proposals) == 1:
            return AgentResponse(
                content=proposals[0]["proposal"],
                agent_name=f"debate/{proposals[0]['agent']}",
            )

        # LLM 聚合选择最佳方案
        prompt = self._build_debate_prompt(topic, proposals, aggregator_prompt)
        try:
            if self.llm:
                aggregated = await self.llm.aquick_chat(
                    prompt,
                    system="你是一位公正的评审。请综合各方方案的优点，给出最终最优方案。"
                )
            else:
                aggregated = self._simple_aggregate(proposals)
        except Exception as e:
            logger.warning(f"[Debate] LLM 聚合失败: {e}，使用简单聚合")
            aggregated = self._simple_aggregate(proposals)

        return AgentResponse(
            content=aggregated,
            agent_name="debate/aggregator",
            metadata={
                "proposals": proposals,
                "participants": agent_names,
            }
        )

    def _build_debate_prompt(self, topic: str, proposals: List[Dict], extra: str) -> str:
        lines = [f"主题: {topic}", "", "各方方案:"]
        for i, p in enumerate(proposals, 1):
            lines.append(f"\n--- 方案 {i} ({p['agent']}) ---")
            lines.append(p["proposal"][:1500])  # 截断避免 token 爆炸
        if extra:
            lines.append(f"\n评审标准: {extra}")
        lines.append("\n请综合以上方案，输出最终最优方案（可以直接采用某一个，也可以融合多个优点）：")
        return "\n".join(lines)

    def _simple_aggregate(self, proposals: List[Dict]) -> str:
        """无 LLM 时的简单聚合：拼接所有方案"""
        lines = ["【综合方案】"]
        for p in proposals:
            lines.append(f"\n--- {p['agent']} 的方案 ---")
            lines.append(p["proposal"])
        return "\n".join(lines)

    # ── Verifier：内容审查 ──

    async def verify(
        self,
        content: str,
        verifier_agent: str,
        criteria: str,
        context: AgentContext,
    ) -> Dict:
        """
        让 verifier agent 检查内容是否满足标准
        返回: {"passed": bool, "feedback": str, "score": float}
        """
        agent = self.registry.get_agent(verifier_agent)
        if not agent:
            return {"passed": False, "feedback": f"Verifier agent '{verifier_agent}' 未找到", "score": 0.0}

        prompt = f"""请审查以下内容，判断是否符合标准。

审查标准:
{criteria}

待审查内容:
```
{content[:3000]}
```

请输出 JSON:
{{
  "passed": true/false,
  "feedback": "具体反馈意见",
  "score": 0.0-1.0
}}
只输出 JSON，不要其他内容。"""

        try:
            response = await agent.process(prompt, context)
            result = self._parse_verification(response.content)
            logger.info(f"[Verify] {verifier_agent} 评分: {result.get('score', 0):.2f}, 通过: {result.get('passed', False)}")
            return result
        except Exception as e:
            logger.error(f"[Verify] 审查失败: {e}")
            return {"passed": False, "feedback": f"审查过程出错: {e}", "score": 0.0}

    def _parse_verification(self, text: str) -> Dict:
        """解析 verifier 的 JSON 输出"""
        import re
        try:
            # 提取 JSON 块
            m = re.search(r'\{.*\}', text, re.DOTALL)
            if m:
                return VerificationResult.model_validate_json(m.group()).model_dump()
        except Exception:
            pass
        # Fallback: 基于关键词判断
        passed = "通过" in text or "passed" in text.lower() or "合格" in text
        return VerificationResult(
            passed=passed,
            feedback=text[:500],
            score=0.7 if passed else 0.3,
        ).model_dump()
