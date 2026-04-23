"""
A2A Protocol tests
Mock HTTP discovery and client request/response.
"""
import os
import sys
from unittest.mock import AsyncMock, patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI

from agent.a2a.models import (
    AgentCard,
    AgentCapability,
    AgentSkill,
    Message,
    Task,
    TaskState,
    TextPart,
)
from agent.a2a.discovery import AgentDiscovery
from agent.a2a.client import A2AClient
from agent.a2a.server import create_a2a_router


@pytest.fixture
def sample_agent_card() -> AgentCard:
    return AgentCard(
        name="TestAgent",
        description="A test external agent",
        url="http://localhost:9001",
        version="1.0.0",
        capabilities=AgentCapability(streaming=True),
        skills=[
            AgentSkill(
                id="math",
                name="Math Solver",
                description="Solves math problems",
                tags=["math", "calculation"],
            )
        ],
    )


@pytest.fixture
def mock_registry():
    reg = MagicMock()
    reg.process = AsyncMock(return_value=MagicMock(
        content="Hello from registry",
        agent_name="companion",
        metadata={},
    ))
    return reg


@pytest.mark.asyncio
async def test_discovery_fetch_success(sample_agent_card):
    discovery = AgentDiscovery(ttl_seconds=60)
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value=sample_agent_card.model_dump())

    mock_session = MagicMock()
    mock_session.get = AsyncMock(return_value=mock_response)
    mock_session.closed = False

    with patch.object(discovery, "_get_session", return_value=mock_session):
        card = await discovery.discover("http://localhost:9001")

    assert card is not None
    assert card.name == "TestAgent"
    assert card.url == "http://localhost:9001"
    await discovery.close()


@pytest.mark.asyncio
async def test_discovery_cache_hit(sample_agent_card):
    discovery = AgentDiscovery(ttl_seconds=60)
    discovery._cache["http://localhost:9001"] = discovery._CacheEntry(
        card=sample_agent_card, timestamp=__import__("time").time()
    )

    mock_session = MagicMock()
    mock_session.get = AsyncMock()

    with patch.object(discovery, "_get_session", return_value=mock_session):
        card = await discovery.discover("http://localhost:9001")

    assert card is not None
    assert card.name == "TestAgent"
    mock_session.get.assert_not_called()
    await discovery.close()


@pytest.mark.asyncio
async def test_discovery_all():
    discovery = AgentDiscovery(ttl_seconds=60)
    card1 = AgentCard(name="Agent1", description="D1", url="http://a1")
    card2 = AgentCard(name="Agent2", description="D2", url="http://a2")

    async def mock_discover(url):
        if "a1" in url:
            return card1
        return card2

    with patch.object(discovery, "discover", side_effect=mock_discover):
        cards = await discovery.discover_all(["http://a1", "http://a2"])

    assert len(cards) == 2
    names = {c.name for c in cards}
    assert names == {"Agent1", "Agent2"}
    await discovery.close()


@pytest.mark.asyncio
async def test_client_send_task(sample_agent_card):
    client = A2AClient(sample_agent_card)
    task_response = Task(
        id="task-123",
        state=TaskState.COMPLETED,
        messages=[
            Message(role="user", parts=[TextPart(text="hello")]),
            Message(role="agent", parts=[TextPart(text="hi there")]),
        ],
    )

    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value={
        "jsonrpc": "2.0",
        "id": 1,
        "result": task_response.model_dump(),
    })

    mock_session = MagicMock()
    mock_session.post = AsyncMock(return_value=mock_response)
    mock_session.closed = False

    with patch.object(client, "_get_session", return_value=mock_session):
        msg = A2AClient.build_text_message("hello")
        result = await client.send_task(msg)

    assert result.id == "task-123"
    assert result.state == TaskState.COMPLETED
    await client.close()


@pytest.mark.asyncio
async def test_client_get_task(sample_agent_card):
    client = A2AClient(sample_agent_card)
    task_data = Task(id="t1", state=TaskState.WORKING)

    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value={
        "jsonrpc": "2.0",
        "result": task_data.model_dump(),
    })

    mock_session = MagicMock()
    mock_session.get = AsyncMock(return_value=mock_response)
    mock_session.closed = False

    with patch.object(client, "_get_session", return_value=mock_session):
        task = await client.get_task("t1")

    assert task.id == "t1"
    await client.close()


@pytest.mark.asyncio
async def test_client_cancel_task(sample_agent_card):
    client = A2AClient(sample_agent_card)
    task_data = Task(id="t1", state=TaskState.CANCELED)

    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value={
        "jsonrpc": "2.0",
        "result": task_data.model_dump(),
    })

    mock_session = MagicMock()
    mock_session.post = AsyncMock(return_value=mock_response)
    mock_session.closed = False

    with patch.object(client, "_get_session", return_value=mock_session):
        task = await client.cancel_task("t1")

    assert task.state == TaskState.CANCELED
    await client.close()


def test_server_agent_card(mock_registry):
    app = FastAPI()
    router = create_a2a_router(mock_registry, agent_name="EvoTest")
    app.include_router(router)
    client = TestClient(app)

    response = client.get("/.well-known/agent.json")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "EvoTest"
    assert "capabilities" in data


def test_server_send_task(mock_registry):
    app = FastAPI()
    router = create_a2a_router(mock_registry)
    app.include_router(router)
    client = TestClient(app)

    payload = {
        "jsonrpc": "2.0",
        "id": 42,
        "method": "tasks/send",
        "params": {
            "id": "task-1",
            "message": {
                "role": "user",
                "parts": [{"type": "text", "text": "hello"}],
            },
        },
    }

    response = client.post("/tasks/send", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "result" in data
    assert data["result"]["state"] == "completed"
    mock_registry.process.assert_awaited_once()


def test_server_get_task(mock_registry):
    app = FastAPI()
    router = create_a2a_router(mock_registry)
    app.include_router(router)
    client = TestClient(app)

    payload = {
        "jsonrpc": "2.0",
        "id": 42,
        "method": "tasks/send",
        "params": {
            "id": "task-1",
            "message": {
                "role": "user",
                "parts": [{"type": "text", "text": "hello"}],
            },
        },
    }
    client.post("/tasks/send", json=payload)

    response = client.get("/tasks/task-1")
    assert response.status_code == 200
    data = response.json()
    assert data["result"]["id"] == "task-1"
