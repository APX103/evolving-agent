"""
Agent 核心逻辑 (v3.2)
协调记忆、人格、情绪、关系、Skill、后台学习和对话
新增：增量学习、反馈闭环、知识图谱
"""
import logging
import threading
from typing import Dict, List, Optional
from datetime import datetime

from agent.config import Config
from agent.events import EventBus, default_bus
from agent.llm.kimi_client import KimiLLMClient
from agent.memory import MemoryManager
from agent.learner import Learner
from agent.reflector import Reflector
from agent.personality import PersonalityEngine
from agent.signal_learner import SignalLearner
from agent.skill import SkillRegistry
from agent.skills_builtin import build_default_skills
from agent.emotion import EmotionSensor
from agent.relationship import RelationshipLog
from agent.mood import AgentMood
from agent.storage.local_json import LocalJsonStorage
from agent.mcp_client import MCPClient, MCPServerConfig
from agent.mcp_tool_skill import MCPRouterSkill, MCPToolSkill

logger = logging.getLogger("agent.core")


class EvolvingAgent:
    def __init__(self, config_path: str = "config.yaml"):
        self.config = Config(config_path)
        self.agent_cfg = self.config.agent
        self.name = self.agent_cfg.get("name", "Evo")

        self.storage = LocalJsonStorage()
        self.llm_client = KimiLLMClient(self.config)

        self.memory = MemoryManager(
            config=self.config,
            storage=self.storage,
            llm_client=self.llm_client,
        )
        self.learner = Learner(self.llm_client, self.memory)
        self.reflector = Reflector(self.llm_client, self.memory)

        storage_base = self.config.storage.get("base_path", "./storage")
        self.personality = PersonalityEngine(
            storage_path=self.config.storage.get("personality", f"{storage_base}/personality"),
            storage=self.storage,
        )
        self.signal_learner = SignalLearner(
            self.llm_client, self.memory, self.personality,
            event_bus=default_bus,
        )

        self.emotion_sensor = EmotionSensor(self.llm_client)
        self.relationship = RelationshipLog(
            storage_path=self.config.storage.get("relationship", f"{storage_base}/relationship"),
            storage=self.storage,
        )
        self.mood = AgentMood(
            storage_path=self.config.storage.get("mood", f"{storage_base}/mood"),
            storage=self.storage,
        )

        self.skills = build_default_skills()

        # ── MCP 集成 ──
        self.mcp_client: Optional[MCPClient] = None
        self._init_mcp()

        self.session_active = False
        self._learning_thread: Optional[threading.Thread] = None
        self._learning_logs: List[str] = []
        self._log_lock = threading.Lock()

        self.event_bus = default_bus

    def _init_mcp(self):
        """初始化 MCP Client，连接配置的 MCP Servers"""
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

        self.mcp_client = MCPClient(servers)
        results = self.mcp_client.connect_all()
        for name, ok in results.items():
            status = "✅" if ok else "❌"
            logger.info(f"[MCP] {status} {name}")

        # 将 MCP tools 注册为 Skill
        if self.mcp_client:
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

        parts.append("\n【行为指南】")
        parts.append("- 自然对话，不需要过度礼貌")
        parts.append("- 记住用户之前说过的话，自然地引用")
        parts.append("- 如果被纠正了，欣然接受并记住")
        parts.append("- 可以适当展示你的个性，不要像个客服")

        return "\n".join(parts)

    def start_session(self):
        if self._learning_thread and self._learning_thread.is_alive():
            self._learning_thread.join(timeout=60)
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

    def chat(self, user_input: str):
        if not self.session_active:
            self.start_session()

        self._flush_learning_logs()
        self.event_bus.publish("turn.started", {"user_input": user_input})

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

        self.memory.add_turn("user", user_input)

        # Skill 路由
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
            except Exception:
                pass

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

        return self.llm_client.chat(
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

        logger.info(f"\n💾 会话已保存。累计进行了 {self.memory.session_count} 次会话。")

        if self._learning_thread and self._learning_thread.is_alive():
            logger.info("⏳ 等上一轮复盘结束...")
            self._learning_thread.join(timeout=30)

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
        except Exception:
            pass

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
        """
        feedback_type = self._detect_quick_feedback(user_input)

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
            except Exception:
                pass

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
