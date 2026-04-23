"""
A2A Protocol Client
Interact with remote A2A agents: send tasks, stream results, get/cancel tasks.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional

import aiohttp

from agent.a2a.models import (
    AgentCard,
    Message,
    Task,
    TaskSendParams,
    TextPart,
)

logger = logging.getLogger(__name__)


class A2AClient:
    """Client for interacting with a remote A2A agent."""

    def __init__(self, agent_card: AgentCard, api_key: Optional[str] = None):
        self.agent_card = agent_card
        self.base_url = agent_card.url.rstrip("/")
        self.api_key = api_key
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            headers: Dict[str, str] = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=120),
                headers=headers,
            )
        return self._session

    async def send_task(
        self,
        message: Message,
        task_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Task:
        """
        Send a task synchronously and wait for the final result.

        Args:
            message: The user message.
            task_id: Optional task ID (auto-generated if omitted).
            session_id: Optional session ID.

        Returns:
            Completed Task object.
        """
        task_id = task_id or str(uuid.uuid4())
        params = TaskSendParams(
            id=task_id,
            sessionId=session_id,
            message=message,
        )
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tasks/send",
            "params": params.model_dump(exclude_none=True),
        }

        session = await self._get_session()
        url = f"{self.base_url}/tasks/send"
        logger.debug(f"[A2AClient] POST {url} task={task_id}")

        async with session.post(url, json=payload) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"A2A send_task failed: HTTP {resp.status} {text[:500]}")
            data = await resp.json()
            if "error" in data and data["error"]:
                raise RuntimeError(f"A2A RPC error: {data['error']}")
            result = data.get("result", {})
            return Task.model_validate(result)

    async def send_task_async(
        self,
        message: Message,
        task_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Task:
        """
        Send a task asynchronously (fire-and-forget style).
        Returns the initial task state.
        """
        task_id = task_id or str(uuid.uuid4())
        params = TaskSendParams(
            id=task_id,
            sessionId=session_id,
            message=message,
        )
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tasks/send",
            "params": params.model_dump(exclude_none=True),
        }

        session = await self._get_session()
        url = f"{self.base_url}/tasks/send"
        async with session.post(url, json=payload) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"A2A send_task_async failed: HTTP {resp.status} {text[:500]}")
            data = await resp.json()
            if "error" in data and data["error"]:
                raise RuntimeError(f"A2A RPC error: {data['error']}")
            result = data.get("result", {})
            return Task.model_validate(result)

    async def send_task_stream(
        self,
        message: Message,
        task_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Send a task with Server-Sent Events (SSE) streaming.
        Yields status updates and artifacts as they arrive.

        Args:
            message: The user message.
            task_id: Optional task ID.
            session_id: Optional session ID.

        Yields:
            Dict events: {"type": "status"|"artifact"|"error", ...}
        """
        task_id = task_id or str(uuid.uuid4())
        params = TaskSendParams(
            id=task_id,
            sessionId=session_id,
            message=message,
        )
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tasks/sendSubscribe",
            "params": params.model_dump(exclude_none=True),
        }

        session = await self._get_session()
        url = f"{self.base_url}/tasks/sendSubscribe"
        logger.debug(f"[A2AClient] SSE POST {url} task={task_id}")

        async with session.post(url, json=payload) as resp:
            if resp.status != 200:
                text = await resp.text()
                yield {"type": "error", "message": f"HTTP {resp.status}: {text[:500]}"}
                return

            async for line in resp.content:
                decoded = line.decode("utf-8").strip()
                if not decoded or not decoded.startswith("data: "):
                    continue
                data_str = decoded[6:]
                if data_str == "[DONE]":
                    break
                try:
                    event = json.loads(data_str)
                    yield event
                except json.JSONDecodeError:
                    continue

    async def get_task(self, task_id: str) -> Task:
        """Get current state of a task."""
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tasks/get",
            "params": {"id": task_id},
        }
        session = await self._get_session()
        url = f"{self.base_url}/tasks/{task_id}"
        async with session.get(url, json=payload) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"A2A get_task failed: HTTP {resp.status} {text[:500]}")
            data = await resp.json()
            if "error" in data and data["error"]:
                raise RuntimeError(f"A2A RPC error: {data['error']}")
            result = data.get("result", data)
            return Task.model_validate(result)

    async def cancel_task(self, task_id: str) -> Task:
        """Cancel a running task."""
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tasks/cancel",
            "params": {"id": task_id},
        }
        session = await self._get_session()
        url = f"{self.base_url}/tasks/{task_id}/cancel"
        async with session.post(url, json=payload) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"A2A cancel_task failed: HTTP {resp.status} {text[:500]}")
            data = await resp.json()
            if "error" in data and data["error"]:
                raise RuntimeError(f"A2A RPC error: {data['error']}")
            result = data.get("result", data)
            return Task.model_validate(result)

    @staticmethod
    def build_text_message(text: str, role: str = "user") -> Message:
        """Helper to build a simple text message."""
        return Message(role=role, parts=[TextPart(text=text)])

    async def close(self) -> None:
        """Close the underlying HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
