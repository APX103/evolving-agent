"""
主动学习引擎 (v2)
Few-shot 示例 + 分层学习策略 + 去重感知
"""
import json
from typing import List, Dict
from agent.kimi_client import KimiClient
from agent.memory import MemoryManager


# ── Few-shot 示例 ──
_PROFILE_FEW_SHOT = """
示例输出格式:
[
  {"key": "用户专业", "value": "前端开发工程师"},
  {"key": "沟通偏好", "value": "喜欢简洁直接的回答，讨厌啰嗦"},
  {"key": "常用工具", "value": "React, TypeScript, VS Code"},
  {"key": "名字", "value": "小明"}
]
注意：只提取用户明确说过的信息，不要猜测。
"""

_KNOWLEDGE_FEW_SHOT = """
示例输出格式:
[
  {"category": "fact", "content": "Python 的 GIL 会限制多线程 CPU 利用率"},
  {"category": "concept", "content": "LLM 的上下文窗口是指单次可处理的最大 token 数"},
  {"category": "preference", "content": "用户喜欢把复杂问题拆成步骤来问"},
  {"category": "context", "content": "用户正在做一个物联网数据采集项目"}
]
注意：只提取对话中新出现的信息。如果用户纠正了你，category 用 "lesson"。
"""

_LESSON_FEW_SHOT = """
示例输出格式:
{
  "successes": ["用户表扬了我给的代码示例清晰"],
  "failures": ["我推荐了 pandas 但用户说项目不能用重型依赖", "我误解了用户的 docker 问题，他其实是网络问题"],
  "improvements": ["先问用户的技术栈再推荐方案", "遇到部署问题先确认环境细节"]
}
"""

# ── 分层学习策略 ──
_STRATEGY_MAP = {
    "casual": "这是闲聊对话，重点记录用户的偏好、性格、兴趣，忽略技术细节。",
    "technical": "这是技术讨论，重点记录概念、事实、解决方案，以及用户纠正你的错误。",
    "corrected": "对话中你明显被用户纠正了，重点记录正确的做法和用户的纠正点。",
    "planning": "用户在规划/设计某事，重点记录目标、约束条件、用户的选择偏好。",
    "mixed": "混合对话，全面提取：用户偏好、新知识、技术概念、纠正教训。"
}


class Learner:
    def __init__(self, client: KimiClient, memory: MemoryManager):
        self.client = client
        self.memory = memory
    
    def learn_from_session(self, messages: List[Dict]) -> Dict:
        if len(messages) < 2:
            return {"learned": False, "reason": "对话太短"}
        
        conversation_text = self._format_conversation(messages)
        
        # 1. 判断对话类型，选择学习策略
        strategy = self._detect_strategy(conversation_text)
        
        # 2. 并行提取（串行调用，但逻辑分层）
        profile_updates = self._extract_profile(conversation_text)
        new_knowledge = self._extract_knowledge(conversation_text, strategy)
        lessons = self._extract_lessons(conversation_text)
        
        # 3. 应用 + 去重感知
        applied = self._apply_to_memory(profile_updates, new_knowledge, lessons)
        
        # 4. 返回摘要
        return {
            "learned": True,
            "strategy": strategy,
            "profile_updates": len(profile_updates),
            "new_knowledge": len(new_knowledge),
            "lessons": len(lessons.get("successes", [])) + len(lessons.get("failures", [])),
            "merged_count": applied.get("merged", 0),
            "details": applied
        }
    
    def _detect_strategy(self, conversation: str) -> str:
        """
        快速判断对话类型，决定学习重点
        """
        lowered = conversation.lower()
        
        # 纠正信号
        correction_signals = ["不对", "错了", "不是这样的", "纠正", "应该是", "其实", "你误解", "不是这个意思"]
        if any(s in lowered for s in correction_signals):
            return "corrected"
        
        # 技术信号
        tech_signals = ["代码", "报错", "bug", "api", "框架", "库", "import", "docker", "部署", "服务器", "数据库"]
        tech_count = sum(1 for s in tech_signals if s in lowered)
        
        # 规划信号
        planning_signals = ["想做一个", "计划", "方案", "设计", "架构", "怎么实现", "第一步"]
        planning_count = sum(1 for s in planning_signals if s in lowered)
        
        if tech_count >= 3 and planning_count >= 2:
            return "mixed"
        elif tech_count >= 3:
            return "technical"
        elif planning_count >= 2:
            return "planning"
        else:
            return "casual"
    
    def _format_conversation(self, messages: List[Dict]) -> str:
        lines = []
        for msg in messages:
            role = "用户" if msg["role"] == "user" else "助手"
            content = msg["content"].replace("\n", " ")
            lines.append(f"{role}: {content}")
        return "\n".join(lines)
    
    def _extract_profile(self, conversation: str) -> List[Dict]:
        prompt = f"""分析以下对话，提取关于用户的明确信息。

{_PROFILE_FEW_SHOT}

对话：
{conversation}

只返回 JSON 数组，不要其他文字。如果没有明确信息，返回 []。
"""
        return self._parse_json_list(self.client.quick_chat(prompt))
    
    def _extract_knowledge(self, conversation: str, strategy: str) -> List[Dict]:
        strategy_hint = _STRATEGY_MAP.get(strategy, _STRATEGY_MAP["mixed"])
        
        prompt = f"""分析以下对话，提取新的知识和信息。

策略指引：{strategy_hint}

{_KNOWLEDGE_FEW_SHOT}

对话：
{conversation}

只返回 JSON 数组，不要其他文字。如果没有新知识，返回 []。
"""
        return self._parse_json_list(self.client.quick_chat(prompt))
    
    def _extract_lessons(self, conversation: str) -> Dict:
        prompt = f"""分析以下对话，评估助手的表现，提取经验教训。

{_LESSON_FEW_SHOT}

对话：
{conversation}

只返回 JSON，不要其他文字。如果没有明显经验教训，返回空字段。
"""
        return self._parse_json_dict(self.client.quick_chat(prompt))
    
    def _apply_to_memory(self, profile_updates: List[Dict], knowledge: List[Dict], lessons: Dict) -> Dict:
        applied = {"profile": [], "knowledge": [], "lessons": [], "merged": 0}
        
        # 应用画像
        for item in profile_updates:
            if "key" in item and "value" in item:
                self.memory.update_profile(item["key"], item["value"])
                applied["profile"].append(item)
        
        # 应用新知识（去重合并内置）
        for item in knowledge:
            if "category" in item and "content" in item:
                result = self.memory.add_knowledge(
                    category=item["category"],
                    content=item["content"],
                    source="session_learning"
                )
                if result["action"] == "merged":
                    applied["merged"] += 1
                else:
                    applied["knowledge"].append(item)
        
        # 应用经验教训
        for category in ["successes", "failures", "improvements"]:
            for lesson in lessons.get(category, []):
                self.memory.add_knowledge(
                    category="lesson",
                    content=f"[{category}] {lesson}",
                    source="session_reflection"
                )
                applied["lessons"].append(lesson)
        
        return applied
    
    # ── JSON 解析工具 ──
    def _clean_json(self, text: str) -> str:
        text = text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        return text.strip()
    
    def _parse_json_list(self, text: str) -> List[Dict]:
        try:
            data = json.loads(self._clean_json(text))
            return data if isinstance(data, list) else []
        except Exception:
            return []
    
    def _parse_json_dict(self, text: str) -> Dict:
        try:
            data = json.loads(self._clean_json(text))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
