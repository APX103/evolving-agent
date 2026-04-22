"""
情绪感知引擎
分析用户话语中的情绪状态，生成适配的回应策略
不只是关键词匹配，而是用 LLM 做深度情绪分析
"""
import json
from typing import Dict, List, Optional
from datetime import datetime

from agent.kimi_client import KimiClient


# ── 情绪标签与回应策略映射 ──
EMOTION_RESPONSE_MAP = {
    "疲惫": {
        "instruction": "用户听起来很累。回复要极简温暖，不展开长篇，先给安慰。",
        "style_adjust": {"verbosity": -0.3, "warmth": +0.2, "proactive": -0.2}
    },
    "焦虑": {
        "instruction": "用户感到焦虑。先安抚情绪，再分步骤给方案，不要施压。",
        "style_adjust": {"formality": -0.2, "warmth": +0.3, "directness": +0.1}
    },
    "兴奋": {
        "instruction": "用户很兴奋！匹配这个能量，热情回应，可以开玩笑。",
        "style_adjust": {"humor": +0.2, "warmth": +0.1, "verbosity": +0.1}
    },
    "沮丧": {
        "instruction": "用户情绪低落。表达理解和陪伴，避免说教，给一点希望。",
        "style_adjust": {"warmth": +0.3, "proactive": -0.1, "technical": -0.2}
    },
    "愤怒": {
        "instruction": "用户在生气。先承认情绪，不辩解，简短回应，给空间。",
        "style_adjust": {"verbosity": -0.4, "warmth": +0.1, "directness": +0.3, "proactive": -0.3}
    },
    "敷衍": {
        "instruction": "用户有点敷衍/冷淡。不追问，简短回应，给用户空间。",
        "style_adjust": {"verbosity": -0.3, "proactive": -0.4}
    },
    "好奇": {
        "instruction": "用户充满好奇。鼓励探索，展开细节，一起思考。",
        "style_adjust": {"proactive": +0.2, "verbosity": +0.2, "technical": +0.1}
    },
    "平静": {
        "instruction": "用户状态平和。正常对话即可。",
        "style_adjust": {}
    },
    "困惑": {
        "instruction": "用户感到困惑。用类比解释，确认理解，不假设。",
        "style_adjust": {"technical": -0.2, "verbosity": +0.1, "formality": -0.2}
    },
}


class EmotionSensor:
    """
    情绪传感器：分析用户输入的情绪，提供回应策略
    """

    def __init__(self, client: KimiClient):
        self.client = client
        # 短期情绪历史（当前会话）
        self.session_emotions: List[Dict] = []

    def analyze(self, text: str, context: str = "") -> Dict:
        """
        分析用户输入的情绪状态
        返回: {"label": str, "intensity": float, "needs": [str], "subtle_signals": str}
        """
        prompt = f"""分析以下用户消息的情绪状态。

要求：
- 识别表面情绪和潜在情绪（比如"还行"可能是疲惫或敷衍）
- 注意语气词、标点、用词选择中的微妙信号
- 考虑上下文中的情绪变化

{context}

用户消息："{text}"

输出 JSON：
{{
  "label": "情绪标签（疲惫/焦虑/兴奋/沮丧/愤怒/敷衍/好奇/平静/困惑）",
  "intensity": 0.0-1.0,
  "needs": ["用户此刻需要什么（如：被倾听、解决方案、独处空间、鼓励）"],
  "subtle_signals": "观察到的微妙语气信号"
}}

只返回 JSON，不要其他文字。"""

        try:
            response = self.client.quick_chat(
                prompt,
                system="你是一位敏锐的情绪分析师，擅长从文字中读出言外之意。"
            )
            result = self._parse_json(response)

            # 校验标签
            if result.get("label") not in EMOTION_RESPONSE_MAP:
                result["label"] = "平静"

            # 确保 intensity 在范围内
            result["intensity"] = max(0.0, min(1.0, float(result.get("intensity", 0.5))))

            # 记录
            result["timestamp"] = datetime.now().isoformat()
            result["text_preview"] = text[:50]
            self.session_emotions.append(result)

            return result

        except Exception as e:
            return {
                "label": "平静",
                "intensity": 0.5,
                "needs": [],
                "subtle_signals": f"分析失败: {e}",
                "timestamp": datetime.now().isoformat()
            }

    def get_response_instruction(self, emotion_result: Dict) -> str:
        """根据情绪结果生成 LLM 回应策略指令"""
        label = emotion_result.get("label", "平静")
        intensity = emotion_result.get("intensity", 0.5)
        needs = emotion_result.get("needs", [])

        config = EMOTION_RESPONSE_MAP.get(label, EMOTION_RESPONSE_MAP["平静"])
        instruction = config["instruction"]

        # 高强烈度时加强调整
        if intensity > 0.7:
            instruction += " 情绪比较强烈，优先处理情绪，再处理事情。"

        # 用户明确的需求
        if needs:
            instruction += f" 用户此刻需要: {', '.join(needs[:3])}。"

        return instruction

    def get_style_adjustments(self, emotion_result: Dict) -> Dict[str, float]:
        """获取人格参数微调建议"""
        label = emotion_result.get("label", "平静")
        config = EMOTION_RESPONSE_MAP.get(label, EMOTION_RESPONSE_MAP["平静"])
        return config.get("style_adjust", {})

    def get_session_emotion_trend(self) -> str:
        """返回本次会话的情绪趋势摘要"""
        if not self.session_emotions:
            return ""

        # 统计各情绪出现次数
        from collections import Counter
        labels = [e["label"] for e in self.session_emotions]
        most_common = Counter(labels).most_common(1)[0][0]

        # 情绪变化
        first = self.session_emotions[0]["label"]
        last = self.session_emotions[-1]["label"]

        if first != last:
            return f"用户情绪从「{first}」变为「{last}」，主导情绪是「{most_common}」"
        return f"用户整体情绪以「{most_common}」为主"

    def _parse_json(self, text: str) -> Dict:
        import json
        try:
            cleaned = text.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            if cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            return json.loads(cleaned.strip())
        except Exception:
            return {}
