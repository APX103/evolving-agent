"""
FastAPI 后端服务
WebSocket 实时聊天 + Agent 管理
"""
import asyncio
import json
import logging
import os
import sys
from typing import Dict

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse

logger = logging.getLogger(__name__)

# 将项目根目录加入路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.config import Config
from agent.core import EvolvingAgent
from agent.observability import get_tracer
from agent.observability.jsonl_backend import JsonlBackend
from agent.observability.llm_logger import get_llm_logger
from agent.performance_monitor import get_performance_monitor

app = FastAPI(title="Evolving Agent Web")

# 配置单例（Web 模式下提前加载）
_config = Config()


# 活跃连接管理
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.agents: Dict[str, EvolvingAgent] = {}

    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self.active_connections[client_id] = websocket
        # 每个连接一个独立的 Agent 实例
        config_path = os.path.join(os.path.dirname(__file__), "..", "config.yaml")
        agent = EvolvingAgent(config_path)
        self.agents[client_id] = agent
        # 异步初始化 MCP（如果配置启用）
        try:
            await agent.ainit_mcp()
        except Exception as e:
            logger.warning(f"[Web] MCP 初始化失败: {e}")

    def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]
        if client_id in self.agents:
            del self.agents[client_id]

    async def send_json(self, client_id: str, data: dict):
        if client_id in self.active_connections:
            await self.active_connections[client_id].send_json(data)

manager = ConnectionManager()


@app.get("/", response_class=HTMLResponse)
async def get_index():
    """返回前端页面"""
    index_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    with open(index_path, "r", encoding="utf-8") as f:
        return f.read()


@app.get("/observability", response_class=HTMLResponse)
async def get_observability():
    """返回可观测性面板"""
    path = os.path.join(os.path.dirname(__file__), "static", "observability.html")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


@app.websocket("/ws/{client_id}")
async def websocket_chat(websocket: WebSocket, client_id: str):
    """WebSocket 聊天接口"""
    await manager.connect(websocket, client_id)
    agent = manager.agents[client_id]

    try:
        while True:
            # 接收用户消息
            raw = await websocket.receive_text()
            msg = json.loads(raw)
            user_input = msg.get("text", "").strip()

            if not user_input:
                continue

            # 为每条消息创建根 span
            tracer = get_tracer()
            span = tracer.start_span("websocket.message", attributes={
                "client_id": client_id,
                "input_length": len(user_input),
            })

            # 处理特殊命令
            if user_input == "/bye":
                agent.end_session()
                await manager.send_json(client_id, {
                    "type": "system",
                    "content": "会话已保存，后台学习中..."
                })
                span.end()
                continue

            if user_input == "/stats":
                stats = agent.get_stats()
                await manager.send_json(client_id, {
                    "type": "stats",
                    "data": stats
                })
                span.end()
                continue

            if user_input == "/personality":
                summary = agent.get_personality_summary()
                await manager.send_json(client_id, {
                    "type": "system",
                    "content": summary
                })
                span.end()
                continue

            # 发送"思考中"状态
            await manager.send_json(client_id, {"type": "thinking", "content": True})

            try:
                # 获取 Agent 回复
                response = await agent.chat(user_input)

                # 处理 Skill 直接返回（字符串）
                if isinstance(response, str):
                    await manager.send_json(client_id, {
                        "type": "message",
                        "role": "assistant",
                        "content": response,
                        "done": True
                    })
                    span.set_attribute("response_length", len(response))
                    span.set_attribute("response_type", "direct")
                    # 更新情绪状态显示
                    await _send_status(client_id, agent)
                    span.end()
                    continue

                # 流式输出（生成器）
                full_text = ""
                await manager.send_json(client_id, {"type": "thinking", "content": False})

                async for chunk in response:
                    full_text += chunk
                    await manager.send_json(client_id, {
                        "type": "stream",
                        "chunk": chunk
                    })
                    # 小延迟让前端有打字机效果
                    await asyncio.sleep(0.02)

                # 流式结束
                await manager.send_json(client_id, {
                    "type": "message",
                    "role": "assistant",
                    "content": full_text,
                    "done": True
                })
                span.set_attribute("response_length", len(full_text))
                span.set_attribute("response_type", "stream")

                # 收尾：记录记忆 + 实时学习
                agent.finalize_response(user_input, full_text)

                # 发送状态更新
                await _send_status(client_id, agent)
            except Exception as e:
                span.record_exception(e)
                await manager.send_json(client_id, {
                    "type": "error",
                    "content": f"服务器错误: {str(e)}"
                })
            finally:
                span.end()

    except WebSocketDisconnect:
        manager.disconnect(client_id)
    except Exception as e:
        await manager.send_json(client_id, {
            "type": "error",
            "content": f"服务器错误: {str(e)}"
        })
        manager.disconnect(client_id)


async def _send_status(client_id: str, agent: EvolvingAgent):
    """发送 Agent 状态到前端"""
    try:
        kg_count = 0
        if agent.memory.knowledge_graph:
            kg_count = len(agent.memory.knowledge_graph.triples)

        status = {
            "type": "status",
            "personality": agent.personality.get_all(),
            "mood": agent.mood.summary(),
            "emotion": agent.emotion_sensor.session_emotions[-1] if agent.emotion_sensor.session_emotions else None,
            "sessions": agent.memory.session_count,
            "knowledge": len(agent.memory.knowledge_base),
            "knowledge_graph": kg_count,
        }
        await manager.send_json(client_id, status)
    except Exception:
        pass


# ── 可观测性 API ──

@app.get("/api/traces")
async def list_traces(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
    """列出最近追踪"""
    backend = JsonlBackend()
    return backend.list_traces(limit=limit, offset=offset)


@app.get("/api/traces/{trace_id}")
async def get_trace(trace_id: str):
    """获取完整 trace 树"""
    backend = JsonlBackend()
    return backend.get_trace(trace_id)


@app.get("/api/metrics")
async def get_metrics():
    """聚合指标（最近 24h）"""
    llm_logger = get_llm_logger()
    perf = get_performance_monitor()
    llm_aggs = llm_logger.get_aggregates(hours=24)
    perf_summary = perf.get_summary()

    total_calls = llm_aggs.get("total_calls", 0)
    total_tokens = llm_aggs.get("total_tokens", 0)
    total_cost = llm_aggs.get("total_cost_usd", 0)
    avg_latency = llm_aggs.get("avg_latency_ms", 0)

    # 计算错误率（从 PerformanceMonitor）
    total_perf_calls = perf_summary.get("total_calls", 0)
    total_failed = perf_summary.get("total_failed", 0)
    error_rate = round(total_failed / total_perf_calls, 4) if total_perf_calls > 0 else 0

    return {
        "period_hours": 24,
        "total_calls": total_calls,
        "total_tokens": total_tokens,
        "total_cost_usd": total_cost,
        "avg_latency_ms": avg_latency,
        "error_rate": error_rate,
        "agents": perf_summary.get("agents", {}),
        "generated_at": perf_summary.get("generated_at"),
    }


@app.get("/api/metrics/agent/{agent_name}")
async def get_agent_metrics(agent_name: str):
    """单个 Agent 指标"""
    perf = get_performance_monitor()
    metrics = perf.get_metrics(agent_name)
    if not metrics:
        return {"agent_name": agent_name, "found": False}
    return {"agent_name": agent_name, "found": True, "metrics": metrics.to_dict()}


# 挂载静态文件
static_path = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_path):
    app.mount("/static", StaticFiles(directory=static_path), name="static")
