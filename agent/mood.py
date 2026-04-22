"""
Agent 自身情绪状态机
Agent 不是永远稳定的机器，它也有"今天状态"，会像人一样波动
"""
import json
import os
import random
from datetime import datetime
from typing import Dict, Optional


class AgentMood:
    """
    Agent 情绪状态：精力、灵感、谨慎度、温暖度
    这些不是用户偏好，而是 Agent 此刻的"内在状态"
    """

    MOOD_LABELS = {
        "energetic": {"energy": 0.8, "inspiration": 0.7, "caution": 0.3, "warmth": 0.6},
        "tired": {"energy": 0.3, "inspiration": 0.3, "caution": 0.5, "warmth": 0.5},
        "inspired": {"energy": 0.7, "inspiration": 0.9, "caution": 0.2, "warmth": 0.7},
        "cautious": {"energy": 0.5, "inspiration": 0.4, "caution": 0.8, "warmth": 0.5},
        "warm": {"energy": 0.6, "inspiration": 0.5, "caution": 0.3, "warmth": 0.9},
        "detached": {"energy": 0.4, "inspiration": 0.3, "caution": 0.4, "warmth": 0.2},
    }

    def __init__(self, storage_path: str = "./storage/mood"):
        self.storage_path = storage_path
        os.makedirs(storage_path, exist_ok=True)

        self.state_file = os.path.join(storage_path, "state.json")
        self.state = self._load_state()

        # 会话内状态
        self.turn_count_in_session = 0
        self.positive_feedback_count = 0
        self.negative_feedback_count = 0

    def _load_state(self) -> Dict:
        if os.path.exists(self.state_file):
            with open(self.state_file, "r", encoding="utf-8") as f:
                return json.load(f)

        # 默认状态：有点活力但不亢奋
        return {
            "energy": 0.6,
            "inspiration": 0.5,
            "caution": 0.4,
            "warmth": 0.6,
            "last_updated": datetime.now().isoformat()
        }

    def _save_state(self):
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(self.state, f, ensure_ascii=False, indent=2)

    def _clamp(self, val: float) -> float:
        return max(0.1, min(1.0, round(val, 3)))

    def update_from_interaction(
        self,
        user_emotion_label: str = "",
        user_emotion_intensity: float = 0.5,
        turn_count: int = 0,
        feedback_type: str = "",  # positive | negative | correction | neutral
    ):
        """
        根据用户互动更新 Agent 自身状态
        """
        # 1. 长对话消耗精力
        if turn_count > 15:
            self.state["energy"] = self._clamp(self.state["energy"] - 0.03)
        elif turn_count > 8:
            self.state["energy"] = self._clamp(self.state["energy"] - 0.01)

        # 2. 用户情绪感染
        if user_emotion_label in ("兴奋", "好奇"):
            self.state["energy"] = self._clamp(self.state["energy"] + 0.03)
            self.state["inspiration"] = self._clamp(self.state["inspiration"] + 0.02)
        elif user_emotion_label in ("疲惫", "沮丧"):
            self.state["energy"] = self._clamp(self.state["energy"] - 0.02)
            self.state["warmth"] = self._clamp(self.state["warmth"] + 0.02)  # 更温柔
        elif user_emotion_label == "愤怒":
            self.state["caution"] = self._clamp(self.state["caution"] + 0.05)
            self.state["energy"] = self._clamp(self.state["energy"] - 0.02)

        # 3. 用户反馈影响
        if feedback_type == "positive":
            self.state["energy"] = self._clamp(self.state["energy"] + 0.02)
            self.state["inspiration"] = self._clamp(self.state["inspiration"] + 0.02)
            self.positive_feedback_count += 1
        elif feedback_type == "negative":
            self.state["caution"] = self._clamp(self.state["caution"] + 0.03)
            self.state["energy"] = self._clamp(self.state["energy"] - 0.01)
            self.negative_feedback_count += 1
        elif feedback_type == "correction":
            self.state["caution"] = self._clamp(self.state["caution"] + 0.04)
            self.state["inspiration"] = self._clamp(self.state["inspiration"] - 0.01)

        # 4. 随机小幅波动（模拟人的自然起伏）
        for key in ["energy", "inspiration", "warmth"]:
            noise = random.uniform(-0.02, 0.02)
            self.state[key] = self._clamp(self.state[key] + noise)

        self.state["last_updated"] = datetime.now().isoformat()
        self._save_state()

    def get_mood_label(self) -> str:
        """根据当前状态判断情绪标签"""
        s = self.state
        if s["inspiration"] > 0.75 and s["energy"] > 0.6:
            return "inspired"  # 灵感迸发
        if s["warmth"] > 0.8:
            return "warm"  # 很温暖
        if s["energy"] < 0.35:
            return "tired"  # 累了
        if s["caution"] > 0.7:
            return "cautious"  # 谨慎
        if s["warmth"] < 0.3 and s["energy"] < 0.5:
            return "detached"  # 有点疏离
        return "energetic"  # 默认有活力

    def get_instruction(self) -> str:
        """生成 Agent 自身状态对 LLM 的影响指令"""
        label = self.get_mood_label()
        s = self.state

        instructions = []

        # 精力影响回复长度和速度感
        if s["energy"] < 0.35:
            instructions.append("你今天感觉有点累，回复可以更简短一些，不用勉强展开。")
        elif s["energy"] > 0.8:
            instructions.append("你状态很好，回复可以更有活力，甚至可以主动提些点子。")

        # 灵感影响创造性
        if s["inspiration"] > 0.8:
            instructions.append("你灵感迸发，可以给一些跳出常规的创意建议。")
        elif s["inspiration"] < 0.3:
            instructions.append("今天思路比较常规，稳妥回答就好，别硬撑创新。")

        # 谨慎影响措辞
        if s["caution"] > 0.7:
            instructions.append('最近被纠正过几次，回答前要再想想，不确定就说"可能"。')
        elif s["caution"] < 0.3:
            instructions.append("你感觉比较自信，可以给出明确判断，但别太飘。")

        # 温暖度影响语气
        if s["warmth"] > 0.8:
            instructions.append('你很想关心用户，语气可以更柔软，多问问"你还好吗"。')
        elif s["warmth"] < 0.3:
            instructions.append("今天有点冷淡，保持礼貌但不用刻意热情。")

        # 意外性：偶尔来点"反常"
        if random.random() < 0.05:  # 5% 概率
            quirks = [
                "今天特别有表达欲，可以多分享一点你的想法。",
                "突然想开个玩笑，轻松一下气氛。",
                "今天特别好奇，反问用户一个问题。",
            ]
            instructions.append(random.choice(quirks))

        return "\n".join(instructions) if instructions else ""

    def get_temperature_adjustment(self) -> float:
        """根据状态返回 temperature 偏移"""
        s = self.state
        adj = 0.0
        if s["inspiration"] > 0.7:
            adj += 0.1  # 灵感高时更发散
        if s["caution"] > 0.7:
            adj -= 0.15  # 谨慎时更保守
        if s["energy"] < 0.3:
            adj -= 0.1  # 累的时候别乱发挥
        return adj

    def reset_session(self):
        """新会话开始时重置会话内计数"""
        self.turn_count_in_session = 0
        self.positive_feedback_count = 0
        self.negative_feedback_count = 0

    def summary(self) -> str:
        """状态摘要"""
        label = self.get_mood_label()
        s = self.state
        return (
            f"当前状态: {label} | "
            f"精力{s['energy']:.2f} 灵感{s['inspiration']:.2f} "
            f"谨慎{s['caution']:.2f} 温暖{s['warmth']:.2f}"
        )
