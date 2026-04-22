"""
Embedding 客户端
支持 Kimi API Embedding 和本地 fallback
"""
import os
import json
import numpy as np
from typing import List, Union
import yaml


class EmbeddingClient:
    """
    文本向量化客户端
    优先使用 Kimi Embedding API，失败时 fallback 到本地模型或字符串匹配
    """
    
    def __init__(self, config_path: str = "config.yaml"):
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        
        kimi_cfg = cfg.get("kimi", {})
        self.api_key = kimi_cfg.get("api_key", "")
        self.base_url = kimi_cfg.get("base_url", "https://api.moonshot.cn/v1")
        self.model = kimi_cfg.get("embedding_model", "text-embedding")
        
        self._local_model = None
        self._use_local = False
    
    def embed(self, texts: Union[str, List[str]]) -> np.ndarray:
        """
        将文本转为向量
        返回: numpy array shape (n_texts, dim)
        """
        if isinstance(texts, str):
            texts = [texts]
        
        # 尝试 Kimi API
        try:
            return self._embed_api(texts)
        except Exception as e:
            # API 失败，尝试本地
            return self._embed_local(texts)
    
    def _embed_api(self, texts: List[str]) -> np.ndarray:
        """调用 Kimi Embedding API"""
        try:
            from openai import OpenAI
            client = OpenAI(api_key=self.api_key, base_url=self.base_url)
            
            # Kimi embedding 接口
            response = client.embeddings.create(
                model=self.model,
                input=texts
            )
            
            vectors = [item.embedding for item in response.data]
            return np.array(vectors, dtype=np.float32)
        except Exception:
            raise  # 抛到外层 fallback
    
    def _embed_local(self, texts: List[str]) -> np.ndarray:
        """本地模型 fallback"""
        if self._local_model is None:
            try:
                from sentence_transformers import SentenceTransformer
                model_name = "sentence-transformers/all-MiniLM-L6-v2"
                print(f"[Embedding] 加载本地模型 {model_name}...")
                self._local_model = SentenceTransformer(model_name)
                self._use_local = True
            except ImportError:
                raise RuntimeError(
                    "Embedding 不可用: Kimi API 失败且未安装 sentence-transformers。"
                    "请运行: pip install sentence-transformers"
                )
        
        vectors = self._local_model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
        return vectors.astype(np.float32)
    
    def cosine_similarity(self, query_vec: np.ndarray, doc_vecs: np.ndarray) -> np.ndarray:
        """计算余弦相似度"""
        # query_vec: (dim,), doc_vecs: (n, dim)
        query_vec = query_vec / (np.linalg.norm(query_vec) + 1e-8)
        doc_vecs = doc_vecs / (np.linalg.norm(doc_vecs, axis=1, keepdims=True) + 1e-8)
        return np.dot(doc_vecs, query_vec)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """两条向量的余弦相似度"""
    a = a / (np.linalg.norm(a) + 1e-8)
    b = b / (np.linalg.norm(b) + 1e-8)
    return float(np.dot(a, b))
