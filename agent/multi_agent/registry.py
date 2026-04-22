"""
Agent 注册中心 - 管理所有 Agent 实例，负责路由和生命周期
"""
import logging
from typing import Dict, List, Optional, Any

from agent.multi_agent.base import BaseAgent, AgentContext, AgentResponse, IntentClassification
from agent.multi_agent.context_manager import ContextManager

logger = logging.getLogger(__name__)


class AgentRegistry:
    def __init__(self, memory, llm_client, config: Optional[Dict] = None):
        self._agents: Dict[str, BaseAgent] = {}
        self._router: Optional[BaseAgent] = None
        self.memory = memory
        self.llm = llm_client
        self.config = config or {}
        self.context_manager: Optional[ContextManager] = None

    def register(self, agent: BaseAgent) -> None:
        self._agents[agent.name] = agent
        logger.info(f"[AgentRegistry] 注册 Agent: {agent.name}")

    def set_router(self, router: BaseAgent) -> None:
        self._router = router
        logger.info("[AgentRegistry] 设置 Router")

    def set_context_manager(self, cm: ContextManager) -> None:
        self.context_manager = cm

    def get_agent(self, name: str) -> Optional[BaseAgent]:
        return self._agents.get(name)

    async def process(self, user_input: str, user_id: str, source: str = "cli") -> AgentResponse:
        if not self._router:
            raise RuntimeError("Router 未设置")

        # 1. 构建上下文
        if self.context_manager:
            context = await self.context_manager.build_context(user_id, query=user_input, source=source)
        else:
            context = AgentContext(user_id=user_id, source=source)

        # 2. 意图分类
        try:
            intent = await self._router.classify(user_input, context)
        except Exception as e:
            logger.warning(f"[AgentRegistry] 意图分类失败: {e}，使用 fallback")
            intent = self._fallback_classify(user_input)

        logger.info(f"[AgentRegistry] 意图: {intent.primary_intent} -> {intent.target_agent} (置信度: {intent.confidence:.2f})")

        # 3. 选择 Agent
        agent = self._select_agent(intent)

        # 4. 执行
        try:
            response = await agent.process(user_input, context)
            response.metadata["intent"] = intent.primary_intent
            response.metadata["agent"] = agent.name
            return response
        except Exception as e:
            logger.error(f"[AgentRegistry] Agent {agent.name} 执行失败: {e}")
            return AgentResponse(
                content=f"抱歉，处理时出了点问题: {e}",
                agent_name=agent.name,
                metadata={"error": str(e)}
            )

    def _select_agent(self, intent: IntentClassification) -> BaseAgent:
        # 策略 1: Router 指定了目标 Agent
        if intent.target_agent and intent.target_agent in self._agents:
            return self._agents[intent.target_agent]

        # 策略 2: 按 can_handle 置信度排序
        candidates = []
        for name, agent in self._agents.items():
            try:
                score = agent.can_handle(intent)
                if score > 0:
                    candidates.append((name, score))
            except Exception:
                continue

        if candidates:
            candidates.sort(key=lambda x: x[1], reverse=True)
            return self._agents[candidates[0][0]]

        # 策略 3: fallback 到 companion
        if "companion" in self._agents:
            return self._agents["companion"]

        # 策略 4: 返回第一个可用的
        return list(self._agents.values())[0]

    def _fallback_classify(self, user_input: str) -> IntentClassification:
        text = user_input.lower()
        code_keywords = ["代码", "编程", "python", "javascript", "bug", "调试", "debug", "函数", "class", "import"]
        research_keywords = ["调研", "搜索", "查一下", "资料", "信息", "对比", "区别", "什么是"]

        if any(k in text for k in code_keywords):
            return IntentClassification("code", 0.7, "coder")
        if any(k in text for k in research_keywords):
            return IntentClassification("research", 0.7, "researcher")
        return IntentClassification("chat", 0.5, "companion")

    def list_agents(self) -> List[Dict]:
        return [{"name": a.name, "description": a.description} for a in self._agents.values()]
