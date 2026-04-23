"""
Shared pytest fixtures for the Evolving Agent test suite.
"""
import os
import sys
import time
import tempfile
import shutil
import asyncio
from typing import Generator
import pytest

# Ensure project root is on path when running tests directly
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ---------------------------------------------------------------------------
# Event loop policy for async tests
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# ---------------------------------------------------------------------------
# Temporary storage
# ---------------------------------------------------------------------------
@pytest.fixture
def temp_storage(tmp_path, monkeypatch) -> Generator[str, None, None]:
    """
    Yield a temporary directory suitable for agent storage.
    Also monkey-patches os.getcwd() inside the test so that relative
    paths like './storage' resolve under the temp directory.
    """
    storage_root = tmp_path / "storage"
    storage_root.mkdir(parents=True, exist_ok=True)
    original_cwd = os.getcwd()
    monkeypatch.chdir(tmp_path)
    try:
        yield str(storage_root)
    finally:
        monkeypatch.chdir(original_cwd)
        # tmp_path is cleaned up automatically by pytest


# ---------------------------------------------------------------------------
# Mock LLM
# ---------------------------------------------------------------------------
class MockLLM:
    """模拟 LLM，记录调用次数和时间"""
    def __init__(self, delay: float = 0.05):
        self.delay = delay
        self.call_count = 0
        self.call_times = []

    def quick_chat(self, prompt, system=None):
        self.call_count += 1
        t0 = time.time()
        time.sleep(self.delay)
        t1 = time.time()
        self.call_times.append((t0, t1))
        return f"result_for_{prompt[:20]}"

    async def aquick_chat(self, prompt, system=None):
        import asyncio as _asyncio
        self.call_count += 1
        t0 = time.time()
        await _asyncio.sleep(self.delay)
        t1 = time.time()
        self.call_times.append((t0, t1))
        return f"result_for_{prompt[:20]}"


@pytest.fixture
def mock_llm() -> MockLLM:
    """Return a fresh MockLLM instance with a small delay."""
    return MockLLM(delay=0.05)


@pytest.fixture
def fast_mock_llm() -> MockLLM:
    """Return a fresh MockLLM instance with zero delay (for speed)."""
    return MockLLM(delay=0.0)
