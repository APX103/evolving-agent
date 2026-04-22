"""
FastAPI 后端服务
WebSocket 实时聊天 + Agent 管理
"""
import asyncio
import json
import os
import sys
from typing import Dict

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse

# 将项目根目录加入路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.config import Config
from agent.core import EvolvingAgent

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
        self.agents[client_id] = EvolvingAgent(config_path)

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

            # 处理特殊命令
            if user_input == "/bye":
                agent.end_session()
                await manager.send_json(client_id, {
                    "type": "system",
                    "content": "会话已保存，后台学习中..."
                })
                continue

            if user_input == "/stats":
                stats = agent.get_stats()
                await manager.send_json(client_id, {
                    "type": "stats",
                    "data": stats
                })
                continue

            if user_input == "/personality":
                summary = agent.get_personality_summary()
                await manager.send_json(client_id, {
                    "type": "system",
                    "content": summary
                })
                continue

            # 发送"思考中"状态
            await manager.send_json(client_id, {"type": "thinking", "content": True})

            # 获取 Agent 回复
            response = agent.chat(user_input)

            # 处理 Skill 直接返回（字符串）
            if isinstance(response, str):
                await manager.send_json(client_id, {
                    "type": "message",
                    "role": "assistant",
                    "content": response,
                    "done": True
                })
                # 更新情绪状态显示
                await _send_status(client_id, agent)
                continue

            # 流式输出（生成器）
            full_text = ""
            await manager.send_json(client_id, {"type": "thinking", "content": False})

            for chunk in response:
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

            # 收尾：记录记忆 + 实时学习
            agent.finalize_response(user_input, full_text)

            # 发送状态更新
            await _send_status(client_id, agent)

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
        status = {
            "type": "status",
            "personality": agent.personality.get_all(),
            "mood": agent.mood.summary(),
            "emotion": agent.emotion_sensor.session_emotions[-1] if agent.emotion_sensor.session_emotions else None,
            "sessions": agent.memory.session_count,
            "knowledge": len(agent.memory.knowledge_base),
        }
        await manager.send_json(client_id, status)
    except Exception:
        pass


# 挂载静态文件
static_path = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_path):
    app.mount("/static", StaticFiles(directory=static_path), name="static")
