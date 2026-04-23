# Evolving Agent 架构文档

> 版本: v4.0  
> 定位: 从"聪明的对话伙伴"进化为"能独立完成复杂任务的个性化多 Agent 协作系统"

---

## 1. 设计哲学

- **Agent 不是工具，是关系**：核心目标不是"准确回答"，而是"建立长期关系"。人格状态机、情绪感知、关系档案贯穿始终。
- **学习即存在**：三层学习体系（实时信号 / 会话级 / 周期反思 / 程序记忆），贯穿整个生命周期。
- **能对话，更能执行任务**：从单轮 ReAct 进化为 Plan-and-Execute + 多 Agent 协作 + MCP 工具生态。
- **纯本地优先**：所有记忆、画像、反思均存储在本地 JSON + 向量索引中，不依赖外部数据库，隐私可控。
- **安全可控**：敏感操作人工审批 + 代码沙箱隔离 + 路径安全检查。

---

## 2. 系统架构总览

```
┌─────────────────────────────────────────────────────────────────────┐
│                        用户交互层                                     │
│  ┌─────────┐  ┌─────────┐  ┌─────────────────────────────────────┐  │
│  │   CLI   │  │   Web   │  │            飞书 Bot                  │  │
│  │ main.py │  │ FastAPI │  │  Webhook / WebSocket / Card / 审批   │  │
│  └────┬────┘  └────┬────┘  └─────────────────────────────────────┘  │
│       └─────────────┴─────────────────────┘                         │
│                      AgentRegistry.process()                         │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      多 Agent 协作层 (v4.0)                           │
│  ┌─────────┐  ┌─────────┐  ┌─────────────────────────────────────┐  │
│  │ Router  │  │Companion│  │         Specialized Agents          │  │
│  │ (调度员) │  │ (陪伴者) │  │  Coder / Researcher / Writer       │  │
│  └────┬────┘  └────┬────┘  │  Planner / Executor / Reviewer     │  │
│       │            │       └─────────────────────────────────────┘  │
│       └────────────┴──────────────────────────────────────────────┘  │
│                           HandoffProtocol                            │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      任务执行层                                       │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌───────────┐  │
│  │   Planner   │  │  Executor   │  │   Sandbox   │  │ Approval  │  │
│  │ (任务分解)   │  │ (计划执行)   │  │ (代码沙箱)   │  │ (人工审批) │  │
│  └─────────────┘  └─────────────┘  └─────────────┘  └───────────┘  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                 │
│  │ MCP Client  │  │   Skills    │  │  Checkpoint │                 │
│  │ (工具生态)   │  │ (插件系统)   │  │ (断点续跑)   │                 │
│  └─────────────┘  └─────────────┘  └─────────────┘                 │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      智能核心层                                       │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐  │
│  │ Memory   │ │Personality│ │ Emotion  │ │  Mood    │ │Relationship│ │
│  │(三层记忆)  │ │(人格状态机) │ │(情绪感知)  │ │(内在状态)  │ │ (关系档案) │ │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘  │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐               │
│  │ Signal   │ │ Learner  │ │ Reflector│ │Procedural│               │
│  │Learner   │ │(增量学习)  │ │(周期反思)  │ │ Memory   │               │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘               │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐                            │
│  │Knowledge │ │ Semantic │ │ Quality  │                            │
│  │ Graph    │ │ Detector │ │ Judge    │                            │
│  └──────────┘ └──────────┘ └──────────┘                            │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      基础设施层                                       │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌───────────┐  │
│  │  LLM Client │  │   Storage   │  │   Events    │  │ Scheduler │  │
│  │(同步+异步)   │  │(本地JSON)   │  │ (事件总线)   │  │(定时调度)   │  │
│  └─────────────┘  └─────────────┘  └─────────────┘  └───────────┘  │
│  ┌─────────────┐  ┌─────────────┐                                   │
│  │ContextMgr   │  │ WorldState  │                                   │
│  │(上下文管理)  │  │(环境认知)    │                                   │
│  └─────────────┘  └─────────────┘                                   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Agent 全生命周期状态机

```
初始化 (EvolvingAgent.__init__)
    │
    ├── 加载 Config
    ├── 初始化 LLM Client（同步/异步双模式）
    ├── 初始化 StorageBackend（LocalJsonStorage）
    ├── 初始化 MemoryManager（多用户隔离：storage/{user_id}/）
    ├── 初始化各子系统（Personality/Emotion/Mood/Relationship/...）
    ├── 初始化 MCP Client（如启用）
    ├── 初始化 Planner + Executor + Sandbox + Approval
    └── 初始化 WorldState + ProceduralMemory + CheckpointManager
    │
    ▼
