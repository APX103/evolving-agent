"""
反思进化模块 (v2.3)
自我批评式反思 + 产出可执行规则写入 ProceduralMemory
形成真正的"反思-行动"闭环
"""
import logging
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from agent.llm.base import LLMClient
from agent.memory.memory_module import MemoryManager

logger = logging.getLogger(__name__)


class ProceduralRule(BaseModel):
    pattern: str = ""
    action: str = ""
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)


class ReflectionSchema(BaseModel):
    summary: str = ""
    strengths: List[str] = []
    weaknesses: List[str] = []
    missed_opportunities: List[str] = []
    user_patterns: str = ""
    personality_update: str = ""
    growth_goals: List[str] = []
    confidence_change: str = ""
    procedural_rules: List[ProceduralRule] = []


# ── 反思 few-shot ──
_REFLECTION_SYSTEM = """你是一位严厉但公正的 AI 导师。
你的任务是让这个 AI Agent 直面自己的问题，找出真正的弱点，而不是自我安慰。
要求：
- 诚实指出 Agent 的不足之处，不要粉饰
- 识别用户反复出现的模式和未被满足的需求
- 给出具体、可执行的改进方向，不要空话
- 反思要简洁有力，像一位资深工程师的 code review
- 产出具体的"行为规则"，可直接写入规则库
"""

_REFLECTION_FORMAT = """以 JSON 输出：
{
  "summary": "一句锐利的核心发现",
  "strengths": ["真正做得好的地方（最多2条，要具体）"],
  "weaknesses": ["必须改进的弱点（至少2条，要尖锐）"],
  "missed_opportunities": ["用户暗示过但没被捕捉到的需求"],
  "user_patterns": "用户行为的深层模式洞察",
  "personality_update": "基于反思，Agent 应该在性格/风格上做出的具体调整",
  "growth_goals": ["接下来3个最重要的提升目标"],
  "confidence_change": "建议的自信度调整（+0.1 更自信 / -0.1 更谨慎）",
  "procedural_rules": [
    {"pattern": "用户表现出XX时", "action": "我应该YY", "confidence": 0.8}
  ]
}
procedural_rules 必须是具体的"当...时，我应该..."行为规则，confidence 0.0-1.0。
只返回 JSON，不要废话。
"""


class Reflector:
    def __init__(
        self,
        llm_client: LLMClient,
        memory: MemoryManager,
        procedural_memory=None,
    ):
        self.llm_client = llm_client
        self.memory = memory
        self.procedural_memory = procedural_memory

    def should_reflect(self, threshold: int = 5) -> bool:
        return self.memory.session_count > 0 and self.memory.session_count % threshold == 0

    def reflect(self) -> Dict:
        """执行深度自我批评式反思，产出可执行规则"""
        # 收集素材
        recent_knowledge = self.memory.search_knowledge(category="", limit=25)
        profile = self.memory.get_profile()
        reflections = self.memory.reflections

        prompt = self._build_reflection_prompt(recent_knowledge, profile, reflections)

        response = self.llm_client.quick_chat(
            prompt,
            system=_REFLECTION_SYSTEM
        )

        reflection = self._parse_reflection(response)

        # 保存反思到记忆
        self.memory.add_reflection(reflection)

        # 更新 profile
        if reflection.get("personality_update"):
            self.memory.update_profile("agent_personality", reflection["personality_update"])

        # ── 核心改进：产出可执行规则写入 ProceduralMemory ──
        rules_added = 0
        if self.procedural_memory and reflection.get("procedural_rules"):
            for rule in reflection["procedural_rules"]:
                try:
                    pattern = rule.get("pattern", "").strip()
                    action = rule.get("action", "").strip()
                    confidence = float(rule.get("confidence", 0.7))
                    if pattern and action:
                        self.procedural_memory.add_rule(
                            pattern=pattern,
                            action=action,
                            confidence=min(1.0, max(0.1, confidence)),
                        )
                        rules_added += 1
                except Exception as e:
                    logger.debug(f"[Reflector] 规则写入失败: {e}")
            if rules_added > 0:
                logger.info(f"[Reflector] 产出 {rules_added} 条行为规则写入 ProceduralMemory")

        # 清理旧知识
        self.memory.cleanup_stale_knowledge(days=60, min_access=1)

        reflection["rules_added"] = rules_added
        return reflection

    def _build_reflection_prompt(self, knowledge: List[Dict], profile: Dict, past_reflections: List[Dict]) -> str:

        knowledge_text = "\n".join([
            f"- [{k['category']}] {k['content']}"
            for k in knowledge[:20]
        ]) if knowledge else "（暂无知识记录）"

        profile_text = "\n".join([
            f"- {k}: {v}"
            for k, v in list(profile.items())[:10]
        ]) if profile else "（暂无用户画像）"

        past_summary = ""
        if past_reflections:
            last = past_reflections[-1]
            past_summary = f"\n上次反思摘要：{last.get('summary', '无')}\n上次目标：{', '.join(last.get('growth_goals', []))}"

        return f"""基于以下信息，对 AI Agent 进行一次不留情面的深度反思。

【积累的知识】
{knowledge_text}

【用户画像】
{profile_text}
{past_summary}

【反思要求】
1. 上次定的目标实现了吗？为什么没实现？
2. 用户有没有反复提同样的需求但你一直没满足？
3. 你有没有过度自信或过度谨慎的时候？
4. 用户最不耐烦/最满意的时刻分别是什么？
5. 产出 2-3 条具体的"当用户...时，我应该..."行为规则

{_REFLECTION_FORMAT}
"""

    def _parse_reflection(self, response: str) -> Dict:
        try:
            cleaned = LLMClient._clean_json(response)
            schema = ReflectionSchema.model_validate_json(cleaned)
            return schema.model_dump()
        except Exception as e:
            return {
                "summary": f"反思解析失败: {str(e)}",
                "strengths": [],
                "weaknesses": [],
                "missed_opportunities": [],
                "user_patterns": "",
                "personality_update": "",
                "growth_goals": [],
                "confidence_change": "",
                "procedural_rules": [],
            }
