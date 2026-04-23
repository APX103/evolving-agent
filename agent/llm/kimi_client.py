"""
Kimi LLM 客户端实现
合并原 kimi_client.py + embedding.py 的能力
支持同步 + 异步双模式
"""
import asyncio
import time
from typing import Any, AsyncGenerator, Dict, Generator, List, Optional, Type, TypeVar, Union

import numpy as np
from openai import AsyncOpenAI, OpenAI

from agent.config import Config
from agent.llm.base import LLMClient, StructuredOutputError
from agent.observability import get_tracer, get_llm_logger


T = TypeVar("T")


class KimiLLMClient(LLMClient):
    def __init__(self, config: Optional[Config] = None, model: Optional[str] = None):
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
            timeout=httpx.Timeout(30.0, connect=10.0),
        )
        # 异步 HTTP 客户端
        async_http_client = httpx.AsyncClient(
            headers={"User-Agent": user_agent} if user_agent else {},
            event_hooks={"request": [_force_ua]},
            timeout=httpx.Timeout(30.0, connect=10.0),
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
        self.model = model or kimi_cfg.get("model", "kimi-latest")
        self.max_tokens = kimi_cfg.get("max_tokens", 4096)
        self.temperature = kimi_cfg.get("temperature", 0.7)
        self.embedding_model = kimi_cfg.get("embedding_model", "text-embedding")

        self._local_model: Optional[Any] = None
        self._use_local = False
        self._last_prompt_tokens: int = 0
        self._last_completion_tokens: int = 0

    # ── 同步接口 ──

    def chat(
        self,
        messages: List[Dict[str, Any]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stream: bool = False,
    ) -> Union[str, Generator[str, None, None]]:
        t = temperature if temperature is not None else self.temperature
        mt = max_tokens if max_tokens is not None else self.max_tokens

        tracer = get_tracer()
        llm_logger = get_llm_logger()
        span = tracer.start_span("llm.chat", attributes={"model": self.model, "stream": stream, "sync": True})
        start = time.time()

        try:
            if stream:
                response = self._sync_client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=t,
                    max_tokens=mt,
                    stream=True,
                )
                return self._stream_generator_with_trace(
                    response, span, start, llm_logger, messages
                )
            else:
                response = self._sync_client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=t,
                    max_tokens=mt,
                    stream=False,
                )
                latency_ms = (time.time() - start) * 1000
                msg = response.choices[0].message
                content = msg.content or getattr(msg, "reasoning_content", None) or ""
                prompt_text = messages[-1].get("content", "") if messages else ""
                self._finish_llm_span(span, llm_logger, response, latency_ms, prompt_text, content)
                return content
        except Exception as e:
            latency_ms = (time.time() - start) * 1000
            span.set_attribute("error", True)
            span.record_exception(e)
            span.end()
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

    def _stream_generator_with_trace(self, response, span, start, llm_logger, messages):
        """带追踪的流式生成器"""
        full_text = ""
        try:
            for chunk in response:
                if chunk.choices and chunk.choices[0].delta:
                    delta = chunk.choices[0].delta
                    text = delta.content or getattr(delta, "reasoning_content", None) or ""
                    if text:
                        full_text += text
                        yield text
        except Exception as e:
            span.record_exception(e)
            raise
        finally:
            latency_ms = (time.time() - start) * 1000
            prompt_text = messages[-1].get("content", "") if messages else ""
            span.set_attribute("response_length", len(full_text))
            span.end()
            llm_logger.log_call(
                model=self.model,
                prompt_tokens=0,
                completion_tokens=0,
                latency_ms=latency_ms,
                prompt_sample=prompt_text,
                response_sample=full_text,
                trace_id=span.trace_id,
                span_id=span.span_id,
                extra={"stream": True, "sync": True},
            )

    def _finish_llm_span(self, span, llm_logger, response, latency_ms, prompt_text, content):
        """完成 LLM span 并记录日志"""
        prompt_tokens = 0
        completion_tokens = 0
        try:
            if hasattr(response, "usage") and response.usage:
                prompt_tokens = getattr(response.usage, "prompt_tokens", 0) or 0
                completion_tokens = getattr(response.usage, "completion_tokens", 0) or 0
        except Exception:
            pass

        self._last_prompt_tokens = prompt_tokens
        self._last_completion_tokens = completion_tokens

        span.set_attribute("latency_ms", round(latency_ms, 2))
        span.set_attribute("prompt_tokens", prompt_tokens)
        span.set_attribute("completion_tokens", completion_tokens)
        span.set_attribute("response_length", len(content))
        span.end()

        llm_logger.log_call(
            model=self.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            prompt_sample=prompt_text,
            response_sample=content,
            trace_id=span.trace_id,
            span_id=span.span_id,
            extra={"stream": False},
        )

    def quick_chat(self, prompt: str, system: str = "") -> str:
        messages: List[Dict[str, Any]] = []
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
        messages: List[Dict[str, Any]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stream: bool = False,
    ) -> Union[str, AsyncGenerator[str, None]]:
        t = temperature if temperature is not None else self.temperature
        mt = max_tokens if max_tokens is not None else self.max_tokens

        tracer = get_tracer()
        llm_logger = get_llm_logger()
        span = tracer.start_span("llm.achat", attributes={"model": self.model, "stream": stream, "sync": False})
        start = time.time()

        try:
            if stream:
                response = await self._async_client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=t,
                    max_tokens=mt,
                    stream=True,
                )
                return self._astream_generator_with_trace(
                    response, span, start, llm_logger, messages
                )
            else:
                response = await self._async_client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=t,
                    max_tokens=mt,
                    stream=False,
                )
                latency_ms = (time.time() - start) * 1000
                msg = response.choices[0].message
                content = msg.content or getattr(msg, "reasoning_content", None) or ""
                prompt_text = messages[-1].get("content", "") if messages else ""
                self._finish_llm_span(span, llm_logger, response, latency_ms, prompt_text, content)
                return content
        except Exception as e:
            latency_ms = (time.time() - start) * 1000
            span.set_attribute("error", True)
            span.record_exception(e)
            span.end()
            error_msg = f"[Kimi API 错误] {str(e)}"
            if stream:
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

    async def _astream_generator_with_trace(self, response, span, start, llm_logger, messages):
        """带追踪的异步流式生成器"""
        full_text = ""
        try:
            async for chunk in response:
                if chunk.choices and chunk.choices[0].delta:
                    delta = chunk.choices[0].delta
                    text = delta.content or getattr(delta, "reasoning_content", None) or ""
                    if text:
                        full_text += text
                        yield text
        except Exception as e:
            span.record_exception(e)
            raise
        finally:
            latency_ms = (time.time() - start) * 1000
            prompt_text = messages[-1].get("content", "") if messages else ""
            span.set_attribute("response_length", len(full_text))
            span.end()
            llm_logger.log_call(
                model=self.model,
                prompt_tokens=0,
                completion_tokens=0,
                latency_ms=latency_ms,
                prompt_sample=prompt_text,
                response_sample=full_text,
                trace_id=span.trace_id,
                span_id=span.span_id,
                extra={"stream": True, "sync": False},
            )

    async def aquick_chat(self, prompt: str, system: str = "") -> str:
        messages: List[Dict[str, Any]] = []
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

    # ── 结构化输出接口（使用 OpenAI JSON mode） ──

    def chat_structured(
        self,
        prompt: str,
        response_model: Type[T],
        system: str = "",
        **kwargs,
    ) -> T:
        from pydantic import ValidationError

        t = kwargs.get("temperature", self.temperature)
        mt = kwargs.get("max_tokens", self.max_tokens)

        messages: List[Dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        try:
            response = self._sync_client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=t,
                max_tokens=mt,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content or ""
        except Exception:
            # Fallback: 普通 quick_chat（可能模型不支持 json_object）
            raw = self.quick_chat(prompt, system=system)

        cleaned = self._clean_json(raw)
        try:
            return response_model.model_validate_json(cleaned)
        except ValidationError as e:
            raise StructuredOutputError(
                f"Failed to validate structured output: {e}",
                raw_text=raw,
            ) from e
        except Exception as e:
            raise StructuredOutputError(
                f"Failed to parse structured output: {e}",
                raw_text=raw,
            ) from e

    async def achat_structured(
        self,
        prompt: str,
        response_model: Type[T],
        system: str = "",
        **kwargs,
    ) -> T:
        from pydantic import ValidationError

        t = kwargs.get("temperature", self.temperature)
        mt = kwargs.get("max_tokens", self.max_tokens)

        messages: List[Dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        try:
            response = await self._async_client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=t,
                max_tokens=mt,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content or ""
        except Exception:
            # Fallback: 普通 aquick_chat
            raw = await self.aquick_chat(prompt, system=system)

        cleaned = self._clean_json(raw)
        try:
            return response_model.model_validate_json(cleaned)
        except ValidationError as e:
            raise StructuredOutputError(
                f"Failed to validate structured output: {e}",
                raw_text=raw,
            ) from e
        except Exception as e:
            raise StructuredOutputError(
                f"Failed to parse structured output: {e}",
                raw_text=raw,
            ) from e
