# Evolving Agent v4.x → 生产级补齐计划

> 基于 `docs/EVALUATION_REPORT_2026.html` 与代码库深度审计制定  
> 制定时间: 2026-04-23  
> 目标: 将框架从"功能完整的实验系统"升级为"可观测、可评估、可协作"的生产级多 Agent 平台

---

## 一、当前状态速览（基于代码审计）

| 维度 | 现状 | 与标杆差距 |
|------|------|-----------|
| **情感智能** | 8维人格+情绪+Mood+关系档案 | ⭐ 领先 |
| **持续学习** | 4层闭环（信号/增量/反思/程序） | ⭐ 领先 |
| **多Agent编排** | Router+Handoff，无图状态机 | ⚠️ 中等 |
| **MCP** | stdio SDK，基础工具发现 | ⚠️ 中等 |
| **可观测性** | PerformanceMonitor 存在但未接入，无 tracing | 🔴 **严重（3.5/10）** |
| **结构化输出** | 17+ 处 `json.loads()`，仅 3 处使用 Pydantic | 🔴 **严重（3.0/10）** |
| **评估体系** | 无 pytest，无 CI/CD，无 benchmark | 🔴 **严重（5.5/10）** |
| **A2A 互操作** | 完全缺失 | 🟡 中等（1.5/10） |

---

## 二、总体策略

**三阶段推进，每阶段有明确的可交付物和验收标准。**

- **Phase 1（生产基线，4-6 周）**：解决所有 P0 缺口，让系统"可被调试、可被评估、类型安全"。
- **Phase 2（生态互联，6-8 周）**：解决 P1 缺口中的 A2A 和编排升级，让系统"可协作、可扩展"。
- **Phase 3（企业加固，8-12 周）**：WASM 沙箱、向量数据库、RL 优化等长期能力。

---

## 三、Phase 1：生产基线（P0 全清）

### 3.1 结构化输出与类型安全（第 1-2 周）

**目标**：消灭所有裸 `json.loads()`，建立强制 Pydantic Schema 校验的 LLM 调用规范。

#### 3.1.1 统一结构化输出接口

- **新建/改造** `agent/llm/structured_client.py`：
  - 为 `LLMClient` 新增 `chat_structured(prompt, response_model: Type[T], ...) -> T` 方法
  - 内部先尝试原生 OpenAI `response_format={"type": "json_object"}`，失败后回退到 prompt 工程 + `model_validate_json`
  - 所有解析异常统一抛出 `StructuredOutputError`，含原始文本供调试

- **改造** `agent/structured_output.py`：
  - 将 `StructuredOutputExtractor` 重构为基于新的 `chat_structured` 接口
  - 保留 `extract_list` 等便捷方法，但底层走统一通道

#### 3.1.2 逐模块 Schema 化

按优先级逐个替换 17+ 处的 `json.loads()`：

| 优先级 | 文件 | Schema 模型 | 影响范围 |
|--------|------|------------|---------|
| P0 | `agent/multi_agent/router.py` | `IntentClassification`（已存在 dataclass，升级为 Pydantic） | 所有用户请求入口 |
| P0 | `agent/planner.py` | `PlanSchema` | 任务规划核心 |
| P0 | `agent/multi_agent/planner.py` | `PlannerDecision` | Agent 级规划 |
| P0 | `agent/emotion.py` | `EmotionAnalysisResult` | 情绪感知 |
| P1 | `agent/mcp_tool_skill.py` | `MCPRouterDecision` | MCP 工具路由 |
| P1 | `agent/signal_learner.py` | `SignalParseResult` | 信号学习 |
| P1 | `agent/reflector.py` | `ReflectionSchema` | 周期反思 |
| P1 | `agent/agent_reflector.py` | `AgentReflectionSchema` | Agent 反思 |
| P1 | `agent/learner.py` | `KnowledgeExtractionResult` | 增量学习 |
| P1 | `agent/skill_auto.py` | `SkillOptimizationSchema` | 技能优化 |
| P2 | `bot/*.py` | 各类 Webhook/WS 消息模型 | 飞书集成 |
| P2 | `web/api.py` | `WebSocketMessage` | Web 接口 |

