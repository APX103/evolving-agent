"""
Kimi LLM 客户端实现
合并原 kimi_client.py + embedding.py 的能力
支持同步 + 异步双模式
"""
import asyncio
from typing import Any, AsyncGenerator, Dict, Generator, List, Optional, Union

import numpy as np
from openai import AsyncOpenAI, OpenAI

from agent.config import Config
from agent.llm.base import LLMClient


class KimiLLMClient(LLMClient):
    def __init__(self, config: Optional[Config] = None):
        cfg = config or Config()
        kimi_cfg = cfg.kimi

        # 支持自定义 User-Agent（如 Kimi Code 白名单绕过）
        import httpx
        user_agent = kimi_cfg.get("user_agent", "")

        def _force_ua(request):
            if user_agent:
                request.headers["User-Agent"] = user_agent

        # 同步 HTTP 客户端
        sync_http_client = httpx.Client(
            headers={"User-Agent": user_agent} if user_agent else {},
            event_hooks={"request": [_force_ua]},
        )
        # 异步 HTTP 客户端
        async_http_client = httpx.AsyncClient(
            headers={"User-Agent": user_agent} if user_agent else {},
            event_hooks={"request": [_force_ua]},
        )

        self._sync_client = OpenAI(
            api_key=kimi_cfg.get("api_key", ""),
            base_url=kimi_cfg.get("base_url", "https://api.moonshot.cn/v1"),
            http_client=sync_http_client,
        )
        self._async_client = AsyncOpenAI(
            api_key=kimi_cfg.get("api_key", ""),
            base_url=kimi_cfg.get("base_url", "https://api.moonshot.cn/v1"),
            http_client=async_http_client,
        )
        self.model = kimi_cfg.get("model", "kimi-latest")
        self.max_tokens = kimi_cfg.get("max_tokens", 4096)
        self.temperature = kimi_cfg.get("temperature", 0.7)
        self.embedding_model = kimi_cfg.get("embedding_model", "text-embedding")

        self._local_model: Optional[Any] = None
        self._use_local = False

    # ── 同步接口 ──

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stream: bool = False,
    ) -> Union[str, Generator[str, None, None]]:
        t = temperature if temperature is not None else self.temperature
        mt = max_tokens if max_tokens is not None else self.max_tokens

        try:
            if stream:
                response = self._sync_client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=t,
                    max_tokens=mt,
                    stream=True,
                )
                return self._stream_generator(response)
            else:
                response = self._sync_client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=t,
                    max_tokens=mt,
                    stream=False,
                )
                msg = response.choices[0].message
                return msg.content or getattr(msg, "reasoning_content", None) or ""
        except Exception as e:
            error_msg = f"[Kimi API 错误] {str(e)}"
            if stream:
                return error_msg
            return error_msg

    def _stream_generator(self, response) -> Generator[str, None, None]:
        for chunk in response:
            if chunk.choices and chunk.choices[0].delta:
                delta = chunk.choices[0].delta
                text = delta.content or getattr(delta, "reasoning_content", None) or ""
                if text:
                    yield text

    def quick_chat(self, prompt: str, system: str = "") -> str:
        messages: List[Dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return self.chat(messages, temperature=0.3, max_tokens=2048, stream=False)  # type: ignore[return-value]

    def embed(self, texts: Union[str, List[str]]) -> np.ndarray:
        if isinstance(texts, str):
            texts = [texts]
        try:
            return self._embed_api(texts)
        except Exception:
            return self._embed_local(texts)

    def _embed_api(self, texts: List[str]) -> np.ndarray:
        response = self._sync_client.embeddings.create(
            model=self.embedding_model,
            input=texts,
        )
        vectors = [item.embedding for item in response.data]
        arr = np.array(vectors, dtype=np.float32)
        if arr.ndim == 1:
            arr = arr.reshape(1, -1)
        return arr

    def _embed_local(self, texts: List[str]) -> np.ndarray:
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
        arr = vectors.astype(np.float32)
        if arr.ndim == 1:
            arr = arr.reshape(1, -1)
        return arr

    def cosine_similarity(self, query_vec: np.ndarray, doc_vecs: np.ndarray) -> np.ndarray:
        query_vec = query_vec / (np.linalg.norm(query_vec) + 1e-8)
        doc_vecs = doc_vecs / (np.linalg.norm(doc_vecs, axis=1, keepdims=True) + 1e-8)
        return np.dot(doc_vecs, query_vec)

    # ── 异步接口 ──

    async def achat(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stream: bool = False,
    ) -> Union[str, AsyncGenerator[str, None]]:
        t = temperature if temperature is not None else self.temperature
        mt = max_tokens if max_tokens is not None else self.max_tokens

        try:
            if stream:
                response = await self._async_client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=t,
                    max_tokens=mt,
                    stream=True,
                )
                return self._astream_generator(response)
            else:
                response = await self._async_client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=t,
                    max_tokens=mt,
                    stream=False,
                )
                msg = response.choices[0].message
                return msg.content or getattr(msg, "reasoning_content", None) or ""
        except Exception as e:
            error_msg = f"[Kimi API 错误] {str(e)}"
            if stream:
                # 返回一个立即 yield 错误消息的异步生成器
                async def _error_gen():
                    yield error_msg
                return _error_gen()
            return error_msg

    async def _astream_generator(self, response) -> AsyncGenerator[str, None]:
        async for chunk in response:
            if chunk.choices and chunk.choices[0].delta:
                delta = chunk.choices[0].delta
                text = delta.content or getattr(delta, "reasoning_content", None) or ""
                if text:
                    yield text

    async def aquick_chat(self, prompt: str, system: str = "") -> str:
        messages: List[Dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        result = await self.achat(messages, temperature=0.3, max_tokens=2048, stream=False)
        return result  # type: ignore[return-value]

    async def aembed(self, texts: Union[str, List[str]]) -> np.ndarray:
        if isinstance(texts, str):
            texts = [texts]
        try:
            return await self._aembed_api(texts)
        except Exception:
            # 本地 embed 没有 async 版本，fallback 到 sync（在后台线程运行）
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self._embed_local, texts)

    async def _aembed_api(self, texts: List[str]) -> np.ndarray:
        response = await self._async_client.embeddings.create(
            model=self.embedding_model,
            input=texts,
        )
        vectors = [item.embedding for item in response.data]
        arr = np.array(vectors, dtype=np.float32)
        if arr.ndim == 1:
            arr = arr.reshape(1, -1)
        return arr
