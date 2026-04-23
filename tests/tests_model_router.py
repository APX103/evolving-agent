"""
Tests for ModelRouter - multi-tier model routing with fallback.
"""
import pytest
from typing import Any, AsyncGenerator, Dict, Generator, List, Optional, Union
import numpy as np

from agent.llm.base import LLMClient
from agent.llm.router import ModelRouter


class MockLLMClient(LLMClient):
    """Mock LLM client that records which tier it represents."""

    def __init__(self, tier_name: str, should_fail: bool = False):
        self.tier_name = tier_name
        self.should_fail = should_fail
        self.chat_calls = []
        self.quick_chat_calls = []
        self._last_prompt_tokens = 10
        self._last_completion_tokens = 5

    def chat(self, messages, temperature=None, max_tokens=None, stream=False):
        self.chat_calls.append({"messages": messages, "stream": stream})
        if self.should_fail:
            raise RuntimeError(f"{self.tier_name} failed")
        return f"result_from_{self.tier_name}"

    def quick_chat(self, prompt, system=""):
        self.quick_chat_calls.append({"prompt": prompt, "system": system})
        if self.should_fail:
            raise RuntimeError(f"{self.tier_name} failed")
        return f"result_from_{self.tier_name}"

    def embed(self, texts):
        return np.array([[1.0, 2.0]])

    def cosine_similarity(self, query_vec, doc_vecs):
        return np.array([1.0])

    async def achat(self, messages, temperature=None, max_tokens=None, stream=False):
        self.chat_calls.append({"messages": messages, "stream": stream, "async": True})
        if self.should_fail:
            raise RuntimeError(f"{self.tier_name} failed")
        return f"aresult_from_{self.tier_name}"

    async def aquick_chat(self, prompt, system=""):
        self.quick_chat_calls.append({"prompt": prompt, "system": system, "async": True})
        if self.should_fail:
            raise RuntimeError(f"{self.tier_name} failed")
        return f"aresult_from_{self.tier_name}"

    async def aembed(self, texts):
        return np.array([[1.0, 2.0]])


@pytest.fixture
def mock_router():
    clients = {
        "lightweight": MockLLMClient("lightweight"),
        "standard": MockLLMClient("standard"),
        "heavy": MockLLMClient("heavy"),
    }
    router = ModelRouter(clients=clients)
    return router


# ---------------------------------------------------------------------------
# Complexity estimation
# ---------------------------------------------------------------------------

class TestComplexityEstimation:
    def test_greeting_simple(self, mock_router):
        assert mock_router.estimate_complexity("hello") == "simple"
        assert mock_router.estimate_complexity("你好") == "simple"
        assert mock_router.estimate_complexity("早上好") == "simple"
        assert mock_router.estimate_complexity("bye") == "simple"

    def test_emotion_simple(self, mock_router):
        assert mock_router.estimate_complexity("开心") == "simple"
        assert mock_router.estimate_complexity("累") == "simple"

    def test_short_qa_simple(self, mock_router):
        assert mock_router.estimate_complexity("how are you") == "simple"
        assert mock_router.estimate_complexity("你好吗？") == "simple"

    def test_standard_conversation(self, mock_router):
        # General conversation longer than 150 chars that is neither greeting nor code
        text = (
            "最近我在学习一些新的东西，看了很多资料，"
            "但是对一些概念还是不太理解，比如生活中的某些现象具体是怎么运作的，"
            "你能帮我用通俗的语言解释一下吗？"
        )
        assert mock_router.estimate_complexity(text) == "standard"
        assert mock_router.estimate_complexity("帮我看看这个问题，看起来有点复杂，需要你给出详细的建议，谢谢啦") == "standard"

    def test_code_heavy(self, mock_router):
        assert mock_router.estimate_complexity("写一段 Python 代码") == "heavy"
        assert mock_router.estimate_complexity("debug this error") == "heavy"
        assert mock_router.estimate_complexity("class Foo:") == "heavy"

    def test_reasoning_heavy(self, mock_router):
        assert mock_router.estimate_complexity("深度分析这个架构") == "heavy"
        assert mock_router.estimate_complexity("多步推理解决问题") == "heavy"

    def test_list_input(self, mock_router):
        messages = [{"role": "user", "content": "hi"}]
        assert mock_router.estimate_complexity(messages) == "simple"

        messages = [{"role": "user", "content": "def foo(): pass"}]
        assert mock_router.estimate_complexity(messages) == "heavy"


# ---------------------------------------------------------------------------
# Tier selection
# ---------------------------------------------------------------------------

class TestTierSelection:
    def test_select_model_simple(self, mock_router):
        client = mock_router.select_model("simple")
        assert client.tier_name == "lightweight"

    def test_select_model_standard(self, mock_router):
        client = mock_router.select_model("standard")
        assert client.tier_name == "standard"

    def test_select_model_heavy(self, mock_router):
        client = mock_router.select_model("heavy")
        assert client.tier_name == "heavy"

    def test_default_tier_property(self, mock_router):
        mock_router.default_tier = "heavy"
        assert mock_router.default_tier == "heavy"
        # When default_tier is set, routing should use it regardless of prompt
        result = mock_router.quick_chat("hi")
        assert result == "result_from_heavy"
        mock_router.default_tier = None

    def test_chat_auto_routing(self, mock_router):
        result = mock_router.chat([{"role": "user", "content": "hello"}])
        assert result == "result_from_lightweight"

    def test_chat_auto_routing_code(self, mock_router):
        result = mock_router.chat([{"role": "user", "content": "写代码"}])
        assert result == "result_from_heavy"

    @pytest.mark.asyncio
    async def test_async_chat_auto_routing(self, mock_router):
        result = await mock_router.achat([{"role": "user", "content": "hello"}])
        assert result == "aresult_from_lightweight"


