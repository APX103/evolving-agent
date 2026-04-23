# Evolving Agent — 越聊越聪明的对话 Agent

一个基于 Kimi API 的本地对话 Agent，它会记住你们的对话，从中学习，不断进化。

## 特点

- **多 Agent 协作**：Router 自动调度 Companion/Coder/Researcher/Planner/Executor/Reviewer 等专业 Agent
- **MCP 协议支持**：接入标准化工具生态（文件系统、网页获取等），工具数量从 5 扩展到 50+
- **任务规划与执行**：Plan-and-Execute 分离，支持多步骤任务分解、并行执行、自动重试
- **代码沙箱**：SafePythonExecutor + Docker 隔离，安全执行复杂代码和数据处理
- **Human-in-the-Loop 审批**：敏感操作（Shell/文件写/网络请求）前暂停等待用户确认
- **分层记忆**：短期上下文 + 工作记忆 + 长期知识库（向量语义检索 + 知识图谱）
- **语义信号检测**：用 Embedding 向量匹配替代正则，捕捉 "我比较偏爱火锅" 等语言变体
- **增量学习**：每轮对话实时提取新知识，RAG 召回已知道识避免重复
- **结构化提取**：强制 LLM 输出 JSON Schema（subject/predicate/object/confidence/temporal_state）
- **LLM-as-Judge 质检**：第二遍 LLM 过滤幻觉、主客体混淆、时态错误
- **知识图谱**：(S,P,O) 三元组存储，支持时态标记、矛盾检测、传递推理
- **自监督反馈闭环**：用户表扬提升 knowledge confidence，纠正自动标记并记录修正
- **知识去重**：语义相似的知识自动合并，避免膨胀
- **记忆老化**：长期未访问的低频知识自动清理
- **人格状态机**：8 维动态性格参数，根据用户反馈实时微调
- **情绪感知**：每轮调用 LLM 做深度情绪分析，识别表面情绪与潜在需求
- **程序记忆**：记录有效行为策略，自动注入 system prompt（越用越"懂规矩"）
- **上下文压缩**：六层上下文架构 + 自动摘要，防御 Context Rot
- **Checkpoint**：Agent 状态快照，支持断点续跑与故障恢复
- **定时调度**：Cron 主动任务调度，Agent 可 24/7 后台自主运行
- **Skill 插件系统**：可扩展的能力模块（计算、文件读写、Shell、代码编辑、Git、测试等）
- **流式输出**：打字机效果回复，实时显示思考过程
- **纯本地存储**：所有记忆存在本地 JSON/向量/图谱，隐私可控

## 快速开始

1. 安装依赖
```bash
pip install -r requirements.txt
# 可选：本地 embedding fallback
pip install sentence-transformers
```

2. 配置 Kimi API Key
```bash
cp config.yaml.example config.yaml
# 编辑 config.yaml，填入你的 KIMI_API_KEY
```

3. 启动对话
```bash
python main.py                    # 经典模式（v3.2 兼容）
python main.py --mode multi       # 多 Agent 协作模式
python main.py --mode multi --user <user_id>  # 多用户隔离
```

## 项目结构

