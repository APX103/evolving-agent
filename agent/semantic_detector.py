"""
语义信号检测器
用 Embedding 向量相似度替代正则匹配，识别用户意图
"""
import os
import json
from typing import Dict, List, Optional, Tuple
import numpy as np

from agent.llm.base import LLMClient


# 预定义信号意图示例（用于计算语义锚点）
SIGNAL_INTENT_EXAMPLES = {
    "remember": [
        "请记住", "记住", "别忘了", "以后记住", "记一下",
        "请记住这个", "帮我记着", "我要你记住", "记下来",
        "remember this", "don't forget", "keep in mind",
    ],
    "preference_positive": [
        "我喜欢", "我爱", "我偏好", "我习惯", "我喜欢吃",
        "我爱好", "我钟爱", "我热衷于", "我比较偏爱",
        "i like", "i love", "i prefer", "i enjoy",
    ],
    "preference_negative": [
        "我讨厌", "我不喜欢", "别", "以后别", "不好", "不行",
        "我厌恶", "我反感", "我讨厌吃", "我不习惯",
        "i hate", "i don't like", "i dislike", "stop",
    ],
    "identity": [
        "我叫", "我的名字是", "我是做", "我的工作",
        "我从事", "我的职业是", "我是干", "我在",
        "my name is", "i am a", "i work as", "my job is",
    ],
    "correction": [
        "不对", "错了", "应该是", "正确的是", "你误解了",
        "不是这样的", "纠正一下", "其实", "你理解错了",
        "wrong", "incorrect", "that's not right", "you misunderstood",
    ],
    "urgency": [
        "紧急", "快点", "马上", "很急", "尽快",
        "立刻", "抓紧时间", "刻不容缓", "十万火急",
        "urgent", "hurry", "asap", "immediately",
    ],
    "gratitude": [
        "谢谢", "感谢", "帮大忙了", "太感谢了", "多谢",
        "thank you", "thanks", "appreciate it", "grateful",
    ],
    "frustration": [
        "烦死了", "气死了", "无语了", "麻烦", "搞不定",
        "受够了", "真烦人", "太糟了", "令人头疼",
        "frustrated", "annoying", "sucks", "can't stand",
    ],
}


class SemanticSignalDetector:
    """
    基于 Embedding 的语义意图检测器
    - 比正则更鲁棒，能捕捉语义变体
    - 支持多语言（中文/英文/混合）
    - 可动态添加新的意图类别
    """

    def __init__(self, llm_client: LLMClient, cache_dir: str = "./storage/semantic_cache"):
        self.llm_client = llm_client
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)

        self.intent_examples = dict(SIGNAL_INTENT_EXAMPLES)
        self._anchor_vectors: Dict[str, np.ndarray] = {}
        self._load_or_build_anchors()

    def _load_or_build_anchors(self):
        """加载或构建意图锚点向量"""
        cache_path = os.path.join(self.cache_dir, "intent_anchors.json")
        vec_cache_path = os.path.join(self.cache_dir, "intent_anchors.npy")

        if os.path.exists(cache_path) and os.path.exists(vec_cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    cached = json.load(f)
                if cached == self.intent_examples:
                    self._anchor_vectors = {
                        k: np.load(vec_cache_path)[i]
                        for i, k in enumerate(self.intent_examples.keys())
                    }
                    return
            except Exception:
                pass

        # 重新构建锚点：每个意图的示例取平均向量
        print("[SemanticDetector] 构建意图锚点向量...")
        for intent, examples in self.intent_examples.items():
            try:
                vecs = self.llm_client.embed(examples)
                # 取平均并归一化
                anchor = vecs.mean(axis=0)
                anchor = anchor / (np.linalg.norm(anchor) + 1e-8)
                self._anchor_vectors[intent] = anchor
            except Exception as e:
                print(f"[SemanticDetector] 意图 '{intent}' 向量构建失败: {e}")

        # 保存缓存
        if self._anchor_vectors:
            np.save(vec_cache_path, np.stack(list(self._anchor_vectors.values())))
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(self.intent_examples, f, ensure_ascii=False, indent=2)

    def add_intent(self, intent_name: str, examples: List[str]):
        """动态添加新意图类别"""
        self.intent_examples[intent_name] = examples
        try:
            vecs = self.llm_client.embed(examples)
            anchor = vecs.mean(axis=0)
            anchor = anchor / (np.linalg.norm(anchor) + 1e-8)
            self._anchor_vectors[intent_name] = anchor
        except Exception as e:
            print(f"[SemanticDetector] 添加意图 '{intent_name}' 失败: {e}")

    def detect(self, text: str, threshold: float = 0.78) -> Optional[Tuple[str, float]]:
        """
        检测文本的意图
        返回: (intent_name, similarity) 或 None
        """
        if not self._anchor_vectors or not text.strip():
            return None

        try:
            query_vec = self.llm_client.embed(text)
            query_vec = query_vec[0] / (np.linalg.norm(query_vec[0]) + 1e-8)

            best_intent = None
            best_sim = 0.0

            for intent, anchor in self._anchor_vectors.items():
                sim = float(np.dot(query_vec, anchor))
                if sim > best_sim and sim > threshold:
                    best_sim = sim
                    best_intent = intent

            if best_intent:
                return best_intent, round(best_sim, 3)
            return None

        except Exception as e:
            print(f"[SemanticDetector] 检测失败: {e}")
            return None

    def detect_top_k(self, text: str, k: int = 3) -> List[Tuple[str, float]]:
        """返回 top-k 最相似的意图（用于调试和分析）"""
        if not self._anchor_vectors or not text.strip():
            return []

        try:
            query_vec = self.llm_client.embed(text)
            query_vec = query_vec[0] / (np.linalg.norm(query_vec[0]) + 1e-8)

            scores = []
            for intent, anchor in self._anchor_vectors.items():
                sim = float(np.dot(query_vec, anchor))
                scores.append((intent, round(sim, 3)))

            scores.sort(key=lambda x: x[1], reverse=True)
            return scores[:k]

        except Exception as e:
            print(f"[SemanticDetector] top-k 检测失败: {e}")
            return []
