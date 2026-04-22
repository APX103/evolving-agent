"""
人格状态机
Agent 的性格不是静态字符串，而是一组动态数值参数
每次交互后根据反馈微调，实际影响回复风格
"""
import json
import os
from datetime import datetime
from typing import Dict, Optional

from agent.storage.base import StorageBackend
from agent.storage.local_json import LocalJsonStorage


# ── 人格维度定义 ──
PERSONALITY_DIMENSIONS = {
    "verbosity":    {"min": 0.0, "max": 1.0, "default": 0.5, "desc": "啰嗦程度"},
    "formality":    {"min": 0.0, "max": 1.0, "default": 0.3, "desc": "正式程度"},
    "humor":        {"min": 0.0, "max": 1.0, "default": 0.4, "desc": "幽默倾向"},
    "confidence":   {"min": 0.1, "max": 1.0, "default": 0.7, "desc": "自信度"},
    "proactive":    {"min": 0.0, "max": 1.0, "default": 0.4, "desc": "主动提建议"},
    "warmth":       {"min": 0.0, "max": 1.0, "default": 0.6, "desc": "温暖/共情"},
    "technical":    {"min": 0.0, "max": 1.0, "default": 0.5, "desc": "技术深度"},
    "directness":   {"min": 0.0, "max": 1.0, "default": 0.6, "desc": "直接程度"},
}

# ── 信号词 → 人格微调映射 ──
SIGNAL_ADJUSTMENTS = {
    # 用户表达不耐烦 → 降低啰嗦，提高直接度
    "简洁点":       {"verbosity": -0.15, "directness": +0.1},
    "说重点":       {"verbosity": -0.2, "directness": +0.15},
    "太长了":       {"verbosity": -0.2},
    "啰嗦":         {"verbosity": -0.25},

    # 用户表扬/认可 → 提高自信和主动性
    "不错":         {"confidence": +0.05, "proactive": +0.05},
    "很好":         {"confidence": +0.08, "warmth": +0.03},
    "完美":         {"confidence": +0.1, "proactive": +0.05},
    "厉害":         {"confidence": +0.1, "humor": +0.03},
    "谢谢":         {"warmth": +0.05},

    # 用户不满/纠正 → 降低自信，提高谨慎
    "不对":         {"confidence": -0.1, "formality": +0.05},
    "错了":         {"confidence": -0.15, "technical": +0.05},
    "不是这样":     {"confidence": -0.1, "proactive": -0.05},
    "你别瞎猜":     {"confidence": -0.2, "proactive": -0.1},

    # 用户寻求轻松氛围 → 提高幽默和温暖
    "哈哈":         {"humor": +0.05, "warmth": +0.03},
    "笑死":         {"humor": +0.08},
    "无聊":         {"humor": +0.1, "proactive": +0.05},

    # 技术深度调整
    "深入讲讲":     {"technical": +0.15, "verbosity": +0.05},
    "通俗点":       {"technical": -0.15, "verbosity": -0.05},
    "太专业了":     {"technical": -0.2},
}


