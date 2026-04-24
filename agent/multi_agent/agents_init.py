"""
Agent 工厂 - 创建所有 Agent 实例并组装完整系统
"""
import logging
from typing import Dict, Optional

from agent.multi_agent.base import BaseAgent
from agent.multi_agent.router import RouterAgent
from agent.multi_agent.companion import CompanionAgent
from agent.multi_agent.coder import CoderAgent
from agent.multi_agent.researcher import ResearcherAgent
from agent.multi_agent.planner import PlannerAgent
from agent.multi_agent.executor import ExecutorAgent
from agent.multi_agent.reviewer import ReviewerAgent
from agent.multi_agent.registry import AgentRegistry
from agent.multi_agent.context_manager import ContextManager
from agent.multi_agent.handoff import HandoffProtocol
from agent.observability.performance_monitor import PerformanceMonitor
from agent.cognition.agent_reflector import AgentReflector

logger = logging.getLogger(__name__)


def create_agents(memory, llm_client, config: Optional[Dict] = None,
                  handoff_protocol: Optional[HandoffProtocol] = None) -> Dict[str, BaseAgent]:
    """
    创建所有 Specialist Agent

    Args:
        memory: MemoryManager 实例
        llm_client: LLM 客户端
        config: 可选配置
        handoff_protocol: Handoff 协议实例（Executor 需要）

    Returns:
        name -> agent 映射字典
    """
    cfg = config or {}
    agents = {}

    # 核心 Specialist
    agents["companion"] = CompanionAgent("companion_1", memory, llm_client, cfg)
    agents["coder"] = CoderAgent("coder_1", memory, llm_client, cfg)
    agents["researcher"] = ResearcherAgent("researcher_1", memory, llm_client, cfg)

    # 规划与执行
    agents["planner"] = PlannerAgent("planner_1", memory, llm_client, cfg)
    agents["executor"] = ExecutorAgent("executor_1", memory, llm_client, cfg, handoff_protocol)
    agents["reviewer"] = ReviewerAgent("reviewer_1", memory, llm_client, cfg)

    logger.info(f"[AgentFactory] 创建 {len(agents)} 个 Agent: {list(agents.keys())}")
    return agents


def create_registry(memory, llm_client, config: Optional[Dict] = None) -> AgentRegistry:
    """
    创建完整的 AgentRegistry（含 Router + 所有 Specialist + ContextManager + Handoff）

    Args:
        memory: MemoryManager 实例
        llm_client: LLM 客户端
        config: 可选配置

    Returns:
        组装完成的 AgentRegistry
    """
    registry = AgentRegistry(memory, llm_client, config)

    # 创建 Router
    router = RouterAgent("router_1", memory, llm_client, config)
    registry.set_router(router)

    # 创建 Handoff 协议
    handoff = HandoffProtocol(registry)

    # 注册所有 Specialist
    agents = create_agents(memory, llm_client, config, handoff)
    for name, agent in agents.items():
        registry.register(agent)

    # 设置 ContextManager
    cm = ContextManager(memory, llm_client, config)
    registry.set_context_manager(cm)

    logger.info("[AgentFactory] AgentRegistry 初始化完成")
    logger.info(f"[AgentFactory] 可用 Agent: {', '.join(registry.list_agents())}")
    return registry


def create_full_system(memory, llm_client, config: Optional[Dict] = None) -> Dict:
    """
    创建完整的多 Agent 系统（含所有子系统）

    Returns:
        {
            "registry": AgentRegistry,
            "handoff": HandoffProtocol,
            "monitor": PerformanceMonitor,
            "reflector": AgentReflector,
        }
    """
    cfg = config or {}

    # 1. 创建 Registry
    registry = create_registry(memory, llm_client, cfg)

    # 2. 创建性能监控
    storage_path = cfg.get("storage_path", "./storage")
    monitor = PerformanceMonitor(storage_path=storage_path)

    # 3. 创建 Agent Reflector
    from agent.memory.memory_namespace import MemoryNamespace
    # 尝试获取 user_id
    user_id = getattr(memory, 'user_id', 'default')
    try:
        mem_ns = MemoryNamespace(user_id, memory, base_path=storage_path)
        reflector = AgentReflector(llm_client, mem_ns)
    except Exception:
        reflector = AgentReflector(llm_client, None)

    logger.info("[AgentFactory] 完整系统初始化完成")

    return {
        "registry": registry,
        "handoff": HandoffProtocol(registry),
        "monitor": monitor,
        "reflector": reflector,
    }