- **验收标准**：`grep -r "json.loads" agent/ bot/ web/` 返回 0 个 LLM 输出解析场景（保留纯数据序列化用途）。

#### 3.1.3 配置 Schema 化

- **新建** `agent/config_models.py`：用 Pydantic `BaseModel` 定义 `AppConfig`、`LLMConfig`、`AgentConfig`、`MCPConfig` 等
- **改造** `agent/config.py`：加载 YAML 后通过 `AppConfig.model_validate()` 校验，运行时类型安全
- **验收标准**：配置缺失必填项时启动即报错，而非运行中 NPE。

#### 3.1.4 静态类型检查接入

- **新增** `pyproject.toml`：配置 `mypy`（或 `pyright`）基础规则
- **新增** `requirements-dev.txt`：`pytest`, `black`, `mypy`, `coverage`
- **验收标准**：`mypy agent/` 无 error-level 问题（warning 可逐步清理）。

---

### 3.2 可观测性体系建设（第 2-4 周）

**目标**：建立从 LLM Call → Agent 决策 → Tool 执行的全链路追踪，以及实时 Web 可视化。

#### 3.2.1 OpenTelemetry / Langfuse 追踪接入

- **新建** `agent/observability/tracing.py`：
  - 封装 `Tracer` / `Span` 抽象，底层可切换 OpenTelemetry SDK 或 Langfuse（默认 Langfuse，对 Agent 场景更友好）
  - 提供装饰器 `@trace_span(name, attributes)` 和上下文管理器 `with trace_span(...)`

- **接入点**（必须覆盖）：
  1. `LLMClient.chat()` / `achat()` —— 记录 prompt（采样）、response、latency、token usage、model name
  2. `AgentRegistry.process()` —— 记录 Router 决策、目标 Agent、输入摘要
  3. `BaseAgent.process()` —— 每个 Specialist Agent 的执行
  4. `HandoffProtocol.handoff()` —— 跨 Agent 调用链路
  5. `Executor.arun()` —— Plan 执行，每个 Step 一个子 Span
  6. `MCPClient.call_tool()` —— 工具调用，记录 server/tool/arguments/result
  7. `Skill.execute()` —— 内置技能执行
  8. `ApprovalManager.request()` —— 审批节点

- **Trace 结构示例**：
  ```
  session:{session_id}
    └─ turn:{turn_id}
         └─ agent:router
              └─ llm:intent_classification (latency=120ms, tokens=245)
         └─ agent:planner
              └─ llm:plan_decomposition (latency=890ms, tokens=1.2k)
         └─ agent:executor
              └─ step:1
                   └─ skill:code_sandbox (latency=2.3s)
              └─ step:2
                   └─ mcp:filesystem/read (latency=45ms)
  ```

- **改造** `PerformanceMonitor`：
  - 将其数据作为 Span Metrics 附加到对应 trace
  - 提供 `export_metrics()` 接口供外部面板拉取

#### 3.2.2 LLM Call 级详细日志

- **新建** `agent/observability/llm_logger.py`：
  - 可配置是否记录完整 prompt/response（默认采样 10%，敏感信息脱敏）
  - 记录 cost（按 model 的 $/1M tokens 计算）
  - 输出到独立日志文件 `storage/logs/llm_calls.jsonl`（JSON Lines，便于后续分析）

#### 3.2.3 可观测性 Web 面板

- **新建** `web/observability.py`：FastAPI 子路由，提供：
  - `/api/traces` —— 最近 trace 列表（按 session/turn/agent 过滤）
  - `/api/traces/{trace_id}` —— 单条 trace 树详情
  - `/api/metrics` —— 聚合指标（总调用数、平均延迟、token 消耗、错误率、成本）
  - `/api/metrics/agent/{name}` —— 单 Agent 指标

- **扩展** `web/static/index.html`：新增 "Observability" Tab：
  - 实时折线图：延迟 / token / 成本（按小时聚合）
  - Trace 瀑布图：类似 Chrome DevTools Network 面板
  - Agent 决策链可视化：router → planner → executor → tools

- **验收标准**：完成一次多 Agent 任务后，能在 Web 面板看到完整的决策链和每个 LLM Call 的延迟/token/cost。

---

### 3.3 评估基准体系（第 3-4 周）

