"""
实时信号学习 v2.0
- 新增语义信号检测（Embedding 替代正则）
- 新增 LLM-as-Judge 质量过滤
- 支持结构化三元组提取
"""
import re
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from agent.events import EventBus, default_bus
from agent.llm.base import LLMClient
from agent.memory import MemoryManager
from agent.quality_judge import QualityJudge
from agent.semantic_detector import SemanticSignalDetector
from agent.knowledge_graph import Triple
from agent.structured_output import ExtractedKnowledgeItem, StructuredOutputExtractor


class SignalParseResult(BaseModel):
    content: str = ""
    category: str = ""
    subject: str = "用户"
    predicate: str = "知道"
    object: str = ""
    temporal_state: str = "current"
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)


# ── 保留正则作为 fallback ──
REGEX_PATTERNS = {
    "remember": {
        "patterns": [
            r"请记住[，,:：]?\s*(.+)",
            r"记住[，,:：]?\s*(.+)",
            r"别忘了[，,:：]?\s*(.+)",
            r"以后记住[，,:：]?\s*(.+)",
            r"记一下[，,:：]?\s*(.+)",
        ],
        "action": "add_knowledge",
        "category": "fact",
    },
    "preference_positive": {
        "patterns": [
            r"我喜欢(.+)",
            r"我爱(.+)",
            r"我偏好(.+)",
            r"我习惯(.+)",
            r"(.+)挺?好[的]?",
        ],
        "action": "add_knowledge",
        "category": "preference",
    },
    "preference_negative": {
        "patterns": [
            r"我讨厌(.+)",
            r"我不喜欢(.+)",
            r"别(.+)",
            r"以后别(.+)",
            r"(.+)不好",
            r"(.+)不行",
        ],
        "action": "add_knowledge",
        "category": "preference",
    },
    "identity": {
        "patterns": [
            r"我叫(.+)",
            r"我的名字是(.+)",
            r"我是做(.+)的",
            r"我的工作[是]?(.+)",
            r"我是(?!说|想|觉得|认为|指|在|要|会|可以|可能|已经|就是)(.+)",
        ],
        "action": "update_profile",
    },
    "correction": {
        "patterns": [
            r"不对[，,。.]?(.+)",
            r"错了[，,。.]?(.+)",
            r"应该是(.+)",
            r"正确的是(.+)",
            r"你误解了[，,:：]?(.+)",
        ],
        "action": "add_knowledge",
        "category": "lesson",
    },
    "urgency": {
        "patterns": [
            r"紧急[！!.。]",
            r"快点[！!.。]",
            r"马上[！!.。]",
            r"很急[！!.。]",
        ],
        "action": "set_working",
        "key": "urgency",
        "value": True,
    },
    "gratitude": {
        "patterns": [
            r"谢[谢了]?[！!.。]",
            r"感谢[！!.。]",
            r"帮大忙[了]?[！!.。]",
        ],
        "action": "feedback_positive",
    },
    "frustration": {
        "patterns": [
            r"烦死[了]?[！!.。]",
            r"气死[了]?[！!.。]",
            r"无语[了]?[！!.。]",
            r"麻烦[！!.。]",
            r"搞不定[！!.。]",
        ],
        "action": "feedback_negative",
    },
}


