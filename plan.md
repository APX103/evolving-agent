# Evolving Agent 调试计划

## 项目概述
从 https://github.com/APX103/evolving-agent 拉取的 Agent 项目，包含 CLI、Web 后端、前端、飞书 Bot 等功能。

## 阶段 1: 环境搭建与依赖修复
- 创建 config.yaml（使用用户提供的配置）
- 安装 Python 依赖
- 检查 Python 版本兼容性（需 >=3.12）
- 运行初始测试，收集所有 ImportError/ModuleNotFoundError

## 阶段 2: 模块级修复（逐个模块调通）
- 修复所有 import 问题
- 修复缺失的模块/方法
- 修复 Pydantic v2 兼容性问题
- 修复 Config 单例模式问题

## 阶段 3: CLI 调通
- 经典模式 (python main.py)
- 多 Agent 模式 (python main.py --mode multi)
- 所有命令 (/bye, /stats, /mem, /clean, /skills, /personality, /help, /agents)

## 阶段 4: Web 后端调通
- FastAPI 服务启动 (python -m web.app)
- WebSocket 聊天接口
- REST API 接口 (/api/traces, /api/metrics)
- 可观测性面板

## 阶段 5: 前端调通
- 首页聊天界面
- WebSocket 连接与消息交互
- 状态面板显示
- 图片上传功能
- 暗黑模式
- 可观测性面板

## 阶段 6: 飞书 Bot 调通
- WebSocket 连接
- 事件处理
- 消息收发

## 阶段 7: 高级功能验证
- MCP 工具集成
- A2A 协议
- 多 Agent 协作
- 记忆系统
- 知识图谱
- Skills 系统

## 技能使用
- Stage 1-2: vibecoding-general-swarm（代码调试）
- Stage 3-7: vibecoding-general-swarm（功能验证）