**目标**：建立可量化的自动化评估，防止回归。

#### 3.3.1 测试基础设施现代化

- **新增** `pyproject.toml` / `pytest.ini`：启用 pytest 发现机制
- **迁移** `tests/` 下所有文件：将 `if __name__ == "__main__"` 改为 `def test_xxx()` + `pytest` 风格
- **新增** `tests/conftest.py`：共享 fixtures（临时 storage 目录、MockLLM、MockStorage）
- **新增** `.github/workflows/ci.yml`：GitHub Actions，跑 pytest + mypy

#### 3.3.2 自定义 Benchmark 框架

- **新建** `benchmarks/` 目录：
  - `benchmarks/framework/` —— 评估框架核心
    - `Task`：定义输入、期望输出、评估函数
    - `Runner`：执行 Agent 并收集结果
    - `Judge`：LLM-as-Judge 或规则判定
    - `Report`：生成对比报告
  - `benchmarks/tasks/` —— 具体任务集
    - `code_generation.py` —— 代码生成（HumanEval/MBPP 子集）
    - `tool_use.py` —— 工具调用正确率
    - `planning.py` —— 任务规划能力（多步骤依赖）
    - `emotion_consistency.py` —— 情感智能一致性
    - `memory_retrieval.py` —— 记忆检索准确率

- **验收标准**：`python -m benchmarks.run --suite=mini` 能在 5 分钟内跑完基础评估并输出分数。

#### 3.3.3 SWE-bench-lite 接入（可选，高优先级）

- **新建** `benchmarks/swe_bench/`：
  - 接入 SWE-bench-lite 子集（或模拟环境）
  - 由于完整 SWE-bench 需要 Docker + 真实 GitHub 仓库，可先实现 "mini 版"：给定函数签名和测试用例，评估 Agent 生成正确 patch 的能力

---

### 3.4 MCP 生产级加固（第 3-4 周，P1）

**目标**：补齐 Streamable HTTP 传输和工具调用审计。

#### 3.4.1 Streamable HTTP 传输

- **改造** `agent/mcp_client.py`：
  - 支持 `transport: "http"` 配置（SSE / Streamable HTTP）
  - 复用现有 aiohttp 连接池，保持 async-first 设计

#### 3.4.2 工具安全审计

- **新建** `agent/mcp_security.py`：
  - `ToolAuditor`：对每个 MCP 工具的 `input_schema` 进行静态分析，标记风险操作（文件删除、网络请求、命令执行）
  - `PolicyEnforcer`：按策略拒绝/审批高风险工具调用（与 `ApprovalManager` 集成）
  - 防御 **tool poisoning**（检测 schema 中是否有隐藏的危险字段）和 **rug pull**（运行时 schema 变更检测）

- **新建** `agent/mcp_budget.py`：
  - `ToolBudgetManager`：为每个会话/任务设置工具调用预算（次数 + 超时），防止无限循环

- **验收标准**：接入一个包含 `rm -rf` 类工具的 MCP Server 时，系统自动标记为高风险并触发审批。

---

## 四、Phase 2：生态互联（P1 核心）

### 4.1 A2A 协议客户端（第 5-6 周）

- **新建** `agent/a2a/`：
  - `agent/a2a/discovery.py` —— Agent Card 发现与缓存
  - `agent/a2a/client.py` —— A2A 任务委托客户端（HTTP + SSE）
  - `agent/a2a/models.py` —— A2A 协议 Pydantic 模型（Task, Message, Part, Artifact, Status）
  - `agent/a2a/server.py` ——（可选）让 Evolving Agent 暴露为 A2A Server，被外部 Agent 调用

- **集成**：在 `AgentRegistry` 中，当没有内部 Agent 能处理请求时，尝试通过 A2A 委托给外部 Agent。

### 4.2 多 Agent 编排升级（第 6-8 周）

**目标**：在保留现有 Router+Handoff 的基础上，引入条件分支和子图组合能力。

- **新建** `agent/workflow/`：轻量级工作流引擎（不引入 LangGraph 依赖，保持项目独立性）
  - `Graph` / `Node` / `Edge` / `Condition` 类
  - 支持：顺序执行、条件分支、循环重试、子图嵌套
  - 状态持久化：每个 Node 执行后自动 checkpoint（复用现有 `CheckpointManager`）