```
evolving-agent/
├── agent/                    # 核心 Agent 模块
│   ├── core.py               # 主 Agent：协调记忆、人格、Skill、对话、MCP、规划
│   ├── llm/                  # LLM 抽象层
│   │   ├── base.py           # LLMClient 接口定义
│   │   ├── async_client.py   # 异步 Kimi 客户端（aiohttp + 连接池）
│   │   └── kimi_client.py    # 同步/异步双模式 Kimi 封装
│   ├── memory/               # 分层记忆系统（v4.0 重构）
│   │   ├── base.py           # 记忆接口
│   │   ├── short_term.py     # 短期记忆（当前会话轮次）
│   │   ├── working.py        # 工作记忆（当前任务状态）
│   │   ├── long_term.py      # 长期记忆（知识库 + 向量索引 + 语义检索 + 去重）
│   │   ├── user_profile.py   # 用户画像
│   │   └── reflections.py    # 反思记录
│   ├── multi_agent/          # 多 Agent 协作系统（v4.0）
│   │   ├── base.py           # BaseAgent 抽象基类 + AgentContext/Handoff
│   │   ├── registry.py       # AgentRegistry（注册中心 + 路由调度）
│   │   ├── router.py         # RouterAgent（意图分类）
│   │   ├── companion.py      # CompanionAgent（陪伴者）
│   │   ├── coder.py          # CoderAgent（程序员）
│   │   ├── researcher.py     # ResearcherAgent（研究员）
│   │   ├── planner.py        # PlannerAgent（规划师）
│   │   ├── executor.py       # ExecutorAgent（执行员）
│   │   ├── reviewer.py       # ReviewerAgent（审稿人）
│   │   ├── context_manager.py # ContextManager（六层上下文 + 压缩）
│   │   └── handoff.py        # HandoffProtocol（Agent 间状态传递）
│   ├── skills_builtin.py     # 内置 Skills（计算、文件、Shell、代码编辑、Git 等）
│   ├── skills_dev/           # 开发专用 Skills（edit/grep/map/test/git）
│   ├── mcp_client.py         # MCP 协议客户端（官方 SDK，stdio/SSE）
│   ├── mcp_tool_skill.py     # MCP 工具路由为 Skill
│   ├── planner.py            # Planner（任务分解，Plan-and-Execute）
│   ├── executor.py           # Executor（计划执行，串行 + 并行 + 重试）
│   ├── sandbox.py            # Python 沙箱（simpleeval → SafePython → Docker）
│   ├── approval.py           # Human-in-the-Loop 敏感操作审批
│   ├── checkpoint.py         # Checkpoint / Durable Execution（断点续跑）
│   ├── procedural_memory.py  # 程序记忆（行为策略积累与注入）
│   ├── context_compressor.py # 上下文压缩与智能摘要
│   ├── world_state.py        # 世界状态（工具可用性、文件快照、资源追踪）
│   ├── scheduler.py          # Cron 主动调度器（定时任务）
│   ├── performance_monitor.py # 性能监控与指标收集
│   ├── learner.py            # 增量学习引擎（RAG 去重 + 结构化提取）
│   ├── signal_learner.py     # 实时信号学习（语义检测 + 结构化提取）
│   ├── semantic_detector.py  # 语义信号检测器（Embedding 意图匹配）
│   ├── quality_judge.py      # LLM-as-Judge 质量过滤
│   ├── knowledge_graph.py    # 知识图谱（S,P,O 三元组 + 推理 + 矛盾检测）
│   ├── reflector.py          # 反思进化模块（自我批评 + 人格再校准）
│   ├── personality.py        # 人格状态机（8 维动态参数 + 信号词实时调整）
│   ├── emotion.py            # 情绪感知（深度 LLM 分析）
│   ├── mood.py               # Agent 自身 Mood（4 维内在状态）
│   ├── relationship.py       # 关系档案（亲密度 / 信任度 / 事件日志）
│   ├── events.py             # 事件总线（模块间解耦）
│   ├── config.py             # 配置中心
│   └── storage/              # 存储抽象层
│       ├── base.py           # StorageBackend 接口
│       └── local_json.py     # 本地 JSON 原子写入 + 备份
├── bot/                      # 飞书机器人集成
│   ├── feishu_adapter.py     # 飞书 Bot 适配器（Webhook + WS）
│   ├── feishu_message.py     # 消息格式转换
│   ├── feishu_approval.py    # 飞书审批 Card
│   ├── feishu_ws_client.py   # WebSocket 长连接
│   └── session_lifecycle.py  # 会话生命周期管理（30min TTL）
├── web/                      # Web 服务
│   ├── app.py                # FastAPI 入口
│   ├── api.py                # WebSocket API + REST 端点
│   └── static/               # 前端静态文件
├── storage/                  # 本地记忆存储（运行时生成）
│   ├── {user_id}/            # 多用户隔离目录
│   │   ├── conversations/    # 会话归档
│   │   ├── knowledge/        # 知识库 + 向量索引 + 图谱三元组
│   │   ├── user_profile/     # 用户画像
│   │   ├── personality/      # 人格状态
│   │   ├── relationship/     # 关系档案
│   │   ├── mood/             # Agent Mood
│   │   ├── procedural_memory/ # 程序记忆
│   │   └── checkpoints/      # 状态快照
│   └── logs/                 # 运行日志
├── main.py                   # CLI 入口（classic / multi 双模式）
├── config.yaml               # 配置文件
└── requirements.txt
```

## 特殊命令

| 命令 | 功能 |
|---|---|
| `/bye` | 结束会话，触发后台学习 |
| `/stats` | 查看 Agent 成长统计 |
| `/mem` | 查看当前记忆摘要 |
| `/clean` | 手动清理陈旧知识 |
| `/skills` | 查看已注册 Skills |
| `/personality` | 查看当前人格状态 |
| `/agents` | 查看可用的 Agent 列表（多 Agent 模式） |
| `/help` | 显示帮助 |

## 核心机制

### 三层记忆

| 层级 | 作用 | 生命周期 |
|---|---|---|
| 短期记忆 | 当前对话上下文 | 当前会话 |
| 工作记忆 | 本次会话关键点 | 会话结束提炼 |
| 长期记忆 | 跨会话知识 + 向量索引 + 知识图谱 | 永久（自动老化） |

### 人格状态机（8维）

- **verbosity**: 啰嗦程度 → 影响回复长度
- **formality**: 正式程度 → 影响语气
- **humor**: 幽默倾向 → 影响风格
- **confidence**: 自信度 → 影响措辞 + LLM temperature
- **proactive**: 主动性 → 影响是否预判需求
- **warmth**: 温暖度 → 影响共情表达
- **technical**: 技术深度 → 影响专业程度
- **directness**: 直接程度 → 影响开门见山

### 实时信号学习

对话中检测到以下信号词时**立即学习**，不用等 `/bye`：
- `请记住...` → 提取为事实知识
- `我喜欢...` / `我讨厌...` → 记录偏好
- `我叫...` / `我是做...的` → 更新用户画像
- `不对` / `错了` / `应该是...` → 记录纠正教训
- `烦死了` / `气死了` → 人格自动调整为更谨慎

### Skill 插件系统

已内置 Skills：
- `/echo` — 回声测试
- `/calc 表达式` — 安全数学计算
- `/read 文件路径` — 读取文件（限于工作区/用户目录）
- `/write 文件路径\n内容` — 写入文件
- `/sh 命令` — 执行安全 Shell 命令（白名单限制）

自定义 Skill 只需继承 `Skill` 基类，实现 `can_handle()` 和 `execute()`。

### 流式输出 + 内心戏

- LLM 回复逐字显示（打字机效果）
- Skill 调用时显示 `[调用 Skill: xxx]`
- 人格调整时显示 `[人格微调: xxx→+0.1]`
- 实时学习时显示 `[实时学习: xxx → 结果]`

## License

MIT