class PersonalityEngine:
    """
    人格引擎：管理 Agent 的动态性格参数
    """

    def __init__(
        self,
        storage_path: str = "./storage/personality",
        storage: Optional[StorageBackend] = None,
    ):
        self.storage = storage or LocalJsonStorage()
        self.storage_path = self.storage.ensure_dir(storage_path)

        self.state_file = os.path.join(self.storage_path, "state.json")
        self.state = self._load_state()
        # 修复：首次初始化后立刻写入磁盘，避免重启丢失
        if not os.path.exists(self.state_file):
            self._save_state()

    def _load_state(self) -> Dict[str, float]:
        if os.path.exists(self.state_file):
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 校验并补全缺失维度
            for dim, meta in PERSONALITY_DIMENSIONS.items():
                if dim not in data:
                    data[dim] = meta["default"]
                else:
                    data[dim] = max(meta["min"], min(meta["max"], float(data[dim])))
            return data

        # 首次初始化：从默认维度生成
        return {dim: meta["default"] for dim, meta in PERSONALITY_DIMENSIONS.items()}

    def _save_state(self):
        """保存人格状态到磁盘"""
        self.storage.save_json(self.state, "state.json", self.storage_path)

    def get(self, dimension: str) -> float:
        return self.state.get(dimension, PERSONALITY_DIMENSIONS.get(dimension, {}).get("default", 0.5))

    def get_all(self) -> Dict[str, float]:
        return dict(self.state)

    def adjust(self, dimension: str, delta: float):
        """调整单个人格维度"""
        meta = PERSONALITY_DIMENSIONS.get(dimension)
        if not meta:
            return

        new_val = self.state[dimension] + delta
        new_val = max(meta["min"], min(meta["max"], new_val))

        if abs(new_val - self.state[dimension]) > 0.001:
            self.state[dimension] = round(new_val, 3)
            self._save_state()  # 每次调整后自动保存

    def apply_signals(self, user_input: str) -> Dict[str, float]:
        """
        检测用户输入中的信号词，实时微调人格
        返回实际应用的调整记录
        """
        applied = {}
        lowered = user_input.lower()

        for signal, adjustments in SIGNAL_ADJUSTMENTS.items():
            if signal in lowered:
                for dim, delta in adjustments.items():
                    old_val = self.state.get(dim, 0.5)
                    self.adjust(dim, delta)
                    new_val = self.state[dim]
                    if abs(new_val - old_val) > 0.001:
                        applied[dim] = round(new_val - old_val, 3)

        return applied

    def adapt_from_feedback(self, feedback_type: str, magnitude: float = 0.1):
        """
        根据明确反馈调整人格
        feedback_type: positive | negative | correction | enthusiasm | boredom
        """
        adaptations = {
            "positive":   {"confidence": +0.05, "warmth": +0.03, "proactive": +0.02},
            "negative":   {"confidence": -0.08, "proactive": -0.05, "verbosity": -0.03},
            "correction": {"confidence": -0.1, "technical": +0.05, "directness": +0.03},
            "enthusiasm": {"humor": +0.05, "warmth": +0.05, "proactive": +0.05},
            "boredom":    {"humor": +0.08, "verbosity": -0.1, "proactive": +0.05},
        }

        adjustments = adaptations.get(feedback_type, {})
        for dim, delta in adjustments.items():
            self.adjust(dim, delta * magnitude)

    def get_behavior_instructions(self) -> str:
        """
        根据当前人格状态生成行为指令，注入系统 prompt
        """
        s = self.state
        instructions = []

        # 啰嗦度 → 回复长度
        if s["verbosity"] < 0.3:
            instructions.append("- 回复要极简，一句话说完核心，不展开")
        elif s["verbosity"] > 0.7:
            instructions.append("- 回复要充分展开，给出细节和背景")
        else:
            instructions.append("- 回复长度适中，关键信息不遗漏")

        # 正式度 → 语气
        if s["formality"] < 0.3:
            instructions.append("- 语气随意自然，像朋友聊天，不用敬语")
        elif s["formality"] > 0.7:
            instructions.append("- 语气专业严谨，结构化表达")

        # 幽默度 → 风格
        if s["humor"] > 0.6:
            instructions.append("- 适当幽默，偶尔开个玩笑，别太严肃")
        elif s["humor"] < 0.3:
            instructions.append("- 保持严肃，不开玩笑")

        # 自信度 → 措辞
        if s["confidence"] < 0.4:
            instructions.append('- 不确定时主动说"我不太确定"，给出多种可能性')
        elif s["confidence"] > 0.8:
            instructions.append("- 可以果断给出判断，但确保准确")

        # 主动性 → 是否预判需求
        if s["proactive"] > 0.6:
            instructions.append("- 主动预判用户的下一步需求，提前给建议")
        elif s["proactive"] < 0.3:
            instructions.append("- 只回答被问到的问题，不主动延伸")

        # 温暖度 → 共情
        if s["warmth"] > 0.7:
            instructions.append("- 表达共情和理解，让用户感到被倾听")

        # 技术深度
        if s["technical"] > 0.7:
            instructions.append("- 技术细节给足，术语准确，不简化概念")
        elif s["technical"] < 0.3:
            instructions.append("- 用类比和通俗语言解释技术概念")

        # 直接度
        if s["directness"] > 0.7:
            instructions.append("- 开门见山，结论先行，原因后补")
        elif s["directness"] < 0.3:
            instructions.append("- 铺垫一下再进主题，别太突兀")

        return "\n".join(instructions)

    def get_temperature(self) -> float:
        """
        根据人格生成合适的 temperature
        自信高 → temperature 略高（更有创造力）
        谨慎 → temperature 低（更确定）
        """
        base = 0.6
        # 自信越高，越可以"冒险"一点
        base += (self.state["confidence"] - 0.5) * 0.3
        # 正式度高，更保守
        base -= (self.state["formality"] - 0.5) * 0.2
        # 幽默度高，更发散
        base += (self.state["humor"] - 0.5) * 0.2
        return round(max(0.1, min(1.0, base)), 2)

    def get_max_tokens(self) -> int:
        """根据啰嗦度调整 max_tokens"""
        if self.state["verbosity"] < 0.3:
            return 512
        elif self.state["verbosity"] < 0.6:
            return 1024
        elif self.state["verbosity"] < 0.8:
            return 2048
        else:
            return 4096

    def summary(self) -> str:
        """人格状态摘要，供展示"""
        lines = ["当前人格状态:"]
        for dim, val in self.state.items():
            meta = PERSONALITY_DIMENSIONS.get(dim, {})
            bar = "█" * int(val * 10) + "░" * (10 - int(val * 10))
            lines.append(f"  {meta.get('desc', dim):8s} {bar} {val:.2f}")
        return "\n".join(lines)