会话开始 (start_session)
    │── 检查是否满足反思阈值 ──→ 触发 Reflector.reflect()
    │── 加载 ProceduralMemory 高置信度策略
    │── 重置 Mood / EmotionSensor 会话状态
    │── 发布 event: session.started
    │
    ▼
对话轮次 (chat)  ←────────────────────────┐
    │                                       │
    ├── 人格信号微调 (PersonalityEngine)     │
    ├── 情绪感知 (EmotionSensor.analyze)     │
    ├── Mood 更新 (AgentMood)                │
    ├── Skill 路由 / MCP 工具路由            │
    │   ├── 命中 → 执行 Skill / MCP Tool    │
    │   └── 未命中 → 进入多 Agent 调度      │
    │       ├── Router 意图分类              │
    │       ├── 选择 Specialist Agent        │
    │       ├── Agent.process()（可能触发 Planner+Executor）
    │       └── Handoff 返回                │
    ├── 记录到短期记忆 (MemoryManager)       │
    ├── 实时学习（SignalLearner + Learner）  │
    └── 发布 events: turn.* / emotion.*     │
                                            │
会话结束 (end_session)                      │
    │── 提取关系事件 (RelationshipLog)       │
    │── 保存会话到本地 JSON                  │
    │── 启动后台学习线程 (Learner)           │
    │── Checkpoint 自动保存（如启用）        │
    │── 发布 event: session.ended            │
    └───────────────────────────────────────┘
```

### 关键行为说明

- **会话是学习的边界**：短期记忆只在会话内存在，`/bye` 触发会话归档 + 后台学习。
- **反思是进化的边界**：每 N 个会话（默认 5）触发 `Reflector.reflect()`，进行自我批评、目标设定、人格再校准。
- **后台学习不阻塞对话**：学习在后台线程中运行，延迟到下一轮对话开始时打印日志。
- **多用户隔离**：按 `user_id` 生成独立 `storage/{user_id}/` 子目录。
- **MCP 连接按需建立**：`ainit_mcp()` 在启动时异步连接配置的 MCP Servers。

---

## 4. 单轮对话决策链

每一轮 `chat(user_input)` 内部的数据流与决策顺序：

```
用户输入
    │
    ▼
[1] PersonalityEngine.apply_signals()
    │   检测"简洁点""错了""很好"等信号词，实时微调人格维度
    │
    ▼
[2] EmotionSensor.analyze()
    │   调用 LLM 做深度情绪分析（表面 + 潜在情绪）
    │   输出: label, intensity, needs, subtle_signals
    │
    ▼
[3] AgentMood.update_from_interaction()
    │   根据用户情绪、反馈类型、轮次，更新 Agent 自身状态
    │   (energy / inspiration / caution / warmth)
    │
    ▼
[4] 记录 user 到短期记忆 (MemoryManager.add_turn)
    │
    ▼
[5] SkillRegistry.find_handler() / MCP Tool 路由
    │   按优先级遍历已注册 Skill，调用 can_handle()
    │   ├── 命中 → execute() → 直接返回字符串（不走 LLM）
    │   └── 未命中 → 继续
    │
    ▼
[6] 是否需要任务规划？
    │   ├── 是（多步骤、复杂任务）→ Planner.decompose() → Executor.run()
    │   └── 否 → 继续单轮对话
    │
    ▼
[7] 组装动态 system prompt
    │   包含: 身份声明 + 关系档案 + Mood 指令 + 自我认知 +
    │         人格行为指令 + 语义召回知识 + 情绪适配指令 +
    │         ProceduralMemory 高置信度策略 + WorldState 环境信息
    │
    ▼
[8] LLM 流式生成 (KimiLLMClient.chat stream=True)
    │   temperature 由 Personality + Mood 共同决定
    │   max_tokens 由 verbosity 维度决定
    │
    ▼
[9] finalize_response()（流式结束后）
    │   记录 assistant 回复到短期记忆
    │   触发 SignalLearner.on_turn_complete() 实时学习
    │   触发反馈闭环检测（"谢谢"/"不对"）
    │
    ▼
