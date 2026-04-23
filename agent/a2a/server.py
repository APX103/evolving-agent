"""
A2A Protocol Server
FastAPI router exposing Evolving Agent as an A2A-compatible agent.
Routes received tasks through the internal AgentRegistry.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from agent.a2a.models import (
    AgentCard,
    AgentCapability,
    AgentSkill,
    Artifact,
    Message,
    Task,
    TaskSendParams,
    TaskState,
    TextPart,
)

logger = logging.getLogger(__name__)


def create_a2a_router(
    registry: Any,
    agent_name: str = "Evo",
    agent_description: str = "Evolving Agent - adaptive multi-agent system",
    skills: Optional[list] = None,
) -> APIRouter:
    """
    Create a FastAPI router with A2A endpoints.

    Args:
        registry: AgentRegistry instance (or any object with async process method).
        agent_name: Name to expose in the AgentCard.
        agent_description: Description to expose in the AgentCard.
        skills: Optional list of skill dicts for the AgentCard.

    Returns:
        Configured APIRouter.
    """
    router = APIRouter()
    skills = skills or []

    # In-memory task store (simplified; production should use persistent store)
    _tasks: Dict[str, Task] = {}

    agent_card = AgentCard(
        name=agent_name,
        description=agent_description,
        url="",  # Will be set dynamically if needed
        version="1.0.0",
        capabilities=AgentCapability(
            streaming=True,
            pushNotifications=False,
            stateTransitionHistory=False,
        ),
        skills=[AgentSkill.model_validate(s) for s in skills],
    )

    @router.get("/.well-known/agent.json")
    async def get_agent_card(request: Request):
        """Return the Agent Card metadata."""
        card = agent_card.model_copy()
        if not card.url:
            # Derive base URL from request
            base_url = str(request.base_url).rstrip("/")
            card.url = base_url
        return card.model_dump(exclude_none=True)

    @router.post("/tasks/send")
    async def send_task(request: Request):
        """Receive a task, route it through the internal registry, and return result."""
        body = await request.json()
        params = _extract_params(body)
        if not params:
            return JSONResponse(
                status_code=400,
                content={"jsonrpc": "2.0", "id": body.get("id"), "error": {"code": -32602, "message": "Invalid params"}},
            )

        task = Task(
            id=params.id,
            sessionId=params.sessionId,
            state=TaskState.WORKING,
            messages=[params.message],
        )
        _tasks[task.id] = task

        try:
            # Extract text from message parts
            user_input = _extract_text(params.message)
            user_id = params.sessionId or "a2a_anonymous"

            # Route through internal registry
            response = await registry.process(user_input, user_id=user_id, source="a2a")

            # Build result task
            result_message = Message(
                role="agent",
                parts=[TextPart(text=response.content)],
                metadata=response.metadata,
            )
            task.messages.append(result_message)
            task.state = TaskState.COMPLETED
            task.artifacts.append(
                Artifact(
                    name="response",
                    parts=[TextPart(text=response.content)],
                    metadata={"agent_name": response.agent_name},
                )
            )
            _tasks[task.id] = task

            return {"jsonrpc": "2.0", "id": body.get("id"), "result": task.model_dump(exclude_none=True)}
        except Exception as e:
            logger.exception("[A2AServer] Task processing failed")
            task.state = TaskState.FAILED
            task.status = {"message": {"role": "agent", "parts": [TextPart(text=f"Error: {e}")]}}
            _tasks[task.id] = task
            return {"jsonrpc": "2.0", "id": body.get("id"), "result": task.model_dump(exclude_none=True)}

    @router.post("/tasks/sendSubscribe")
    async def send_task_subscribe(request: Request):
        """Receive a task and stream updates via SSE."""
        body = await request.json()
        params = _extract_params(body)
        if not params:
            return JSONResponse(
                status_code=400,
                content={"jsonrpc": "2.0", "id": body.get("id"), "error": {"code": -32602, "message": "Invalid params"}},
            )

        task_id = params.id
        user_id = params.sessionId or "a2a_anonymous"
        user_input = _extract_text(params.message)

        async def event_stream():
            task = Task(
                id=task_id,
                sessionId=params.sessionId,
                state=TaskState.WORKING,
                messages=[params.message],
            )
            _tasks[task_id] = task

            # Yield initial status
            yield _sse_event({
                "jsonrpc": "2.0",
                "id": body.get("id"),
                "result": {
                    "id": task_id,
                    "status": {"state": TaskState.WORKING, "message": {"role": "agent", "parts": [{"type": "text", "text": "Processing..."}]}},
                },
            })

            try:
                response = await registry.process(user_input, user_id=user_id, source="a2a")
                result_message = Message(
                    role="agent",
                    parts=[TextPart(text=response.content)],
                    metadata=response.metadata,
                )
                task.messages.append(result_message)
                task.state = TaskState.COMPLETED
                task.artifacts.append(
                    Artifact(
                        name="response",
                        parts=[TextPart(text=response.content)],
                        metadata={"agent_name": response.agent_name},
                    )
                )
                _tasks[task_id] = task

                yield _sse_event({
                    "jsonrpc": "2.0",
                    "id": body.get("id"),
                    "result": {
                        "id": task_id,
                        "status": {"state": TaskState.COMPLETED, "message": result_message.model_dump()},
                        "artifact": {
                            "name": "response",
                            "parts": [{"type": "text", "text": response.content}],
                        },
                    },
                })
            except Exception as e:
                logger.exception("[A2AServer] Streaming task failed")
                task.state = TaskState.FAILED
                _tasks[task_id] = task
                yield _sse_event({
                    "jsonrpc": "2.0",
                    "id": body.get("id"),
                    "result": {
                        "id": task_id,
                        "status": {"state": TaskState.FAILED, "message": {"role": "agent", "parts": [{"type": "text", "text": f"Error: {e}"}]}},
                    },
                })

            yield "data: [DONE]\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @router.get("/tasks/{task_id}")
    async def get_task(task_id: str):
        """Get the current state of a task."""
        task = _tasks.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        return {"jsonrpc": "2.0", "id": None, "result": task.model_dump(exclude_none=True)}

    return router


def _extract_params(body: Dict[str, Any]) -> Optional[TaskSendParams]:
    """Extract and validate TaskSendParams from JSON-RPC body."""
    params = body.get("params")
    if not params:
        return None
    try:
        return TaskSendParams.model_validate(params)
    except Exception:
        return None


def _extract_text(message: Message) -> str:
    """Extract plain text from message parts."""
    texts = []
    for part in message.parts:
        if part.type == "text":
            texts.append(part.text)
    return "\n".join(texts)


def _sse_event(data: Dict[str, Any]) -> str:
    """Format a dict as an SSE data event."""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
