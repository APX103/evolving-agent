"""
主动学习引擎 v3.0
- 增量提取：每轮只处理新增内容，不用等 /bye
- 结构化提取：JSON Schema 约束，带 confidence
- RAG 去重：提取前先召回已有知识
- LLM-as-Judge 质量过滤
- 支持知识图谱三元组
"""
from typing import Dict, List, Optional
from datetime import datetime

from pydantic import TypeAdapter

from agent.llm.base import LLMClient
from agent.memory import MemoryManager
from agent.quality_judge import QualityJudge
from agent.knowledge_graph import Triple
from agent.structured_output import ExtractedKnowledgeItem, StructuredOutputExtractor


# ── Few-shot 示例（结构化版本） ──
_STRUCTURED_FEW_SHOT = """
示例输出格式:
[
  {
    "subject": "用户",
    "predicate": "职业",
    "object": "前端开发工程师",
    "temporal_state": "current",
    "confidence": 0.95,
    "content": "用户是前端开发工程师"
  },
  {
    "subject": "用户",
    "predicate": "沟通偏好",
    "object": "简洁直接",
    "temporal_state": "current",
    "confidence": 0.88,
    "content": "用户喜欢简洁直接的回答，讨厌啰嗦"
  },
  {
    "subject": "用户",
    "predicate": "技术栈",
    "object": "React, TypeScript",
    "temporal_state": "current",
    "confidence": 0.92,
    "content": "用户常用 React 和 TypeScript"
  }
]
注意：
- temporal_state 只能是 current / past / planned / negated
- confidence 根据原文明确程度给 0-1 分
- 只提取用户明确说过的信息，不要猜测
"""

_KNOWLEDGE_FEW_SHOT = """
示例输出格式:
[
  {
    "subject": "事实",
    "predicate": "关于",
    "object": "Python GIL",
    "temporal_state": "current",
    "confidence": 0.9,
    "category": "fact",
    "content": "Python 的 GIL 会限制多线程 CPU 利用率"
  },
  {
    "subject": "概念",
    "predicate": "关于",
    "object": "LLM 上下文窗口",
    "temporal_state": "current",
    "confidence": 0.85,
    "category": "concept",
    "content": "LLM 的上下文窗口是指单次可处理的最大 token 数"
  },
  {
    "subject": "用户",
    "predicate": "偏好",
    "object": "拆分步骤提问",
    "temporal_state": "current",
    "confidence": 0.8,
    "category": "preference",
    "content": "用户喜欢把复杂问题拆成步骤来问"
  }
]
"""

_LESSON_FEW_SHOT = """
示例输出格式:
[
  {
    "category": "success",
    "content": "用户表扬了我给的代码示例清晰",
    "confidence": 0.95
  },
  {
    "category": "failure",
    "content": "我推荐了 pandas 但用户说项目不能用重型依赖",
    "confidence": 0.9
  },
  {
    "category": "improvement",
    "content": "先问用户的技术栈再推荐方案",
    "confidence": 0.85
  }
]
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
    def __init__(self, llm_client: LLMClient, memory: MemoryManager):
        self.llm_client = llm_client
        self.memory = memory
        self.quality_judge = QualityJudge(llm_client)

    # ── 增量学习接口（每轮调用，不用等 /bye） ──
    def learn_from_turn(self, user_input: str, assistant_response: str) -> Dict:
        """
        单轮增量学习
        提取新增知识，RAG 去重后入库
        """
        if not user_input.strip():
            return {"learned": False, "reason": "空输入"}

        # 1. RAG 召回已有知识
        existing = self.memory.search_knowledge(query=user_input, limit=5)
        existing_context = "\n".join([f"- [{k['category']}] {k['content']}" for k in existing])

        # 2. 结构化提取（增量）
        extracted = self._extract_incremental(user_input, assistant_response, existing_context)

        # 3. 质量过滤
        source_text = f"用户: {user_input}\n助手: {assistant_response}"
        filtered = self.quality_judge.filter_valid(extracted, source_text)

        # 4. 应用入库
        applied = self._apply_to_memory(filtered)

        return {
            "learned": len(filtered) > 0,
            "new_knowledge": len(applied.get("knowledge", [])),
            "profile_updates": len(applied.get("profile", [])),
            "merged_count": applied.get("merged", 0),
            "details": applied
        }

    def _extract_incremental(self, user_input: str, assistant_response: str, existing_context: str) -> List[Dict]:
        """增量提取：只提取与已有知识不重复的新内容"""
        prompt = f"""分析以下单轮对话，提取新的知识和信息。

【我已知道的相关信息】
{existing_context if existing_context else "（暂无）"}

【当前对话】
用户: {user_input}
助手: {assistant_response}

【要求】
1. 只提取**与上述已知信息不重复**的新知识
2. 用结构化 JSON 输出，包含 subject / predicate / object / temporal_state / confidence / category / content
3. 如果没有新知识，返回空数组 []

{_KNOWLEDGE_FEW_SHOT}

