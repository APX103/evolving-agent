"""
Embedding 客户端
"""
from typing import List, Union
import numpy as np

from agent.llm.kimi_client import KimiLLMClient


class EmbeddingClient:
    def __init__(self, config_path: str = "config.yaml"):
        self._llm = KimiLLMClient()

    def embed(self, texts: Union[str, List[str]]) -> np.ndarray:
        if isinstance(texts, str):
            texts = [texts]
        return self._llm.embed(texts)

    def cosine_similarity(self, query_vec: np.ndarray, doc_vecs: np.ndarray) -> np.ndarray:
        dot = query_vec @ doc_vecs.T
        qnorm = np.linalg.norm(query_vec)
        dnorm = np.linalg.norm(doc_vecs, axis=1)
        return dot / (qnorm * dnorm + 1e-10)
