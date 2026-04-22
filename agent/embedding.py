"""
Embedding 客户端（兼容层）
原实现已迁移至 agent.llm.kimi_client.KimiLLMClient
此文件保留以兼容旧 import，内部转发到新实现
"""
import warnings
from typing import List, Union
import numpy as np

from agent.llm.kimi_client import KimiLLMClient

warnings.warn(
    "agent.embedding 已弃用，请改用 agent.llm.KimiLLMClient.embed()",
    DeprecationWarning,
    stacklevel=2
)


class EmbeddingClient:
    """兼容旧接口的包装器"""

    def __init__(self, config_path: str = "config.yaml"):
        self._client = KimiLLMClient()

    def embed(self, texts: Union[str, List[str]]) -> np.ndarray:
        return self._client.embed(texts)

    def cosine_similarity(self, query_vec: np.ndarray, doc_vecs: np.ndarray) -> np.ndarray:
        return self._client.cosine_similarity(query_vec, doc_vecs)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """两条向量的余弦相似度"""
    a = a / (np.linalg.norm(a) + 1e-8)
    b = b / (np.linalg.norm(b) + 1e-8)
    return float(np.dot(a, b))