只返回 JSON 数组，不要其他文字。"""

        extractor = StructuredOutputExtractor(self.llm_client)
        items = extractor.extract_list(ExtractedKnowledgeItem, prompt)
        if items:
            return [item.model_dump() for item in items]
        # fallback: 保留旧的手动解析
        return self._parse_json_list(self.llm_client.quick_chat(prompt))

    # ── 会话级学习（保留，用于 /bye 后的深度复盘） ──
    def learn_from_session(self, messages: List[Dict]) -> Dict:
        if len(messages) < 2:
            return {"learned": False, "reason": "对话太短"}

        conversation_text = self._format_conversation(messages)

        # 1. 判断对话类型
        strategy = self._detect_strategy(conversation_text)

        # 2. 结构化提取
        profile_updates = self._extract_profile_structured(conversation_text)
        new_knowledge = self._extract_knowledge_structured(conversation_text, strategy)
        lessons = self._extract_lessons_structured(conversation_text)

        # 3. 质量过滤
        all_extracted = profile_updates + new_knowledge + lessons
        source_text = conversation_text[:4000]
        filtered = self.quality_judge.filter_valid(all_extracted, source_text)

        # 4. 应用 + 去重感知
        applied = self._apply_to_memory(filtered)

        return {
            "learned": True,
            "strategy": strategy,
            "profile_updates": len([x for x in applied.get("profile", [])]),
            "new_knowledge": len([x for x in applied.get("knowledge", [])]),
            "lessons": len([x for x in applied.get("lessons", [])]),
            "merged_count": applied.get("merged", 0),
            "details": applied
        }

    def _detect_strategy(self, conversation: str) -> str:
        lowered = conversation.lower()

        correction_signals = ["不对", "错了", "不是这样的", "纠正", "应该是", "其实", "你误解", "不是这个意思"]
        if any(s in lowered for s in correction_signals):
            return "corrected"

        tech_signals = ["代码", "报错", "bug", "api", "框架", "库", "import", "docker", "部署", "服务器", "数据库"]
        tech_count = sum(1 for s in tech_signals if s in lowered)

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

    # ── 结构化提取方法 ──
    def _extract_profile_structured(self, conversation: str) -> List[Dict]:
        prompt = f"""分析以下对话，提取关于用户的明确信息。

{_STRUCTURED_FEW_SHOT}

对话：
{conversation}

只返回 JSON 数组，不要其他文字。如果没有明确信息，返回 []。
"""
        return self._parse_json_list(self.llm_client.quick_chat(prompt))

    def _extract_knowledge_structured(self, conversation: str, strategy: str) -> List[Dict]:
        strategy_hint = _STRATEGY_MAP.get(strategy, _STRATEGY_MAP["mixed"])

        prompt = f"""分析以下对话，提取新的知识和信息。

策略指引：{strategy_hint}

{_KNOWLEDGE_FEW_SHOT}

对话：
{conversation}

只返回 JSON 数组，不要其他文字。如果没有新知识，返回 []。
"""
        return self._parse_json_list(self.llm_client.quick_chat(prompt))

    def _extract_lessons_structured(self, conversation: str) -> List[Dict]:
        prompt = f"""分析以下对话，评估助手的表现，提取经验教训。

{_LESSON_FEW_SHOT}

对话：
{conversation}

只返回 JSON 数组，不要其他文字。如果没有明显经验教训，返回 []。
"""
        return self._parse_json_list(self.llm_client.quick_chat(prompt))

    # ── 应用到记忆 ──
    def _apply_to_memory(self, items: List[Dict]) -> Dict:
        applied = {"profile": [], "knowledge": [], "lessons": [], "merged": 0, "triples": []}

        for item in items:
            # 尝试存为知识图谱三元组
            triple = self._dict_to_triple(item)
            if triple and self.memory.knowledge_graph:
                added = self.memory.knowledge_graph.add(triple)
                if added:
                    applied["triples"].append(triple.to_dict())

            # 画像更新
            if item.get("category") == "profile" or item.get("predicate") in ("职业", "名字", "身份"):
                key = item.get("predicate", item.get("key", "info"))
                value = item.get("object", item.get("value", item.get("content", "")))
                if key and value:
                    self.memory.update_profile(key, value)
                    applied["profile"].append(item)

            # 知识入库（去重合并内置）
            elif "content" in item:
                result = self.memory.add_knowledge(
                    category=item.get("category", "fact"),
                    content=item["content"],
                    source="session_learning"
                )
                if result["action"] == "merged":
                    applied["merged"] += 1
                else:
                    applied["knowledge"].append(item)

            # 经验教训
            elif item.get("category") in ("success", "failure", "improvement"):
                self.memory.add_knowledge(
                    category="lesson",
                    content=f"[{item['category']}] {item['content']}",
                    source="session_reflection"
                )
                applied["lessons"].append(item)

        return applied

    def _dict_to_triple(self, item: Dict) -> Optional[Triple]:
        """把结构化 dict 转为 Triple"""
        try:
            return Triple(
                subject=item.get("subject", "用户"),
                predicate=item.get("predicate", "知道"),
                object=item.get("object", item.get("content", "")[:50]),
                temporal_state=item.get("temporal_state", "current"),
                confidence=item.get("_confidence", item.get("confidence", 0.8)),
                source=item.get("source", "learner"),
                created_at=datetime.now().isoformat(),
                updated_at=datetime.now().isoformat(),
            )
        except Exception:
            return None

    # ── JSON 解析工具 ──
    def _parse_json_list(self, text: str) -> List[Dict]:
        try:
            cleaned = LLMClient._clean_json(text)
            adapter = TypeAdapter(List[ExtractedKnowledgeItem])
            items = adapter.validate_json(cleaned)
            return [item.model_dump() for item in items]
        except Exception:
            return []
