"""
Agent 核心逻辑 (v3.2)
协调记忆、人格、情绪、关系、Skill、后台学习和对话
新增：增量学习、反馈闭环、知识图谱
"""
import logging
import os
import threading
from typing import Dict, List, Optional
from datetime import datetime

from agent.core.config import Config
from agent.core.events import EventBus, default_bus
from agent.llm.kimi_client import KimiLLMClient
from agent.memory import MemoryManager
from agent.cognition.learner import Learner
from agent.cognition.reflector import Reflector
from agent.context.personality import PersonalityEngine
from agent.cognition.signal_learner import SignalLearner
from agent.skills.base import SkillRegistry
from agent.skills.builtin import build_default_skills
from agent.context.emotion import EmotionSensor
from agent.context.relationship import RelationshipLog
from agent.context.mood import AgentMood
from agent.storage.local_json import LocalJsonStorage
from agent.mcp.client import MCPClient, MCPServerConfig
from agent.skills.mcp_tool import MCPRouterSkill, MCPToolSkill
from agent.planning.planner import Planner
from agent.engine.executor import Executor
from agent.planning.plan import Plan, StepStatus
from agent.core.checkpoint import CheckpointManager
from agent.memory.procedural_memory import ProceduralMemory
from agent.context.world_state import WorldState
from agent.mcp.approval import ApprovalManager

logger = logging.getLogger("agent.core")