# ---------------------------------------------------------------------------
# Fallback on failure
# ---------------------------------------------------------------------------

class TestFallback:
    def test_sync_quick_chat_fallback(self):
        clients = {
            "lightweight": MockLLMClient("lightweight", should_fail=True),
            "standard": MockLLMClient("standard"),
            "heavy": MockLLMClient("heavy"),
        }
        router = ModelRouter(clients=clients)
        router.default_tier = "lightweight"
        result = router.quick_chat("prompt")
        assert result == "result_from_standard"
        assert clients["lightweight"].quick_chat_calls
        assert clients["standard"].quick_chat_calls

    def test_sync_chat_fallback(self):
        clients = {
            "lightweight": MockLLMClient("lightweight", should_fail=True),
            "standard": MockLLMClient("standard", should_fail=True),
            "heavy": MockLLMClient("heavy"),
        }
        router = ModelRouter(clients=clients)
        router.default_tier = "lightweight"
        result = router.chat([{"role": "user", "content": "test"}])
        assert result == "result_from_heavy"

    def test_all_tiers_fail(self):
        clients = {
            "lightweight": MockLLMClient("lightweight", should_fail=True),
            "standard": MockLLMClient("standard", should_fail=True),
            "heavy": MockLLMClient("heavy", should_fail=True),
        }
        router = ModelRouter(clients=clients)
        with pytest.raises(RuntimeError, match="All model tiers failed"):
            router.quick_chat("test")

    @pytest.mark.asyncio
    async def test_async_fallback(self):
        clients = {
            "lightweight": MockLLMClient("lightweight", should_fail=True),
            "standard": MockLLMClient("standard"),
            "heavy": MockLLMClient("heavy"),
        }
        router = ModelRouter(clients=clients)
        router.default_tier = "lightweight"

        result = await router.aquick_chat("prompt")
        assert result == "aresult_from_standard"

    def test_stream_no_fallback(self):
        """Stream mode should return generator directly without attempting fallback."""
        def failing_gen():
            yield "chunk1"
            raise RuntimeError("stream error")
        
        class StreamMock(MockLLMClient):
            def chat(self, messages, temperature=None, max_tokens=None, stream=False):
                if stream:
                    return failing_gen()
                return super().chat(messages, temperature, max_tokens, stream)
        
        clients = {
            "lightweight": StreamMock("lightweight"),
            "standard": StreamMock("standard"),
        }
        router = ModelRouter(clients=clients)
        router.default_tier = "lightweight"
        gen = router.chat([{"role": "user", "content": "test"}], stream=True)
        # Generator is returned directly; error only occurs on iteration
        assert hasattr(gen, "__iter__")


# ---------------------------------------------------------------------------
# Cost tracking
# ---------------------------------------------------------------------------

class TestCostTracking:
    def test_cost_tracking_basic(self, mock_router):
        mock_router._track_cost("lightweight", 100, 50)
        summary = mock_router.get_cost_summary()
        assert summary["lightweight"]["prompt_tokens"] == 100
        assert summary["lightweight"]["completion_tokens"] == 50
        assert summary["lightweight"]["calls"] == 1

    def test_cost_tracking_with_rates(self, mock_router):
        mock_router._cost_per_1k = {
            "lightweight": {"prompt": 0.001, "completion": 0.002},
            "standard": {"prompt": 0.003, "completion": 0.006},
            "heavy": {"prompt": 0.01, "completion": 0.03},
        }
        mock_router._track_cost("lightweight", 1000, 500)
        mock_router._track_cost("standard", 2000, 1000)
        summary = mock_router.get_cost_summary()
        # lightweight: (1000/1000)*0.001 + (500/1000)*0.002 = 0.001 + 0.001 = 0.002
        assert abs(summary["lightweight"]["cost"] - 0.002) < 1e-9
        # standard: (2000/1000)*0.003 + (1000/1000)*0.006 = 0.006 + 0.006 = 0.012
        assert abs(summary["standard"]["cost"] - 0.012) < 1e-9
        # total
        assert abs(summary["total"]["cost"] - 0.014) < 1e-9
        assert summary["total"]["calls"] == 2

    def test_cost_summary_total(self, mock_router):
        mock_router._track_cost("lightweight", 10, 5)
        mock_router._track_cost("standard", 20, 10)
        mock_router._track_cost("heavy", 30, 15)
        summary = mock_router.get_cost_summary()
        assert summary["total"]["prompt_tokens"] == 60
        assert summary["total"]["completion_tokens"] == 30
        assert summary["total"]["calls"] == 3


# ---------------------------------------------------------------------------
# Single-model transparent mode
# ---------------------------------------------------------------------------

class TestSingleModelTransparentMode:
    def test_single_client_all_tiers(self):
        single = MockLLMClient("single")
        clients = {"lightweight": single, "standard": single, "heavy": single}
        router = ModelRouter(clients=clients)
        assert router.select_model("simple").tier_name == "single"
        assert router.select_model("heavy").tier_name == "single"
        result = router.quick_chat("hi")
        assert result == "result_from_single"