返回给调用方
```

---

## 5. 多 Agent 协作架构（v4.0）

### 5.1 核心组件

```
AgentRegistry（注册中心）
    │── register(agent)       按 priority 排序注册
    │── set_router(router)    设置意图分类器
    │── process()             统一入口：build_context → classify → select → execute
    └── list_agents()         元信息查询

RouterAgent（调度员）
    │── classify()            LLM 意图分类 → IntentClassification
    └── INTENT_AGENT_MAP      意图 → Agent 映射

BaseAgent（抽象基类）
    │── process()             处理用户输入（异步）
    │── can_handle()          返回置信度
    └── build_system_prompt() 基于 AgentContext 构建 prompt

Specialist Agents
    ├── CompanionAgent        陪伴者：日常对话、情感交流（temperature=0.8）
    ├── CoderAgent            程序员：代码编写、调试、文件操作（temperature=0.2）
    ├── ResearcherAgent       研究员：信息检索、调研（temperature=0.4）
    ├── WriterAgent           写手：文案、报告（temperature=0.6）
    ├── PlannerAgent          规划师：复杂任务分解（temperature=0.3）
    ├── ExecutorAgent         执行员：按计划调用工具（temperature=0.2）
    └── ReviewerAgent         审稿人：质量检查、反思（temperature=0.3）
```

### 5.2 Handoff 协议

- Agent 间不直接调用方法，通过 `working_memory` 共享状态。
- 每个 Handoff 携带完整上下文（`HandoffRequest` / `HandoffResult`）。
- 支持跨 Agent 学习成果收集（`learnings` 带 `source_agent` 标签）。

### 5.3 协作流程示例

```
用户: "帮我调研 Python 异步框架，写对比报告"
    │
    ▼
Router → intent: "research" + "write" → target: "planner"
    │
    ▼
PlannerAgent.process()
    ├── 分析任务复杂度 → 需要分解
    ├── decompose() → Plan(4 steps)
    └── 返回 HandoffRequest → Executor
    │
    ▼
ExecutorAgent.process()
    ├── 获取 Plan from working_memory
    ├── 按依赖执行步骤（并行无依赖步骤）
    │   ├── Step 1 → Handoff to Researcher → working_memory["research_results"]
    │   ├── Step 2 → Handoff to Researcher → working_memory["benchmark_data"]
    │   ├── Step 3 → Handoff to Writer (inject research_results)
    │   └── Step 4 → Handoff to Reviewer (inject draft_report)
    ├── 汇总结果
    └── 返回最终报告
```

---

## 6. 任务规划与执行（Plan-and-Execute）

### 6.1 Planner

- **触发条件**：用户输入包含多动作词（"然后""接着""先...再..."）或显式 `/plan` 命令。
- **输入**：用户请求 + 可用工具列表（从 WorldState 获取）。
- **输出**：`Plan` 对象（步骤列表 + 依赖关系）。
- **工具库**：llm / mcp:fetch / mcp:filesystem / sandbox / skill:*

### 6.2 Executor

- **执行模式**：串行（有依赖）+ 并行（无依赖）。
- **重试机制**：每步最多重试 2 次。
- **变量替换**：支持 `{{stepN.result}}` 和 `{{stepN.description}}` 跨步骤引用。
- **状态流转**：PENDING → RUNNING → SUCCESS / FAILED / RETRYING。

### 6.3 安全执行

```
工具调用前
    │
    ├── 是否需要审批？（ApprovalManager.requires_approval）
    │   ├── 是 → 请求用户确认（blocking/nonblocking/auto）
    │   └── 否 → 继续
    │
    ├── sandbox 工具？
    │   ├── SafePythonExecutor（受限 builtins + 静态安全扫描）
    │   └── DockerSandbox（完全隔离，无网络，128m 内存限制）
    │
    └── 继续执行
```

---

## 7. MCP 协议集成

### 7.1 架构

```
Config (mcp.servers)
    │
    ▼
MCPClient.connect_all()      # 异步连接所有 server
    │
    ├── StdioServerParameters  # stdio 传输
    ├── ClientSession.initialize()
    └── _refresh_tools()       # 拉取工具列表
    │
    ▼
MCPClient.list_tools()       # 统一工具发现
MCPClient.call_tool()        # 统一工具调用
    │
    ▼
