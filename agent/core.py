"""
Agent 核心逻辑 (v3)
协调记忆、人格、情绪、关系、Skill、后台学习和对话
"""
import yaml
import threading
import os
from typing import List, Dict, Optional
from datetime import datetime

from agent.kimi_client import KimiClient
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


class EvolvingAgent:
    def __init__(self, config_path: str = "config.yaml"):
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)
        
        self.agent_cfg = self.config["agent"]
        self.name = self.agent_cfg.get("name", "Evo")
        
        # 初始化各模块
        self.client = KimiClient(config_path)
        self.memory = MemoryManager(config_path)
        self.learner = Learner(self.client, self.memory)
        self.reflector = Reflector(self.client, self.memory)
        
        # 人格引擎 + 信号学习
        storage_base = self.config["storage"].get("base_path", "./storage")
        self.personality = PersonalityEngine(
            storage_path=self.config["storage"].get("personality", os.path.join(storage_base, "personality"))
        )
        self.signal_learner = SignalLearner(self.client, self.memory, self.personality)
        
        # 🔥 通人性三大模块
        self.emotion_sensor = EmotionSensor(self.client)
        self.relationship = RelationshipLog(
            storage_path=self.config["storage"].get("relationship", os.path.join(storage_base, "relationship"))
        )
        self.mood = AgentMood(
            storage_path=self.config["storage"].get("mood", os.path.join(storage_base, "mood"))
        )
        
        # Skill 插件系统
        self.skills = build_default_skills()
        
        self.session_active = False
        self._learning_thread: Optional[threading.Thread] = None
        self._learning_logs: List[str] = []
        self._log_lock = threading.Lock()
    
    def _build_system_prompt(self, query_hint: str = "") -> str:
        """构建包含身份、人格、记忆、关系、情绪的动态系统提示"""
        parts = []
        
        # 身份
        parts.append(f"你是 {self.name}，一个不断学习和进化的 AI 助手。")
        parts.append("每次对话后你都会复盘学习，所以你会越来越了解用户、越来越擅长帮助他们。")
        
        # 🔥 关系档案
        rel_context = self.relationship.get_relationship_context()
        if rel_context:
            parts.append(f"\n{rel_context}")
        
        # 🔥 Agent 自身情绪状态（内在状态，不是用户偏好）
        mood_instruction = self.mood.get_instruction()
        if mood_instruction:
            parts.append(f"\n【你此刻的状态】\n{mood_instruction}")
        
        # 自我认知（反思产物）
        personality_text = self.memory.get_profile("agent_personality")
        if personality_text:
            parts.append(f"\n【你的自我认知】{personality_text}")
        
        # 动态人格行为指令
        behavior = self.personality.get_behavior_instructions()
        if behavior:
            parts.append(f"\n【当前风格指令】\n{behavior}")
        
        # 基于当前问题的语义召回上下文
        context = self.memory.get_relevant_context(query_hint=query_hint, limit=5)
        if context:
            parts.append(f"\n{context}")
        
        # 基础行为指南
        parts.append("\n【行为指南】")
        parts.append("- 自然对话，不需要过度礼貌")
        parts.append("- 记住用户之前说过的话，自然地引用")
        parts.append("- 如果被纠正了，欣然接受并记住")
        parts.append("- 可以适当展示你的个性，不要像个客服")
        
        return "\n".join(parts)
    
    def start_session(self):
        """开始新会话"""
        if self._learning_thread and self._learning_thread.is_alive():
            self._learning_thread.join(timeout=60)
            self._learning_thread = None

        self.session_active = True
        self.mood.reset_session()
        self.emotion_sensor.session_emotions.clear()
        
        # 检查是否需要反思
        if self.reflector.should_reflect(self.agent_cfg.get("reflect_threshold", 5)):
            print("\n🧠 我正在反思之前的对话，准备进化一下...")
            reflection = self.reflector.reflect()
            print(f"💡 反思完成：{reflection.get('summary', '')}")
            if reflection.get("growth_goals"):
                print(f"🎯 接下来的目标：{', '.join(reflection['growth_goals'])}")
            if reflection.get("confidence_change"):
                try:
                    delta = float(reflection["confidence_change"])
                    self.personality.adjust("confidence", delta)
                    print(f"   人格自信度调整为: {self.personality.get('confidence'):.2f}")
                except ValueError:
                    pass
            print()
    
    def chat(self, user_input: str):
        """处理用户输入，返回字符串（Skill）或生成器（LLM 流式）"""
        if not self.session_active:
            self.start_session()
        
        # 先打印后台学习积累日志
        self._flush_learning_logs()
        
        # ── 实时人格调整（信号词） ──
        signal_changes = self.personality.apply_signals(user_input)
        if signal_changes:
            changed_dims = ", ".join([f"{k}→{v:+.2f}" for k, v in signal_changes.items()])
            print(f"  [人格微调: {changed_dims}]")
        
        # 🔥 情绪感知
        emotion_result = self.emotion_sensor.analyze(user_input)
        emotion_label = emotion_result.get("label", "平静")
        emotion_intensity = emotion_result.get("intensity", 0.5)
        
        if emotion_label != "平静" or emotion_intensity > 0.6:
            print(f"  [情绪感知: {emotion_label} {emotion_intensity:.1f}]")
            if emotion_result.get("needs"):
                print(f"    用户需要: {', '.join(emotion_result['needs'][:3])}")
        
        # 情绪驱动的 personality 微调
        emotion_style_adj = self.emotion_sensor.get_style_adjustments(emotion_result)
        for dim, delta in emotion_style_adj.items():
            self.personality.adjust(dim, delta)
        
        # 更新 Agent 自身 mood
        self.mood.turn_count_in_session = len(self.memory.short_term) // 2
        feedback_type = self._detect_quick_feedback(user_input)
        self.mood.update_from_interaction(
            user_emotion_label=emotion_label,
            user_emotion_intensity=emotion_intensity,
            turn_count=self.mood.turn_count_in_session,
            feedback_type=feedback_type
        )
        
        # 记录用户输入到短期记忆
        self.memory.add_turn("user", user_input)
        
        # ── Skill 路由 ──
        ctx = {
            "memory": self.memory,
            "personality": self.personality,
            "short_term": self.memory.short_term,
        }
        matched_skill = self.skills.find_handler(user_input, ctx)
        
        if matched_skill:
            print(f"  [调用 Skill: {matched_skill.name}]")
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
        
        # ── 无 Skill 匹配，走 LLM ──
        system_prompt = self._build_system_prompt(user_input)
        
        # 情绪适配指令追加
        emotion_instruction = self.emotion_sensor.get_response_instruction(emotion_result)
        if emotion_instruction:
            system_prompt += f"\n\n【此刻情绪适配】\n{emotion_instruction}"
        
        messages = self.memory.get_context_messages(
            system_prompt,
            max_turns=self.agent_cfg.get("max_short_term_turns", 10)
        )
        
        # 根据人格 + mood 动态调整 LLM 参数
        temperature = self.personality.get_temperature()
        temperature += self.mood.get_temperature_adjustment()
        temperature = max(0.1, min(1.0, temperature))
        max_tokens = self.personality.get_max_tokens()
        
        return self.client.chat(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True
        )
    
    def _detect_quick_feedback(self, text: str) -> str:
        """快速判断用户反馈类型，供 mood 使用"""
        lowered = text.lower()
        if any(s in lowered for s in ["不对", "错了", "纠正", "应该是", "你误解"]):
            return "correction"
        if any(s in lowered for s in ["谢谢", "感谢", "不错", "很好", "完美", "厉害"]):
            return "positive"
        if any(s in lowered for s in ["烦", "气", "无语", "失望", "没用", "不行"]):
            return "negative"
        return "neutral"
    
    def _flush_learning_logs(self):
        """将后台线程积累的学习日志一次性打印"""
        with self._log_lock:
            if self._learning_logs:
                for msg in self._learning_logs:
                    print(f"\n  {msg}")
                self._learning_logs.clear()

    def _background_learn(self, messages: List[Dict]):
        """后台线程：执行会话级学习，结果写入日志队列"""
        log_msg = ""
        try:
            result = self.learner.learn_from_session(messages)
            if result.get("learned"):
                merged = result.get("merged_count", 0)
                log_msg = f"🧠 [后台学习完成] 学到 {result['new_knowledge']} 条知识"
                if merged:
                    log_msg += f"，合并 {merged} 条"
                log_msg += f"，更新 {result['profile_updates']} 项画像"
            else:
                log_msg = f"🧠 [后台学习完成] {result.get('reason', '没有新内容')}"
        except Exception as e:
            log_msg = f"⚠️ [后台学习出错] {e}"
        finally:
            with self._log_lock:
                self._learning_logs.append(log_msg)
            self._learning_thread = None

    def end_session(self) -> Optional[Dict]:
        """结束会话并触发后台学习"""
        if not self.session_active:
            return None

        messages = self.memory.short_term.copy()
        
        # 🔥 记录关系事件
        if messages:
            self._record_relationship_event(messages)
            # 情绪趋势
            trend = self.emotion_sensor.get_session_emotion_trend()
            if trend:
                print(f"  [情绪趋势: {trend}]")
        
        self.memory.end_session()
        self.session_active = False

        print(f"\n💾 会话已保存。累计进行了 {self.memory.session_count} 次对话。")

        if self._learning_thread and self._learning_thread.is_alive():
            print("⏳ 等上一轮复盘结束...")
            self._learning_thread.join(timeout=30)

        if self.agent_cfg.get("learn_after_session", True) and messages:
            print("📚 复盘学习在后台进行，你可以继续聊...")
            self._learning_thread = threading.Thread(
                target=self._background_learn,
                args=(messages,),
                daemon=True
            )
            self._learning_thread.start()
        else:
            print()

        return {}
    
    def _record_relationship_event(self, messages: List[Dict]):
        """从会话中提取关系事件"""
        # 简单启发式：根据对话特征判断事件类型
        user_msgs = [m["content"] for m in messages if m["role"] == "user"]
        all_text = " ".join(user_msgs).lower()
        
        # 判断事件类型
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
        """流式输出结束后，记录回复并触发实时学习"""
        self.memory.add_turn("assistant", response)
        try:
            logs = self.signal_learner.on_turn_complete(user_input, response)
            if logs:
                for log in logs:
                    if log["signal"] not in ("feedback", "auto_verbosity_down", "auto_verbosity_up"):
                        print(f"\n  [实时学习: {log['signal']} → {log['result']}]")
        except Exception:
            pass

    def get_stats(self) -> Dict:
        """获取 Agent 成长统计"""
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
        }
    
    def get_personality_summary(self) -> str:
        """获取人格状态摘要"""
        return self.personality.summary()
