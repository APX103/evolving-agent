"""
Agent 注册中心 - 管理所有 Agent 实例，负责路由和生命周期
新增：A2A 外部 Agent 发现与委托
"""
import logging
from typing import Dict, List, Optional, Any

from agent.multi_agent.base import BaseAgent, AgentContext, AgentResponse, IntentClassification
from agent.multi_agent.context_manager import ContextManager
from agent.observability import get_tracer

logger = logging.getLogger(__name__)


class AgentRegistry:
    def __init__(self, memory, llm_client, config: Optional[Dict] = None):
        self._agents: Dict[str, BaseAgent] = {}
        self._router: Optional[BaseAgent] = None
        self.memory = memory
        self.llm = llm_client
        self.config = config or {}
        self.context_manager: Optional[ContextManager] = None

        # A2A external agents
        self.external_agents: List[Any] = []
        self._a2a_discovery: Optional[Any] = None
        self._a2a_clients: Dict[str, Any] = {}
        self._init_a2a()

    def _init_a2a(self) -> None:
        """Initialize A2A discovery and load external agents from config."""
        a2a_config = self.config.get("a2a") if isinstance(self.config, dict) else None
        if not a2a_config:
            return
        urls = a2a_config.get("external_agents", []) if isinstance(a2a_config, dict) else []
        if not urls:
            return
        try:
            from agent.a2a.discovery import AgentDiscovery
            self._a2a_discovery = AgentDiscovery()
            self._pending_discovery_urls = urls
            logger.info(f"[AgentRegistry] A2A configured with {len(urls)} external agent URLs")
        except Exception as e:
            logger.warning(f"[AgentRegistry] A2A init failed: {e}")

    async def _ensure_external_agents(self) -> None:
        """Lazy discovery of external agents."""
        if hasattr(self, "_pending_discovery_urls") and self._pending_discovery_urls:
            if self._a2a_discovery is None:
                return
            urls = self._pending_discovery_urls
            self._pending_discovery_urls = []
            try:
                cards = await self._a2a_discovery.discover_all(urls)
                self.external_agents = cards
                from agent.a2a.client import A2AClient
                for card in cards:
                    self._a2a_clients[card.url] = A2AClient(card)
                logger.info(f"[AgentRegistry] Discovered {len(cards)} external A2A agents")
            except Exception as e:
                logger.warning(f"[AgentRegistry] External agent discovery failed: {e}")

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

        await self._ensure_external_agents()

        tracer = get_tracer()
        span = tracer.start_span("registry.process", attributes={"user_id": user_id, "source": source})
        span.set_attribute("input_length", len(user_input))

        try:
            if self.context_manager:
                context = await self.context_manager.build_context(user_id, query=user_input, source=source)
            else:
                context = AgentContext(user_id=user_id, source=source)

            try:
                intent = await self._router.classify(user_input, context)
            except Exception as e:
                logger.warning(f"[AgentRegistry] 意图分类失败: {e}，使用 fallback")
                intent = self._fallback_classify(user_input)

            logger.info(f"[AgentRegistry] 意图: {intent.primary_intent} -> {intent.target_agent} (置信度: {intent.confidence:.2f})")
            span.set_attribute("intent", intent.primary_intent)
            span.set_attribute("target_agent", intent.target_agent)
            span.set_attribute("confidence", round(intent.confidence, 3))

            agent = self._select_agent(intent, user_input)
            span.set_attribute("selected_agent", getattr(agent, "name", "external"))

            try:
                if isinstance(agent, BaseAgent):
                    response = await agent.process(user_input, context)
                    response.metadata["intent"] = intent.primary_intent
                    response.metadata["agent"] = agent.name
                    span.set_attribute("response_length", len(response.content))
                    return response
                else:
                    response = await self._delegate_to_external(agent, user_input, user_id)
                    response.metadata["intent"] = intent.primary_intent
                    response.metadata["agent"] = f"a2a:{getattr(agent, 'name', 'unknown')}"
                    span.set_attribute("response_length", len(response.content))
                    return response
            except Exception as e:
                logger.error(f"[AgentRegistry] Agent {getattr(agent, 'name', 'external')} 执行失败: {e}")
                span.record_exception(e)
                return AgentResponse(
                    content=f"抱歉，处理时出了点问题: {e}",
                    agent_name=getattr(agent, "name", "external"),
                    metadata={"error": str(e)}
                )
        finally:
            span.end()

    def _select_agent(self, intent: IntentClassification, user_input: str) -> Any:
        if intent.target_agent and intent.target_agent in self._agents:
            return self._agents[intent.target_agent]

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

        external_agent = self._match_external_agent(intent, user_input)
        if external_agent:
            logger.info(f"[AgentRegistry] 委托到外部 A2A Agent: {external_agent.name}")
            return external_agent

        if "companion" in self._agents:
            return self._agents["companion"]

        return list(self._agents.values())[0]

    def _match_external_agent(self, intent: IntentClassification, user_input: str) -> Optional[Any]:
        """Match an external A2A agent based on intent/skills."""
        if not self.external_agents:
            return None

        intent_key = intent.primary_intent.lower()
        for card in self.external_agents:
            for skill in card.skills:
                skill_tags = [t.lower() for t in skill.tags]
                skill_name = skill.name.lower()
                skill_desc = skill.description.lower()
                if intent_key in skill_tags or intent_key in skill_name or intent_key in skill_desc:
                    return card

        user_lower = user_input.lower()
        for card in self.external_agents:
            for skill in card.skills:
                for tag in skill.tags:
                    if tag.lower() in user_lower:
                        return card
                if skill.name.lower() in user_lower:
                    return card

        return None

    async def _delegate_to_external(self, agent_card: Any, user_input: str, user_id: str) -> AgentResponse:
        """Delegate task to an external A2A agent and translate result to AgentResponse."""
        from agent.a2a.client import A2AClient
        client = self._a2a_clients.get(agent_card.url)
        if client is None:
            client = A2AClient(agent_card)
            self._a2a_clients[agent_card.url] = client

        message = A2AClient.build_text_message(user_input, role="user")
        try:
            task = await client.send_task(message)
            text = ""
            for msg in task.messages:
                if msg.role == "agent":
                    for part in msg.parts:
                        if part.type == "text":
                            text += part.text
            if not text:
                text = "(外部 Agent 未返回文本内容)"
            return AgentResponse(
                content=text,
                agent_name=f"a2a:{agent_card.name}",
                metadata={"task_id": task.id, "source": "a2a"}
            )
        except Exception as e:
            logger.error(f"[AgentRegistry] A2A delegation failed: {e}")
            return AgentResponse(
                content=f"外部 Agent 调用失败: {e}",
                agent_name=f"a2a:{agent_card.name}",
                metadata={"error": str(e)}
            )

    def _fallback_classify(self, user_input: str) -> IntentClassification:
        text = user_input.lower()
        code_keywords = ["代码", "编程", "python", "javascript", "bug", "调试", "debug", "函数", "class", "import"]
        research_keywords = ["调研", "搜索", "查一下", "资料", "信息", "对比", "区别", "什么是"]

        if any(k in text for k in code_keywords):
            return IntentClassification(primary_intent="code", confidence=0.7, target_agent="coder")
        if any(k in text for k in research_keywords):
            return IntentClassification(primary_intent="research", confidence=0.7, target_agent="researcher")
        return IntentClassification(primary_intent="chat", confidence=0.5, target_agent="companion")

    def list_agents(self) -> List[Dict]:
        return [{"name": a.name, "description": a.description} for a in self._agents.values()]