MCPRouterSkill / MCPToolSkill  # 将 MCP Tool 接入 Skill 路由
```

### 7.2 配置示例

```yaml
mcp:
  enabled: true
  servers:
    - name: "filesystem"
      transport: "stdio"
      command: "npx"
      args: ["-y", "@modelcontextprotocol/server-filesystem", "/Users"]
    - name: "fetch"
      transport: "stdio"
      command: "uvx"
      args: ["mcp-server-fetch"]
```

---

## 8. 三层记忆系统 + 命名空间

### 8.1 数据流

```
┌─────────────────────────────────────────────────────────────┐
│                        记忆架构（v4.0）                        │
├─────────────┬─────────────┬─────────────────────────────────┤
│   短期记忆   │   工作记忆   │           长期记忆               │
│  short_term │ working_mem │  knowledge_base + vectors + graph│
├─────────────┼─────────────┼─────────────────────────────────┤
│ 当前会话    │  当前任务    │  跨会话知识 + 向量语义索引 + 图谱  │
│ List[dict]  │   Dict[str]  │   List[dict] + np.ndarray        │
│ 内存中      │   内存中     │  JSON + NPY + 图谱本地持久化      │
│ 会话结束    │  随任务结束  │   永久（自动老化清理）            │
│ 归档到文件  │   随任务归档  │   反思时 cleanup_stale_knowledge │
└─────────────┴─────────────┴─────────────────────────────────┘
```

### 8.2 多用户隔离

```
storage/
├── {user_id}/
│   ├── conversations/       # 会话归档
│   ├── knowledge/           # 知识库 + 向量索引 + 图谱
│   ├── user_profile/        # 用户画像
│   ├── personality/         # 人格状态
│   ├── relationship/        # 关系档案
│   ├── mood/                # Agent Mood
│   ├── procedural_memory/   # 程序记忆
│   └── checkpoints/         # 状态快照
└── logs/                    # 运行日志
```

### 8.3 知识写入链路（add_knowledge）

与 v3.1 相同：精确匹配 → 向量相似度匹配（cosine_sim > 0.85）→ 新增 → 知识图谱化。

### 8.4 记忆老化（cleanup_stale_knowledge）

- **触发时机**：每次反思时自动调用；用户可手动 `/clean` 触发。
- **清理规则**：`access_count < min_access` 且 `last_accessed < cutoff_days`。
- **保护规则**：category 为 `reflection` 或 `personality` 的知识永不删除。

---

## 9. 上下文分层架构（ContextManager）

### 9.1 六层架构（针对 RoPE Context Rot 优化）

```
Layer 0: System Prompt（~500 tokens）
  └─ Agent 身份 + 人格 + 情绪指令 + 关系上下文

Layer 1: Eternal Memory（~300 tokens）
  └─ 用户最核心的 3-5 条画像（自动提取，永不压缩）
  └─ 合并到 system prompt 内部（确保最强注意力）

Layer 2: Session Summaries（~800 tokens）
  └─ 过去每个会话的 LLM 生成摘要，按时间倒序
  └─ 持久化到磁盘，进程重启后自动加载

Layer 3: Working Context（~200 tokens）
  └─ 当前任务目标、用户最后需求、待办事项
  └─ 放在 short_term 之前的最末尾（最近位置）

Layer 4: Recent Turns（~1500 tokens）
  └─ 当前会话最近的完整对话轮次
  └─ 超限时：最旧 50% 轮次 → LLM 摘要 → 移至 Layer 2

Layer 5: Procedural Rules（~200 tokens）
  └─ 高置信度行为策略，上限 5 条