class EvolvingAgent:
    def __init__(self, config_path: str = "config.yaml", user_id: str = "default"):
        self.user_id = user_id
        self.config = Config(config_path)
        self.agent_cfg = self.config.agent
        self.name = self.agent_cfg.get("name", "Evo")

        self.storage = LocalJsonStorage()
        self.llm_client = KimiLLMClient(self.config)

        # 多用户隔离：按 user_id 生成独立存储目录
        storage_base = self.config.storage.get("base_path", "./storage")
        user_storage_base = os.path.join(storage_base, user_id)
        self.storage.ensure_dir(user_storage_base)

        self.memory = MemoryManager(
            config=self.config,
            storage=self.storage,
            llm_client=self.llm_client,
            base_path=user_storage_base,
        )
        self.learner = Learner(self.llm_client, self.memory)

        self.personality = PersonalityEngine(
            storage_path=os.path.join(user_storage_base, "personality"),
            storage=self.storage,
        )
        self.signal_learner = SignalLearner(
            self.llm_client, self.memory, self.personality,
            event_bus=default_bus,
        )

        self.emotion_sensor = EmotionSensor(self.llm_client)
        self.relationship = RelationshipLog(
            storage_path=os.path.join(user_storage_base, "relationship"),
            storage=self.storage,
        )
        self.mood = AgentMood(
            storage_path=os.path.join(user_storage_base, "mood"),
            storage=self.storage,
        )

        # 程序记忆
        self.procedural_memory = ProceduralMemory(
            storage_path=os.path.join(user_storage_base, "procedural_memory"),
            storage=self.storage,
            llm_client=self.llm_client,
        )

        self.reflector = Reflector(
            self.llm_client,
            self.memory,
            procedural_memory=self.procedural_memory,
        )

        # ── MCP 集成（必须在 WorldState 和 Executor 之前初始化）──
        self.mcp_client: Optional[MCPClient] = None
        self._init_mcp()

        # 世界状态（环境认知）
        self.world_state = WorldState(
            mcp_client=self.mcp_client,
            base_path=user_storage_base,
        )
        self.world_state.refresh_tool_status()

        # 审批管理器
        approval_cfg = self.config.raw.get("approval", {})
        self.approval_mgr = ApprovalManager(config=approval_cfg, mode=approval_cfg.get("mode", "blocking"))

        self.skills = build_default_skills(approval=self.approval_mgr)

        # ── PlanningFlow 集成 ──
        self.planner = Planner(self.llm_client)
        self.executor = Executor(
            llm_client=self.llm_client,
            mcp_client=self.mcp_client,
            skills=self.skills,
        )

        # ── Checkpoint 集成 ──
        self.checkpoint_mgr = CheckpointManager(
            base_path=os.path.join(user_storage_base, "checkpoints")
        )

        self.session_active = False
        self._learning_thread: Optional[threading.Thread] = None
        self._learning_logs: List[str] = []
        self._log_lock = threading.Lock()
        self._thread_lock = threading.Lock()

        self.event_bus = default_bus

    def _init_mcp(self):
        """同步初始化 MCP Client 配置（不连接，连接延迟到 ainit_mcp）"""
        mcp_cfg = self.config.raw.get("mcp", {})
        if not mcp_cfg.get("enabled", False):
            return

        servers = []
        for s in mcp_cfg.get("servers", []):
            try:
                servers.append(MCPServerConfig(
                    name=s["name"],
                    transport=s.get("transport", "stdio"),
                    command=s.get("command"),
                    args=s.get("args", []),
                    url=s.get("url"),
                    env=s.get("env", {}),
                ))
            except Exception as e:
                logger.warning(f"[MCP] 解析 server 配置失败: {e}")

        if not servers:
            return

        mcp_security_cfg = mcp_cfg.get("security", {})
        self.mcp_client = MCPClient(
            servers=servers,
            approval_manager=self.approval_mgr,
            security_config=mcp_security_cfg,
        )
        logger.info(f"[MCP] Client 已初始化，{len(servers)} 个 server 待连接")

    async def ainit_mcp(self):
        """异步连接 MCP Servers 并注册 Tools 为 Skills"""
        if self.mcp_client is None:
            return

        results = await self.mcp_client.connect_all()
        for name, ok in results.items():
            status = "✅" if ok else "❌"
            logger.info(f"[MCP] {status} {name}")

        # 将 MCP tools 注册为 Skill
        tools = self.mcp_client.list_tools()
        for tool in tools:
            self.skills.register(MCPToolSkill(
                self.mcp_client, tool.name, tool.description, tool.server
            ))
        # 注册 MCP 路由 Skill
        self.skills.register(MCPRouterSkill(self.mcp_client, self.llm_client))
        logger.info(f"[MCP] 已注册 {len(tools)} 个 MCP tools + 1 个路由 Skill")

    def _build_system_prompt(self, query_hint: str = "") -> str:
        parts = []
        parts.append(f"你是 {self.name}，一个不断学习和进化的 AI 助手。")
        parts.append("每次对话后你都会复盘学习，所以你会越来越了解用户、越来越擅长帮助他们。")

        rel_context = self.relationship.get_relationship_context()
        if rel_context:
            parts.append(f"\n{rel_context}")

        mood_instruction = self.mood.get_instruction()
        if mood_instruction:
            parts.append(f"\n【你此刻的状态】\n{mood_instruction}")

        personality_text = self.memory.get_profile("agent_personality")
        if personality_text:
            parts.append(f"\n【你的自我认知】{personality_text}")

        behavior = self.personality.get_behavior_instructions()
        if behavior:
            parts.append(f"\n【当前风格指令】\n{behavior}")

        context = self.memory.get_relevant_context(query_hint=query_hint, limit=5)
        if context:
            parts.append(f"\n{context}")

        # 注入程序记忆（行为策略）
        procedural = self.procedural_memory.get_prompt_text(query_hint)
        if procedural:
            parts.append(f"\n{procedural}")

        # 注入环境状态
        world_context = self.world_state.to_context_string()
        if world_context:
            parts.append(f"\n{world_context}")

        parts.append("\n【行为指南】")
        parts.append("- 自然对话，不需要过度礼貌")
        parts.append("- 记住用户之前说过的话，自然地引用")
        parts.append("- 如果被纠正了，欣然接受并记住")
        parts.append("- 可以适当展示你的个性，不要像个客服")

        return "\n".join(parts)

    def start_session(self):
        with self._thread_lock:
            thread = self._learning_thread
        if thread and thread.is_alive():
            thread.join(timeout=60)
        with self._thread_lock:
            self._learning_thread = None

        self.session_active = True
        self.mood.reset_session()
        self.emotion_sensor.session_emotions.clear()

        threshold = self.agent_cfg.get("reflect_threshold", 5)
        if self.reflector.should_reflect(threshold):
            logger.info("🧠 正在反思之前的对话，准备进化一下...")
            reflection = self.reflector.reflect()
            logger.info(f"💡 反思完成：{reflection.get('summary', '')}")
            if reflection.get("growth_goals"):
                logger.info(f"🎯 接下来的目标：{', '.join(reflection['growth_goals'])}")
            if reflection.get("confidence_change"):
                try:
                    delta = float(reflection["confidence_change"])
                    self.personality.adjust("confidence", delta)
                    logger.info(f"   人格自信度调整为: {self.personality.get('confidence'):.2f}")
                except ValueError:
                    pass
            logger.info("")

        self.event_bus.publish("session.started", {"agent": self.name})

    async def chat(self, user_input: str, image: Optional[str] = None):
        if not self.session_active:
            self.start_session()

        self._flush_learning_logs()
        self.event_bus.publish("turn.started", {"user_input": user_input, "has_image": bool(image)})

        # 人格信号微调
        signal_changes = self.personality.apply_signals(user_input)
        if signal_changes:
            changed_dims = ", ".join([f"{k}→{v:+.2f}" for k, v in signal_changes.items()])
            logger.info(f"  [人格微调: {changed_dims}]")

        # 情绪感知
        emotion_result = self.emotion_sensor.analyze(user_input)
        emotion_label = emotion_result.get("label", "平静")
        emotion_intensity = emotion_result.get("intensity", 0.5)

        if emotion_label != "平静" or emotion_intensity > 0.6:
            logger.info(f"  [情绪感知: {emotion_label} {emotion_intensity:.1f}]")
            if emotion_result.get("needs"):
                logger.info(f"    用户需要: {', '.join(emotion_result['needs'][:3])}")

        self.event_bus.publish("emotion.detected", emotion_result)

        emotion_style_adj = self.emotion_sensor.get_style_adjustments(emotion_result)
        for dim, delta in emotion_style_adj.items():
            self.personality.adjust(dim, delta)

        self.mood.turn_count_in_session = len(self.memory.short_term) // 2
        feedback_type = self._detect_quick_feedback(user_input)
        self.mood.update_from_interaction(
            user_emotion_label=emotion_label,
            user_emotion_intensity=emotion_intensity,
            turn_count=self.mood.turn_count_in_session,
            feedback_type=feedback_type
        )

        self.memory.add_turn("user", user_input, image=image)

        # ── PlanningFlow 路由（图片输入直接跳过，走 LLM）──
        if not image:
            is_explicit_plan = user_input.strip().startswith("/plan ")
            should_auto_plan = self.planner.should_plan(user_input)

            if is_explicit_plan or should_auto_plan:
                task = user_input.replace("/plan", "").strip() if is_explicit_plan else user_input
                logger.info(f"  [PlanningFlow] 任务规划: {task[:60]}...")
                plan = await self.planner.adecompose(task)

                if plan and plan.steps:
                    logger.info(f"  [PlanningFlow] 生成 {len(plan.steps)} 步计划")
                    plan = await self.executor.arun(plan)
                    response = plan.summary or "计划执行完成。"

                    # 记录执行结果
                    self.memory.add_turn("assistant", response)
                    try:
                        self.signal_learner.on_turn_complete(user_input, response)
                    except Exception as e:
                        logger.warning(f"[SignalLearner] Turn complete error: {e}")

                    # 如果是流式调用方，需要包装为生成器
                    def _plan_generator(text):
                        yield text
                    return _plan_generator(response)
                # plan 为 None 表示不需要规划，继续走正常流程

        # Skill 路由（图片输入直接跳过，走 LLM）
        if not image:
            ctx = {
                "memory": self.memory,
                "personality": self.personality,
                "short_term": self.memory.short_term,
            }
            matched_skill = self.skills.find_handler(user_input, ctx)

            if matched_skill:
                logger.info(f"  [调用 Skill: {matched_skill.name}]")
                self.event_bus.publish("skill.executed", {"skill": matched_skill.name, "input": user_input})
                try:
                    result = matched_skill.execute(user_input, ctx)
                    response = result.content
                    if result.should_learn and result.success:
                        self.memory.add_knowledge(
                            category="skill_result",
                            content=f"[{matched_skill.name}] {user_input} -> {result.content[:200]}",
                            source=f"skill:{matched_skill.name}"
                        )
                except Exception as e:
                    response = f"[Skill {matched_skill.name} 执行出错] {e}"

                self.memory.add_turn("assistant", response)
                try:
                    self.signal_learner.on_turn_complete(user_input, response)
                except Exception as e:
                    logger.warning(f"[SignalLearner] Turn complete error: {e}")

                return response

        # LLM 对话
        system_prompt = self._build_system_prompt(user_input)
        emotion_instruction = self.emotion_sensor.get_response_instruction(emotion_result)
        if emotion_instruction:
            system_prompt += f"\n\n【此刻情绪适配】\n{emotion_instruction}"

        messages = self.memory.get_context_messages(
            system_prompt,
            max_turns=self.agent_cfg.get("max_short_term_turns", 10)
        )

        temperature = self.personality.get_temperature()
        temperature += self.mood.get_temperature_adjustment()
        temperature = max(0.0, min(1.0, temperature))
        max_tokens = self.personality.get_max_tokens()

        return await self.llm_client.achat(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True
        )

    def _detect_quick_feedback(self, text: str) -> str:
        lowered = text.lower()
        if any(s in lowered for s in ["不对", "错了", "纠正", "应该是", "你误解"]):
            return "correction"
        if any(s in lowered for s in ["谢谢", "感谢", "不错", "很好", "完美", "厉害"]):
            return "positive"
        if any(s in lowered for s in ["烦", "气", "无语", "失望", "没用", "不行"]):
            return "negative"
        return "neutral"

    def _flush_learning_logs(self):
        with self._log_lock:
            if self._learning_logs:
                for msg in self._learning_logs:
                    logger.info(f"\n  {msg}")
                self._learning_logs.clear()

    def _background_learn(self, messages: List[Dict]):
        log_msg = ""
        try:
            result = self.learner.learn_from_session(messages)
            if result.get("learned"):
                merged = result.get("merged_count", 0)
                log_msg = f"🧠 [后台学习完成] 学到 {result['new_knowledge']} 条知识"
                if merged:
                    log_msg += f"，合并 {merged} 条"
                log_msg += f"，更新 {result['profile_updates']} 项画像"
                if result.get("triples"):
                    log_msg += f"，图谱 {len(result['triples'])} 个三元组"
            else:
                log_msg = f"🧠 [后台学习完成] {result.get('reason', '没有新内容')}"
        except Exception as e:
            log_msg = f"⚠️ [后台学习出错] {e}"
        finally:
            with self._log_lock:
                self._learning_logs.append(log_msg)
            with self._thread_lock:
                self._learning_thread = None

    def end_session(self) -> Optional[Dict]:
        if not self.session_active:
            return None

        messages = self.memory.short_term.copy()

        if messages:
            self._record_relationship_event(messages)
            trend = self.emotion_sensor.get_session_emotion_trend()
            if trend:
                logger.info(f"  [情绪趋势: {trend}]")

        self.memory.end_session()
        self.session_active = False

        # ── 保存 Checkpoint ──
        try:
            cp_id = self.checkpoint_mgr.save({
                "session_count": self.memory.session_count,
                "personality": self.personality.get_all(),
                "mood": self.mood.state,
                "relationship": self.relationship.get_summary(),
                "knowledge_count": len(self.memory.knowledge_base),
                "knowledge_base": self.memory.knowledge_base[:50],
                "short_term": self.memory.get_short_term(5),
                "working_memory": dict(self.memory.working_memory),
                "procedural_memory": [r.to_dict() for r in self.procedural_memory.list_rules()],
            })
            logger.info(f"  [Checkpoint 已保存: {cp_id}]")
        except Exception as e:
            logger.warning(f"[Checkpoint] 保存失败: {e}")

        logger.info(f"\n💾 会话已保存。累计进行了 {self.memory.session_count} 次会话。")

        with self._thread_lock:
            thread = self._learning_thread
        if thread and thread.is_alive():
            logger.info("⏳ 等上一轮复盘结束...")
            thread.join(timeout=30)

        with self._thread_lock:
            if self.agent_cfg.get("learn_after_session", True) and messages:
                logger.info("📚 复盘学习在后台进行，你可以继续聊...")
                self._learning_thread = threading.Thread(
                    target=self._background_learn,
                    args=(messages,),
                    daemon=True
                )
                self._learning_thread.start()
            else:
                logger.info("")

        self.event_bus.publish("session.ended", {"session_count": self.memory.session_count})
        return {}

    def _record_relationship_event(self, messages: List[Dict]):
        user_msgs = [m["content"] for m in messages if m["role"] == "user"]
        all_text = " ".join(user_msgs).lower()

        event_type = "routine"
        sentiment = 0.0
        desc = "日常对话"

        if self.memory.session_count == 1:
            event_type = "first_meet"
            sentiment = 0.3
            desc = "初次见面"
        elif any(s in all_text for s in ["谢谢", "感谢", "不错", "很好", "完美"]):
            event_type = "user_praised"
            sentiment = 0.6
            desc = "用户表达了认可或感谢"
        elif any(s in all_text for s in ["不对", "错了", "你误解", "应该是"]):
            event_type = "user_corrected"
            sentiment = -0.2
            desc = "用户纠正了错误或误解"
        elif any(s in all_text for s in ["烦", "气", "无语", "失望"]):
            event_type = "user_frustrated"
            sentiment = -0.5
            desc = "用户表达了不满或沮丧"
        elif any(s in all_text for s in ["哈哈", "笑死", "开玩笑"]):
            event_type = "joke_shared"
            sentiment = 0.4
            desc = "双方有轻松的玩笑互动"
        elif len(user_msgs) > 10:
            event_type = "deep_talk"
            sentiment = 0.3
            desc = f"进行了较深入的交流（{len(user_msgs)}轮对话）"

        self.relationship.add_event(event_type, desc, sentiment)

    def finalize_response(self, user_input: str, response: str):
        """流式输出结束后，记录回复并触发实时学习 + 增量学习"""
        self.memory.add_turn("assistant", response)

        # ── 实时信号学习 ──
        try:
            logs = self.signal_learner.on_turn_complete(user_input, response)
            if logs:
                for log in logs:
                    if log["signal"] not in ("feedback", "auto_verbosity_down", "auto_verbosity_up"):
                        logger.info(f"\n  [实时学习: {log['signal']} → {log['result']}]")
        except Exception as e:
            logger.warning(f"[SignalLearner] Turn complete error: {e}")

        # ── 增量学习（每轮都学，不用等 /bye） ──
        try:
            incremental_result = self.learner.learn_from_turn(user_input, response)
            if incremental_result.get("learned"):
                logger.info(f"  [增量学习] 新知识: {incremental_result['new_knowledge']} 条, "
                           f"画像: {incremental_result['profile_updates']} 项")
        except Exception as e:
            logger.debug(f"增量学习跳过: {e}")

        # ── 反馈闭环：调整知识 confidence ──
        self._apply_feedback_to_knowledge(user_input, response)

    def _apply_feedback_to_knowledge(self, user_input: str, response: str):
        """
        自监督反馈闭环：
        - 用户表扬 → 提升相关知识的 confidence
        - 用户纠正 → 降低相关知识的 confidence，标记为待修正
        - 同时更新程序记忆（行为策略）
        """
        feedback_type = self._detect_quick_feedback(user_input)

        # 程序记忆学习
        try:
            correction = ""
            if feedback_type == "correction":
                correction = user_input
            self.procedural_memory.learn_from_feedback(user_input, response, feedback_type, correction)
        except Exception as e:
            logger.warning(f"[ProceduralMemory] Learn from feedback error: {e}")

        if feedback_type == "positive":
            # 召回与本轮对话相关的知识，提升 confidence
            related = self.memory.search_knowledge(query=user_input + " " + response, limit=3)
            for k in related:
                if "_confidence" not in k:
                    k["_confidence"] = 0.7
                k["_confidence"] = min(1.0, k["_confidence"] + 0.05)
                k["access_count"] = k.get("access_count", 0) + 2
            if related:
                self.storage.save_json(self.memory.knowledge_base, "knowledge_base.json", self.memory.knowledge_path)
                logger.info(f"  [反馈闭环] 用户认可，提升 {len(related)} 条知识权重")

        elif feedback_type == "correction":
            # 召回与 assistant_response 相关的知识，降低 confidence
            related = self.memory.search_knowledge(query=response, limit=3)
            for k in related:
                if "_confidence" not in k:
                    k["_confidence"] = 0.7
                k["_confidence"] = max(0.1, k["_confidence"] - 0.2)
                k["_status"] = "corrected"
                k["_correction_note"] = user_input
            if related:
                self.storage.save_json(self.memory.knowledge_base, "knowledge_base.json", self.memory.knowledge_path)
                logger.info(f"  [反馈闭环] 用户纠正，降低 {len(related)} 条知识权重并标记")

            # 同时尝试把纠正内容作为新知识写入
            try:
                self.memory.add_knowledge(
                    category="lesson",
                    content=f"用户纠正: {user_input} (原回复: {response[:100]})",
                    source="user_correction"
                )
            except Exception as e:
                logger.warning(f"[Memory] Add knowledge error: {e}")

    def get_stats(self) -> Dict:
        kg_stats = {}
        if self.memory.knowledge_graph:
            kg_stats = {
                "triples_count": len(self.memory.knowledge_graph.triples),
            }
        return {
            "name": self.name,
            "total_sessions": self.memory.session_count,
            "knowledge_count": len(self.memory.knowledge_base),
            "reflection_count": len(self.memory.reflections),
            "profile_keys": list(self.memory.get_profile().keys()),
            "current_session_active": self.session_active,
            "personality": self.personality.get_all(),
            "temperature": self.personality.get_temperature(),
            "max_tokens": self.personality.get_max_tokens(),
            **kg_stats,
        }

    def get_personality_summary(self) -> str:
        return self.personality.summary()