- **改造** `agent/plan.py` + `agent/executor.py`：
  - 将 `Plan` 的执行从 `while + ThreadPool` 迁移到 `Graph` 执行
  - `Step` 映射为 `Node`，`depends_on` 映射为 `Edge`
  - 新增条件边：`if step.status == SUCCESS -> next_step else fallback_step`
  - 新增循环边：`while step.result != valid -> retry`

- **新建** `agent/workflow/visualizer.py`：
  - 生成 Mermaid 图文本，便于在文档和面板中展示

### 4.3 可观测性面板增强（第 7-8 周）

- 在 Web 面板中新增 **Workflow 可视化**：实时展示 Graph 执行状态（节点高亮、条件分支路径）
- 新增 **Cost 预警**：当单次会话 token 消耗超过阈值时，WebSocket 推送警告

### 4.4 模型降级策略（第 7-8 周，P2）

- **新建** `agent/llm/router.py`：
  - `ModelRouter`：根据任务复杂度（通过 Router Agent 的 confidence 或字数估计）自动选择模型
  - 简单任务（问候、情感回应）→ 轻量模型 / 本地模型
  - 复杂任务（代码、规划）→ 大模型
  - 支持 fallback：大模型超时/失败时自动降级

---

## 五、Phase 3：企业级加固（P2 长期）

| 周次 | 任务 | 说明 |
|------|------|------|
| 9-10 | WASM 沙箱调研 | 评估 `wasmtime` / `wasmer` 替代 `SafePythonExecutor` 的可行性 |
| 10-12 | Playwright MCP Server | 浏览器自动化，支持截图、点击、表单填写 |
| 12-14 | 向量数据库迁移 | FAISS/Milvus 替代 numpy 向量存储，支持百万级检索 |
| 14-16 | RL Router 优化 | 根据历史 trace 数据，用 Bandit/RL 学习最优 Agent 调度策略 |

---

## 六、关键验收标准汇总

### Phase 1 出口标准
- [ ] 零裸 `json.loads()` 解析 LLM 输出
- [ ] `mypy agent/` 无 error
- [ ] 任意 Agent 任务可在 Langfuse/Web 面板看到完整 trace 树
- [ ] `pytest` 能发现并运行全部测试，`coverage >= 60%`
- [ ] `python -m benchmarks.run --suite=mini` 成功输出分数
- [ ] MCP HTTP 传输可用，高风险工具自动触发审批

### Phase 2 出口标准
- [ ] 能发现并调用外部 A2A Agent
- [ ] Plan 执行支持条件分支 + 循环重试
- [ ] Web 面板支持 Workflow 实时可视化
- [ ] 简单任务自动使用轻量模型，成本降低 30%+

### Phase 3 出口标准
- [ ] WASM 沙箱通过安全审计
- [ ] 支持百万级知识向量检索（<100ms）
- [ ] Router 调度准确率基于 RL 持续提升

---

## 七、实施建议与风险

### 并行策略
- **结构化输出** 和 **可观测性** 可完全并行（改动文件交集小）
- **评估体系** 可在前两者进行到中后期时启动（需要引用前两者的新接口做测试）
- **MCP 加固** 依赖可观测性中的 audit log 能力，建议在其之后或并行时预留接口

### 风险
| 风险 | 应对 |
|------|------|
| Pydantic 化导致大量回归 | 每改造一个模块，立即补充 pytest 单元测试 |
| Tracing 引入性能开销 | 采用采样（默认 10%），生产环境可关闭详细 prompt 记录 |
| Langfuse 依赖外部服务 | 封装抽象层，支持切换为本地 JSONL / OpenTelemetry |
| A2A 协议仍处草案阶段 | 关注 Google A2A 仓库更新，保持模型层独立 |

---

## 八、相关文档索引

- [docs/EVALUATION_REPORT_2026.html](EVALUATION_REPORT_2026.html) — 完整评估报告
- [docs/ARCHITECTURE.md](ARCHITECTURE.md) — 系统架构
- [ROADMAP.md](../ROADMAP.md) — 长期路线图
- [GAP_ANALYSIS_2026.md](../GAP_ANALYSIS_2026.md) — 差距分析