class SignalLearner:
    """
    实时信号学习者 v2.0
    融合语义检测 + 正则 fallback + 质量过滤
    """

    def __init__(
        self,
        llm_client: LLMClient,
        memory: MemoryManager,
        personality,
        event_bus: Optional[EventBus] = None,
    ):
        self.llm_client = llm_client
        self.memory = memory
        self.personality = personality
        self.event_bus = event_bus or default_bus

        # 语义检测器
        self.semantic_detector = SemanticSignalDetector(llm_client)
        # 质量过滤器
        self.quality_judge = QualityJudge(llm_client)

    def scan_and_learn(self, user_input: str, assistant_response: str = "") -> List[Dict]:
        """
        扫描用户输入，检测所有信号，立即学习
        返回处理日志
        """
        logs = []

        # ── 第一层：语义检测（优先） ──
        semantic_result = self.semantic_detector.detect(user_input)
        if semantic_result:
            intent_name, sim = semantic_result
            logs.append({
                "signal": intent_name,
                "method": "semantic",
                "similarity": sim,
            })
            # 根据意图类型执行对应动作
            result = self._execute_by_intent(intent_name, user_input)
            if result:
                logs[-1]["result"] = result
                self.event_bus.publish("signal.learned", logs[-1])

        # ── 第二层：正则 fallback ──
        regex_hits = self._regex_scan(user_input)
        for hit in regex_hits:
            # 避免与语义检测重复（如果语义已命中同类型，跳过）
            if semantic_result and semantic_result[0] == hit["signal"]:
                continue
            result = self._execute_by_regex(hit)
            if result:
                hit["result"] = result
                logs.append(hit)
                self.event_bus.publish("signal.learned", hit)

        # ── 情感反馈检测（保持原有逻辑） ──
        feedback = self._detect_feedback(user_input)
        if feedback:
            self.personality.adapt_from_feedback(feedback)
            logs.append({"signal": "feedback", "type": feedback, "action": "personality_adjust"})

        return logs

    def _execute_by_intent(self, intent_name: str, full_input: str) -> Optional[str]:
        """根据语义意图执行动作"""
        # 映射意图到配置
        config_map = {
            "remember": {"action": "add_knowledge", "category": "fact"},
            "preference_positive": {"action": "add_knowledge", "category": "preference"},
            "preference_negative": {"action": "add_knowledge", "category": "preference"},
            "identity": {"action": "update_profile"},
            "correction": {"action": "add_knowledge", "category": "lesson"},
            "urgency": {"action": "set_working", "key": "urgency", "value": True},
            "gratitude": {"action": "feedback_positive"},
            "frustration": {"action": "feedback_negative"},
        }
        config = config_map.get(intent_name)
        if not config:
            return None

        return self._execute_action(intent_name, config, full_input, full_input)

    def _regex_scan(self, text: str) -> List[Dict]:
        """正则扫描，返回所有命中"""
        hits = []
        for signal_type, config in REGEX_PATTERNS.items():
            match = self._match_patterns(text, config.get("patterns", []))
            if match:
                extracted = match.group(1).strip() if match.lastindex else text
                hits.append({
                    "signal": signal_type,
                    "extracted": extracted,
                    "action": config["action"],
                    "method": "regex",
                })
        return hits

    def _match_patterns(self, text: str, patterns: List[str]) -> Optional[re.Match]:
        for p in patterns:
            match = re.search(p, text, re.IGNORECASE)
            if match:
                return match
        return None

    def _execute_by_regex(self, hit: Dict) -> Optional[str]:
        """执行正则命中结果"""
        config = REGEX_PATTERNS.get(hit["signal"], {})
        return self._execute_action(hit["signal"], config, hit["extracted"], hit.get("full_input", ""))

    def _execute_action(self, signal_type: str, config: Dict, extracted: str, full_input: str) -> Optional[str]:
        action = config.get("action")

        if action == "add_knowledge":
            # 结构化提取 + 质量过滤（使用 Pydantic 强制校验）
            prompt = self._build_extraction_prompt(signal_type, extracted)
            extractor = StructuredOutputExtractor(self.llm_client)
            items = extractor.extract_list(ExtractedKnowledgeItem, prompt, system="你只输出 JSON，不要解释。")

            if items:
                structured_list = [item.model_dump() for item in items]
            else:
                # fallback: 手动解析
                refined = self.llm_client.quick_chat(prompt, system="你只输出 JSON，不要解释。").strip().strip("\"'")
                if len(refined) <= 5:
                    return None
                structured_list = [self._try_parse_structured(refined, config.get("category", "fact"))]

            # 质量过滤
            source_text = f"用户说: {full_input}"
            filtered = self.quality_judge.filter_valid(structured_list, source_text)

            if filtered:
                item = filtered[0]
                # 尝试存为三元组
                triple = self._item_to_triple(item, signal_type)
                if triple and self.memory.knowledge_graph:
                    added = self.memory.knowledge_graph.add(triple)
                    if added:
                        return f"kg:{triple.predicate}:{triple.object}"

                # fallback 到传统知识库
                result = self.memory.add_knowledge(
                    category=item.get("category", "fact"),
                    content=item.get("content", extracted),
                    source=f"signal:{signal_type}"
                )
                return result["action"]
            return None

        elif action == "update_profile":
            key = self._determine_profile_key(config, full_input)
            if key:
                refined = self.llm_client.quick_chat(
                    f"提取用户的身份信息，只输出简短值: {extracted}",
                    system="只输出简短的事实值，不要解释。"
                ).strip().strip("\"'")
                self.memory.update_profile(key, refined)
                return f"profile:{key}={refined}"

        elif action == "set_working":
            self.memory.set_working(config.get("key"), config.get("value"))
            return f"working:{config['key']}={config['value']}"

        elif action == "feedback_positive":
            self.personality.adapt_from_feedback("positive")
            return "personality:+confidence"

        elif action == "feedback_negative":
            self.personality.adapt_from_feedback("negative")
            return "personality:-confidence"

        return None

    def _build_extraction_prompt(self, signal_type: str, extracted: str) -> str:
        """构建结构化提取 prompt"""
        templates = {
            "remember": f"提取用户要求记住的关键事实，返回 JSON: {{\"content\":\"...\",\"subject\":\"用户\",\"predicate\":\"知道\",\"object\":\"...\",\"temporal_state\":\"current\"}}。文本: {extracted}",
            "preference_positive": f"提取用户的正面偏好，返回 JSON: {{\"content\":\"...\",\"subject\":\"用户\",\"predicate\":\"喜欢\",\"object\":\"...\",\"temporal_state\":\"current\"}}。文本: {extracted}",
            "preference_negative": f"提取用户的负面偏好，返回 JSON: {{\"content\":\"...\",\"subject\":\"用户\",\"predicate\":\"不喜欢\",\"object\":\"...\",\"temporal_state\":\"current\"}}。文本: {extracted}",
            "correction": f"提取用户的纠正内容，返回 JSON: {{\"content\":\"...\",\"subject\":\"用户\",\"predicate\":\"纠正\",\"object\":\"...\",\"temporal_state\":\"current\"}}。文本: {extracted}",
        }
        return templates.get(signal_type, f"提取关键信息，返回 JSON: {{\"content\":\"...\"}}。文本: {extracted}")

    def _try_parse_structured(self, text: str, default_category: str) -> Dict:
        """尝试解析结构化 JSON"""
        try:
            result = SignalParseResult.model_validate_json(text)
            data = result.model_dump()
            data["category"] = default_category
            return data
        except Exception:
            return {"content": text, "category": default_category}

    def _item_to_triple(self, item: Dict, source: str) -> Optional[Triple]:
        """把结构化 item 转为 Triple"""
        from datetime import datetime
        try:
            return Triple(
                subject=item.get("subject", "用户"),
                predicate=item.get("predicate", "知道"),
                object=item.get("object", item.get("content", "")[:50]),
                temporal_state=item.get("temporal_state", "current"),
                confidence=item.get("_confidence", 0.8),
                source=source,
                created_at=datetime.now().isoformat(),
                updated_at=datetime.now().isoformat(),
            )
        except Exception:
            return None

    def _determine_profile_key(self, config: Dict, text: str) -> Optional[str]:
        key_map = config.get("key_map", {})
        for pattern, key in key_map.items():
            if re.search(pattern, text):
                return key
        return "identity"

    def _detect_feedback(self, text: str) -> Optional[str]:
        """简单情感检测"""
        lowered = text.lower()

        positive_signals = ["谢谢", "感谢", "不错", "很好", "完美", "厉害", "棒", "给力", "学到了", "有帮助"]
        if any(s in lowered for s in positive_signals):
            return "positive"

        enthusiasm_signals = ["哇", "太棒了", " awesome", " amazing", "喜欢", "太喜欢了"]
        if any(s in lowered for s in enthusiasm_signals):
            return "enthusiasm"

        correction_signals = ["不对", "错了", "不是这样", "纠正", "其实", "应该是"]
        if any(s in lowered for s in correction_signals):
            return "correction"

        boredom_signals = ["无聊", "没意思", "太慢了", "能不能快点", "说重点"]
        if any(s in lowered for s in boredom_signals):
            return "boredom"

        negative_signals = ["烦", "气", "无语", "失望", "没用", "不行", "差"]
        if any(s in lowered for s in negative_signals):
            return "negative"

        return None

    def on_turn_complete(self, user_input: str, assistant_response: str):
        """每轮对话完成后调用，做实时信号学习"""
        logs = self.scan_and_learn(user_input, assistant_response)

        # 检测用户是否在说 Agent 的回复太长/太短
        response_len = len(assistant_response)
        if response_len > 2000 and ("太长了" in user_input or "啰嗦" in user_input or "说重点" in user_input):
            self.personality.adjust("verbosity", -0.15)
            logs.append({"signal": "auto_verbosity_down", "reason": "response_too_long_and_complained"})

        if response_len < 50 and "多讲点" in user_input:
            self.personality.adjust("verbosity", +0.1)
            logs.append({"signal": "auto_verbosity_up", "reason": "response_too_short_and_asked_more"})

        return logs
