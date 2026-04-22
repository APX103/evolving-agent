"""
Agent 级独立 Reflector - 每个 Specialist 独立的反思进化
集成记忆命名空间，支持 Agent 私有反思记录
"""
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

REFLECTION_PROMPT_TEMPLATE = """你是 {agent_name} 的反思导师。请基于最近的交互记录，对 {agent_name} 进行一次深度反思。

【角色定义】
{agent_description}

【最近交互记录】
{interaction_history}

【用户反馈】
{user_feedback}

【反思要求】
1. 分析成功和失败的案例
2. 识别用户的深层需求和模式
3. 发现能力短板和改进方向
4. 提出具体的技能/策略提升建议

输出 JSON 格式：
{{
  "agent_name": "{agent_name}",
  "summary": "核心发现（一句话）",
  "strengths": ["优势1", "优势2"],
  "weaknesses": ["短板1", "短板2"],
  "user_patterns": "用户行为模式洞察",
  "improvement_suggestions": ["建议1", "建议2", "建议3"],
  "skill_gaps": ["缺失技能1", "缺失技能2"],
  "confidence_adjustment": 0.0,
  "next_goals": ["目标1", "目标2"]
}}"""


class AgentReflector:
    """
    Agent 级独立反思器
    每个 Specialist Agent 有独立的反思记录和改进方向
    """

    def __init__(self, llm_client, memory_namespace=None):
        self.llm = llm_client
        self.memory_ns = memory_namespace
        self.logger = logging.getLogger(__name__)
        # 内存中的交互记录缓存 (agent_name -> list)
        self._interaction_cache: Dict[str, List[Dict]] = {}
        # 反思触发阈值 (每 N 次交互触发一次)
        self.reflect_threshold = 5

    def record_interaction(self, agent_name: str, user_input: str,
                           response: str, feedback: str = ""):
        """记录一次 Agent 交互，用于后续反思"""
        if agent_name not in self._interaction_cache:
            self._interaction_cache[agent_name] = []

        self._interaction_cache[agent_name].append({
            "timestamp": datetime.now().isoformat(),
            "user_input": user_input[:200],
            "response": response[:200],
            "feedback": feedback,
        })

        # 保持最近 50 条
        self._interaction_cache[agent_name] = self._interaction_cache[agent_name][-50:]

        # 检查是否达到反思阈值
        interactions = self._interaction_cache[agent_name]
        if len(interactions) >= self.reflect_threshold and len(interactions) % self.reflect_threshold == 0:
            self.logger.info(f"[AgentReflector] {agent_name} 达到反思阈值 ({len(interactions)} 次交互)")
            # 异步触发反思（不阻塞主流程）
            import asyncio
            asyncio.create_task(self.reflect_async(agent_name))

    async def reflect_async(self, agent_name: str) -> Optional[Dict]:
        """异步执行反思"""
        try:
            return await self.reflect(agent_name)
        except Exception as e:
            self.logger.error(f"[AgentReflector] {agent_name} 反思失败: {e}")
            return None

    async def reflect(self, agent_name: str) -> Dict:
        """
        对指定 Agent 执行深度反思
        """
        interactions = self._interaction_cache.get(agent_name, [])
        if not interactions:
            return {"summary": "无交互记录", "agent_name": agent_name}

        # 构建反思素材
        history_text = self._format_interactions(interactions[-20:])
        feedback_text = self._extract_feedback(interactions)

        # Agent 角色描述
        descriptions = {
            "companion": "温暖陪伴型 Agent，负责日常对话和情感支持",
            "coder": "编程专家 Agent，负责代码生成、调试和技术实现",
            "researcher": "研究员 Agent，负责信息检索、资料收集和调研",
            "planner": "规划师 Agent，负责复杂任务分解和计划制定",
            "executor": "执行员 Agent，负责按计划调用工具完成动作",
            "reviewer": "审稿人 Agent，负责质量检查和反思纠错",
        }

        prompt = REFLECTION_PROMPT_TEMPLATE.format(
            agent_name=agent_name,
            agent_description=descriptions.get(agent_name, "通用 Agent"),
            interaction_history=history_text,
            user_feedback=feedback_text,
        )

        # 调用 LLM 生成反思
        messages = [{"role": "user", "content": prompt}]
        try:
            if hasattr(self.llm, 'achat'):
                response = await self.llm.achat(messages, temperature=0.3, max_tokens=1024)
            elif hasattr(self.llm, 'quick_chat'):
                import asyncio
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(
                    None, lambda: self.llm.quick_chat(prompt, "")
                )
            else:
                response = ""
        except Exception as e:
            self.logger.error(f"[AgentReflector] LLM 调用失败: {e}")
            response = ""

        reflection = self._parse_reflection(response, agent_name)

        # 保存反思记录
        self._save_reflection(agent_name, reflection)

        self.logger.info(f"[AgentReflector] {agent_name} 反思完成: {reflection.get('summary', '')}")
        return reflection

    def _format_interactions(self, interactions: List[Dict]) -> str:
        """格式化交互记录"""
        lines = []
        for i, inter in enumerate(interactions, 1):
            lines.append(f"{i}. 用户: {inter['user_input']}")
            lines.append(f"   回复: {inter['response']}")
            if inter.get('feedback'):
                lines.append(f"   反馈: {inter['feedback']}")
        return "\n".join(lines)

    def _extract_feedback(self, interactions: List[Dict]) -> str:
        """提取用户反馈"""
        feedbacks = [i['feedback'] for i in interactions if i.get('feedback')]
        if not feedbacks:
            return "（暂无明确反馈）"
        return "\n".join(f"- {f}" for f in feedbacks[-5:])

    def _parse_reflection(self, response: str, agent_name: str) -> Dict:
        """解析 LLM 输出的反思 JSON"""
        try:
            cleaned = response.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            if cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()

            data = json.loads(cleaned)
            return {
                "agent_name": data.get("agent_name", agent_name),
                "summary": data.get("summary", ""),
                "strengths": data.get("strengths", []),
                "weaknesses": data.get("weaknesses", []),
                "user_patterns": data.get("user_patterns", ""),
                "improvement_suggestions": data.get("improvement_suggestions", []),
                "skill_gaps": data.get("skill_gaps", []),
                "confidence_adjustment": data.get("confidence_adjustment", 0.0),
                "next_goals": data.get("next_goals", []),
                "reflected_at": datetime.now().isoformat(),
            }
        except Exception as e:
            self.logger.warning(f"[AgentReflector] 解析失败: {e}")
            return {
                "agent_name": agent_name,
                "summary": f"反思解析失败: {str(e)}",
                "strengths": [],
                "weaknesses": [],
                "reflected_at": datetime.now().isoformat(),
            }

    def _save_reflection(self, agent_name: str, reflection: Dict):
        """保存反思到 Agent 私有空间"""
        if self.memory_ns:
            reflections = self.memory_ns.load_private(
                agent_name, "reflections.json", default=[]
            )
            reflections.append(reflection)
            # 保留最近 20 条
            reflections = reflections[-20:]
            self.memory_ns.save_private(agent_name, reflections, "reflections.json")
        else:
            # 仅保存在内存
            if not hasattr(self, '_memory_reflections'):
                self._memory_reflections = {}
            if agent_name not in self._memory_reflections:
                self._memory_reflections[agent_name] = []
            self._memory_reflections[agent_name].append(reflection)

    def get_reflections(self, agent_name: str) -> List[Dict]:
        """获取 Agent 的反思历史"""
        if self.memory_ns:
            return self.memory_ns.load_private(agent_name, "reflections.json", default=[])
        return getattr(self, '_memory_reflections', {}).get(agent_name, [])

    def get_latest_reflection(self, agent_name: str) -> Optional[Dict]:
        """获取最新的反思"""
        reflections = self.get_reflections(agent_name)
        return reflections[-1] if reflections else None