```

### 9.2 to_messages() 优化（防御 Lost-in-the-Middle）

```python
messages = [
    system_prompt（含 Eternal Memory 合并）,   # ← 最强注意力
    [working_context],                          # ← 当前任务，最近位置
    [procedural_rules],                         # ← 行为策略
    [session_summaries],                        # ← 历史信息，可容忍衰减
    ...short_term turns,                        # ← 最近对话，U形注意力优势
]
```

---

## 10. 学习体系

### 10.1 实时信号学习（SignalLearner）

- **触发时机**：每轮对话完成后 `finalize_response()` 中调用。
- **检测机制**：SemanticSignalDetector（Embedding 向量匹配，阈值 0.78）。
- **执行动作**：结构化提取 → QualityJudge 质检 → add_knowledge + KnowledgeGraph.add → update_profile → 人格微调。

### 10.2 增量学习（Learner）

- **触发时机**：每轮对话结束后实时处理（`learn_from_turn()`），无需等待 `/bye`。
- **策略分流**：casual / technical / corrected / planning / mixed。
- **RAG 去重**：提取前召回已有知识，只提取新增内容。

### 10.3 程序记忆（ProceduralMemory）

- **功能**：记录有效行为策略（如"用户问技术问题时先问技术栈"）。
- **注入方式**：高置信度策略自动注入 system prompt（Layer 5）。
- **存储**：`storage/{user_id}/procedural_memory/strategies.json`。

### 10.4 周期反思（Reflector）

- **触发条件**：`session_count > 0` 且 `session_count % threshold == 0`。
- **输入**：最近 25 条知识、用户画像、过往反思记录、程序记忆。
- **输出**：summary / strengths / weaknesses / growth_goals / personality_update。
- **副作用**：触发 `cleanup_stale_knowledge()` + 更新 procedural_memory。

---

## 11. 人格与情绪双循环

### 11.1 人格状态机（PersonalityEngine）

- **8 维动态参数**：verbosity, formality, humor, confidence, proactive, warmth, technical, directness。
- **调整来源**：信号词、情绪映射、明确反馈、反思输出。
- **LLM 参数映射**：
  - `get_temperature()`：confidence↑ → temperature↑；formality↑ → temperature↓。
  - `get_max_tokens()`：verbosity 决定 512/1024/2048/4096。

### 11.2 情绪感知（EmotionSensor）

- 每轮调用 LLM 做深度分析，识别"还行"背后可能是疲惫或敷衍。
- 输出应用：追加到 system prompt + 实时微调 PersonalityEngine。

### 11.3 Agent 自身 Mood（AgentMood）

- **4 维内在状态**：energy, inspiration, caution, warmth。
- **对 LLM 的影响**：生成自我认知文本注入 system prompt + 偏移 temperature。
- **5% 意外性**：随机触发 quirks，避免机械感。

---

## 12. Skill 插件系统

### 12.1 内置 Skills

| Skill | 触发 | 功能 |
|---|---|---|
| `/echo` | `/echo text` | 回声测试 |
| `/calc` | `/calc 表达式` | 安全数学计算（simpleeval） |
| `/read` | `/read 路径` | 读取文件（路径安全检查） |
| `/write` | `/write 路径\n内容` | 写入文件 |
| `/sh` | `/sh 命令` | 安全 Shell（白名单+黑名单） |
| `edit` | 代码编辑 | 精确编辑代码文件 |
| `map` | 代码结构 | 查看项目代码结构 |
| `grep` | 代码搜索 | 在代码库中搜索 |
| `test` | 测试运行 | 运行单元测试 |
| `git` | 版本控制 | Git 操作 |

### 12.2 MCP Tool 接入

MCP Client 发现的工具通过 `MCPRouterSkill` 和 `MCPToolSkill` 接入 Skill 路由，对 Agent 而言与内置 Skill 无差别。

---

## 13. 工程化扩展点

| 扩展需求 | 当前伏笔 | 实施方式 |
|---|---|---|
| 接入 OpenAI / Claude | `LLMClient` 接口 | 新建 `OpenAILLMClient`，注入 EvolvingAgent |
| 换 SQLite / Redis 存储 | `StorageBackend` 接口 | 新建 `SQLiteStorage`，注入各模块 |
| 新 Specialist Agent | `BaseAgent` 抽象基类 | 继承 BaseAgent，注册到 AgentRegistry |
| 新 MCP Server | `config.yaml` mcp.servers | 配置即接入 |
| 审计与监控 | `EventBus.publish()` | 订阅 `turn.*` / `session.*` 事件 |
| 异步后台学习 | `EventBus` + asyncio task | 将实时学习改为 async task queue |

---

## 14. 相关文档索引

| 文档 | 内容 |
|------|------|
| `README.md` | 项目简介与快速开始 |
| `docs/ARCHITECTURE.md` | 本文档：完整架构设计与数据流 |
| `ROADMAP.md` | 演进路线图与里程碑 |
| `SPEC.md` | v4.0 多 Agent 系统设计规格 |
| `GAP_ANALYSIS_2026.md` | 与行业最佳实践的差距分析 |
