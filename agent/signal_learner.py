"""
实时信号学习
对话中检测到特定信号词时，立即触发迷你学习
不用等 /bye 会话结束
"""
import re
from typing import Dict, List, Optional

from agent.events import EventBus, default_bus
from agent.llm.base import LLMClient
from agent.memory import MemoryManager


# ── 信号模式定义 ──
SIGNAL_PATTERNS = {
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
        "prompt_template": "提取用户要求记住的关键信息，只保留核心事实: {}"
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
        "prompt_template": "提取用户的偏好，简短描述: {}"
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
        "prompt_template": "提取用户的负面偏好/禁忌，简短描述: {}"
    },
    "identity": {
        "patterns": [
            r"我叫(.+)",
            r"我的名字是(.+)",
            r"我是做(.+)的",
            r"我的工作[是]?(.+)",
            # 排除"我是说/想/觉得"等常见前缀
            r"我是(?!说|想|觉得|认为|指|在|要|会|可以|可能|已经|就是)(.+)",
        ],
        "action": "update_profile",
        "key_map": {
            r"我叫|我的名字是": "name",
            r"我是做|我的工作[是]?": "职业",
            r"我是": "身份",
        },
        "prompt_template": "提取用户的身份信息，简短描述: {}"
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
        "prompt_template": "提取用户的纠正内容，记录正确的做法: {}"
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
    实时信号学习者：对话中即时检测信号，触发快速学习
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

    def scan_and_learn(self, user_input: str, assistant_response: str = "") -> List[Dict]:
        """
        扫描用户输入，检测所有信号，立即学习
        返回处理日志
        """
        logs = []

        for signal_type, config in SIGNAL_PATTERNS.items():
            # 先检测是否匹配
            match = self._match_patterns(user_input, config.get("patterns", []))
            if not match:
                continue

            extracted = match.group(1).strip() if match.lastindex else user_input

            # 执行对应动作
            result = self._execute_action(signal_type, config, extracted, user_input)
            if result:
                log = {
                    "signal": signal_type,
                    "extracted": extracted,
                    "action": config["action"],
                    "result": result
                }
                logs.append(log)
                self.event_bus.publish("signal.learned", log)

        # 检测情感反馈（不用 regex，用关键词）
        feedback = self._detect_feedback(user_input)
        if feedback:
            self.personality.adapt_from_feedback(feedback)
            logs.append({"signal": "feedback", "type": feedback, "action": "personality_adjust"})

        return logs

    def _match_patterns(self, text: str, patterns: List[str]) -> Optional[re.Match]:
        for p in patterns:
            match = re.search(p, text, re.IGNORECASE)
            if match:
                return match
        return None

    def _execute_action(self, signal_type: str, config: Dict, extracted: str, full_input: str) -> Optional[str]:
        action = config["action"]

        if action == "add_knowledge":
            # 使用 LLM 精炼提取内容
            prompt = config["prompt_template"].format(extracted)
            refined = self.llm_client.quick_chat(prompt, system="你只输出精炼后的事实，不要解释，不要多余文字。")
            refined = refined.strip().strip("\"'")

            if len(refined) > 5:
                result = self.memory.add_knowledge(
                    category=config.get("category", "fact"),
                    content=refined,
                    source=f"signal:{signal_type}"
                )
                return result["action"]

        elif action == "update_profile":
            # 尝试确定 key
            key = self._determine_profile_key(config, full_input)
            if key:
                refined = self.llm_client.quick_chat(
                    f"提取用户的身份信息，只输出简短值: {extracted}",
                    system="只输出简短的事实值，不要解释。"
                ).strip().strip("\"'")
                self.memory.update_profile(key, refined)
                return f"profile:{key}={refined}"

        elif action == "set_working":
            self.memory.set_working(config["key"], config["value"])
            return f"working:{config['key']}={config['value']}"

        elif action == "feedback_positive":
            self.personality.adapt_from_feedback("positive")
            return "personality:+confidence"

        elif action == "feedback_negative":
            self.personality.adapt_from_feedback("negative")
            return "personality:-confidence"

        return None

    def _determine_profile_key(self, config: Dict, text: str) -> Optional[str]:
        key_map = config.get("key_map", {})
        for pattern, key in key_map.items():
            if re.search(pattern, text):
                return key
        return "identity"

    def _detect_feedback(self, text: str) -> Optional[str]:
        """
        简单情感检测
        """
        lowered = text.lower()

        # 积极信号
        positive_signals = ["谢谢", "感谢", "不错", "很好", "完美", "厉害", "棒", "给力", "学到了", "有帮助"]
        if any(s in lowered for s in positive_signals):
            return "positive"

        # 热情信号
        enthusiasm_signals = ["哇", "太棒了", " awesome", " amazing", "喜欢", "太喜欢了"]
        if any(s in lowered for s in enthusiasm_signals):
            return "enthusiasm"

        # 纠正信号
        correction_signals = ["不对", "错了", "不是这样", "纠正", "其实", "应该是"]
        if any(s in lowered for s in correction_signals):
            return "correction"

        # 无聊/不耐烦
        boredom_signals = ["无聊", "没意思", "太慢了", "能不能快点", "说重点"]
        if any(s in lowered for s in boredom_signals):
            return "boredom"

        # 负面
        negative_signals = ["烦", "气", "无语", "失望", "没用", "不行", "差"]
        if any(s in lowered for s in negative_signals):
            return "negative"

        return None

    def on_turn_complete(self, user_input: str, assistant_response: str):
        """
        每轮对话完成后调用，做实时信号学习
        """
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
