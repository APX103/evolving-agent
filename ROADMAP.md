# Evolving Agent 演进路线图

> 版本: v3.1 → v4.0  
> 时间跨度: 2026 Q2 - 2027 Q1  
> 目标: 从"聪明的对话伙伴"进化为"能独立完成复杂任务的个性化 Agent"

---

## 一、当前定位

Evolving Agent 是一个**有记忆、有情感、会进化**的个人陪伴型 Agent。在情感智能（人格状态机、情绪感知、关系档案）和持续学习（实时信号检测、增量知识提取、自监督反馈闭环）方面具有差异化优势。

### 已有能力
- ✅ 分层记忆系统（短期/工作/长期 + 向量语义检索 + 知识图谱）
- ✅ 语义信号检测（Embedding 意图匹配，替代正则）
- ✅ 增量学习 + RAG 去重（每轮实时提取，无需等待 `/bye`）
- ✅ LLM-as-Judge 质量过滤（幻觉/主客体混淆/时态错误检测）
- ✅ 知识图谱三元组（S,P,O + 时态标记 + 推理 + 矛盾检测）
- ✅ 自监督反馈闭环（表扬提升 confidence，纠正自动标记修正）
- ✅ 人格-情绪-关系三元驱动（8 维人格 + 9 种情绪 + 亲密度/信任度）
- ✅ 纯本地存储（隐私可控，零外部依赖）

---

## 二、能力缺口分析

通过与 LangGraph、CrewAI、OpenAI Agents SDK、MetaGPT、OpenManus、PydanticAI 等主流框架及 OpenAI Operator/Deep Research、Anthropic Computer Use 等工业实践对比，识别出以下关键缺口：

### 🔴 P0 — 决定 Agent 能否从"对话"进化为"执行任务"

| # | 缺口 | 行业标杆 | 影响 |
|---|------|----------|------|
| 1 | **无 MCP 协议支持** | Cursor / Claude Code / LangGraph 全原生支持 | 无法接入标准化工具生态，只能手写 Skill |
| 2 | **单轮 ReAct，无任务规划** | OpenManus / Deep Research 有计划-执行分离 | 无法处理"调研并写报告"类长程任务 |
| 3 | **无代码执行沙箱 + 浏览器** | Anthropic Computer Use / Smolagents | Agent 只能"说"，不能"做"和"查" |
| 4 | **无持久化 Checkpoint** | PydanticAI Durable Execution | 长任务失败需全部重来，无法断点续跑 |

### 🟡 P1 — 决定工程成熟度

| # | 缺口 | 行业标杆 |
|---|------|----------|
| 5 | 结构化输出无类型安全 | PydanticAI 强制 Schema 校验 |
| 6 | 无多用户/多会话隔离 | Mem0 四作用域模型 |
| 7 | 无可观测性/决策追踪 | LangSmith / OpenTelemetry |
| 8 | 无程序记忆（行为策略积累） | LangMem SDK |
| 9 | 单轨迹推理，无树搜索 | LATS / Tree of Thoughts |

### 🟢 P2 — 决定长期上限

| # | 缺口 | 行业标杆 |
|---|------|----------|
| 10 | 单 Agent 架构 | CrewAI / LangGraph 多 Agent 编排 |
| 11 | 无 A2A 协议支持 | Google A2A |
| 12 | 无 Skill Library + RL 自我改进 | SAGE / HyperAgents |
| 13 | 无自动上下文压缩 | Claude 长上下文自动 Compaction |
| 14 | 无 Human-in-the-Loop 审批 | Claude Code / PydanticAI |

---

## 三、四阶段演进路线

```
2026 Q2          2026 Q3          2026 Q4          2027 Q1
   │                │                │                │
   ▼                ▼                ▼                ▼
┌──────┐        ┌──────┐        ┌──────┐        ┌──────┐
│Phase1│   →    │Phase2│   →    │Phase3│   →    │Phase4│
│基础设施│        │记忆与│        │高级推理│        │自我│
│现代化 │        │可观测性│       │与多Agent│       │进化 │
└──────┘        └──────┘        └──────┘        └──────┘
```

---

### Phase 1：基础设施现代化（2026 Q2）

> **目标**：让 Agent 从"只能对话"进化为"能执行任务"  
> **时间**：1-2 个月  
> **投入**：中等（2-3 人月）

| 项目 | 描述 | 关键产出 |
|------|------|----------|
| **MCP Client 集成** | 实现 MCP 协议客户端，接入文件系统、浏览器、搜索等标准化工具 | `agent/mcp_client.py`，工具数量从 5 → 50+ |
| **PlanningFlow 任务规划** | 引入计划-执行分离架构，支持多步骤任务分解、跟踪、动态调整 | `agent/planner.py`，支持"调研→分析→写作→检查"类长程任务 |
| **代码执行沙箱** | 替换 `CalcSkill.eval` 为安全的 Docker/e2b 沙箱，支持复杂计算和数据处理 | `agent/sandbox.py`，消除 eval 安全风险 |
| **浏览器自动化** | 集成 Playwright，支持网页浏览、搜索、信息提取 | `agent/tools/browser.py`，Agent 能获取实时信息 |
| **Pydantic 结构化输出** | 所有 LLM 输出强制 Pydantic Schema 校验，替代手动 `json.loads()` | 解析错误率降低 50%+ |
| **Human-in-the-Loop** | 敏感操作（Shell/文件写/网络请求）前暂停，等待用户确认 | `agent/approval.py`，安全合规 |
| **高优先级 Bug 修复** | CalcSkill 安全、semantic_detector 缓存、异常静默吞没等 5 项 | 稳定性提升 |

**Phase 1 完成后，Agent 将能够**：
- "帮我查一下 React 19 的新特性，浏览官方文档，然后写一个可运行的示例"
- "计算这个 CSV 文件的平均值，并把结果保存到桌面"
- 执行失败时自动重试或请求用户帮助

---

### Phase 2：记忆与可观测性升级（2026 Q3）

> **目标**：让 Agent 更可靠、更可控、更懂用户  
> **时间**：2-3 个月  
> **投入**：中等（3-4 人月）

| 项目 | 描述 | 关键产出 |
|------|------|----------|
| **多用户隔离** | 按 `user_id` 动态生成 `storage/{user_id}/` 子目录，支持多用户 | `MemoryScope` 四作用域（user/session/run/app） |
| **程序记忆** | 记录有效的行为策略（如"用户问技术问题时先问技术栈"），自动注入 system prompt | `ProceduralMemory`，Agent 越用越"懂规矩" |
| **Checkpoint / Durable Execution** | 会话状态 snapshot，支持断点续跑、故障恢复 | `CheckpointManager`，长任务不再"一崩全毁" |
| **决策链追踪** | 可视化 Agent 的完整决策过程（thought → tool → observation → action） | OpenTelemetry / 自定义 Tracer，调试效率 10x |
| **自动上下文压缩** | 长对话智能摘要，保留关键决策点，避免 token 爆炸 | `ContextCompressor`，支持 100+ 轮对话 |
| **异步学习** | 实时学习从同步改为异步任务队列，降低对话延迟 | 回复延迟从 2-5s → <500ms |
| **实时学习合并** | 情绪分析 + 增量学习 LLM 调用合并为单次调用 | token 消耗降低 30% |

**Phase 2 完成后，Agent 将能够**：
- 多个用户独立使用，记忆完全隔离
- 长任务执行 30 分钟后断网，恢复后从断点继续
- 开发者清晰看到 Agent 每一步"在想什么"

---

### Phase 3：高级推理与多 Agent（2026 Q4）

> **目标**：突破单 Agent 能力天花板  
> **时间**：3-4 个月  
> **投入**：较高（4-6 人月）

| 项目 | 描述 | 关键产出 |
|------|------|----------|
| **Tree Search 推理** | 复杂决策时多路径探索（ToT / LATS），评估后选择最优 | `agent/reasoning/tot.py`，方案选择成功率提升 |
| **Planner + Executor 分离** | 引入专用 Planner Agent 做决策，Executor Agent 做执行 | 架构升级为多 Agent |
| **Specialist Agent** | 引入 Researcher / Coder / Writer 等专用 Agent | 各 Agent 专精一域 |
| **Skill Library** | 将成功的行为沉淀为可复用 Skill，后续任务优先检索 | `agent/skill_library/`，经验跨任务复用 |
| **A2A 协议支持** | 实现 Agent-to-Agent 通信，与其他 Agent 互操作 | Agent Card + 任务委托 |
| **动态 Handoff** | 根据任务类型自动路由到最合适的 Agent | 用户无感知切换 |

**Phase 3 完成后，Agent 将能够**：
- "帮我写一个爬虫，抓取这个网站的数据，然后分析并生成可视化报告" —— Planner 分解任务，Researcher 调研，Coder 写代码，Writer 写报告
- 自动选择最佳实现路径（Docker vs 直接部署 vs Serverless）

---

### Phase 4：自我进化（2027 Q1）

> **目标**：让 Agent 真正"学会学习"  
> **时间**：3-6 个月  
> **投入**：高（需要研究探索）

| 项目 | 描述 | 关键产出 |
|------|------|----------|
| **RL 自我优化** | 基于用户反馈的显式奖励，用强化学习优化策略 | 策略选择准确率持续提升 |
| **元认知改进** | Agent 能反思"我这次为什么学错了"，改进学习过程本身 | 学习效率指数级提升 |
| **领域专用模型微调** | 基于积累的数据做 SFT + RLHF，训练情感/陪伴专用模型 | 回复质量超越通用模型 |
| **自动工作流进化** | 类似 AFlow（ICLR 2025 Oral），MCTS 自动搜索最优工作流 | 工作流自我迭代优化 |

**Phase 4 完成后，Agent 将能够**：
- 根据你的使用习惯，自动调整学习策略（"这个用户喜欢直接给代码，以后少说废话"）
- 在情感陪伴领域的表现超越通用大模型

---

## 四、关键里程碑

| 里程碑 | 时间 | 验收标准 |
|--------|------|----------|
| **v3.2 — 能执行任务的 Agent** | 2026.06 | MCP 接入 ≥3 个 Server，PlanningFlow 支持 5+ 步骤任务，代码沙箱 + 浏览器可用 |
| **v3.5 — 可靠的 Agent** | 2026.09 | 多用户隔离，Checkpoint 支持断点续跑，决策链可视化，上下文压缩 |
| **v4.0 — 聪明的 Agent** | 2026.12 | 多 Agent 编排（Planner+3 Specialist），Skill Library，A2A 通信 |
| **v4.5 — 自我进化的 Agent** | 2027.03 | RL 策略优化，元认知，领域专用模型 |

---

## 五、风险与应对

| 风险 | 影响 | 应对策略 |
|------|------|----------|
| **MCP 生态不成熟** | 工具质量参差不齐 | 优先接入官方/高星 MCP Server，自建 fallback |
| **代码沙箱安全** | 用户代码可能逃逸 | 使用 Docker 隔离 + 资源限制（CPU/内存/网络），禁用危险系统调用 |
| **浏览器自动化不稳定** | 网页结构变化导致失败 | 多重 fallback：结构化数据 → 截图 OCR → 纯文本提取 |
| **多 Agent 协调复杂** | 通信开销、状态同步困难 | 渐进式：先 2 个 Agent（Planner+Executor），再扩展 |
| **API 成本激增** | MCP + 规划 + 沙箱 = 更多 LLM 调用 | 本地缓存、调用合并、模型降级（简单任务用轻量模型） |

---

## 六、对比：补齐后 vs 主流框架

| 维度 | 当前 | Phase 1-2 后 | Phase 3-4 后 | LangGraph | CrewAI |
|------|------|--------------|--------------|-----------|--------|
| **情感智能** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐ |
| **记忆系统** | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ |
| **工具生态** | ⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| **任务规划** | ⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| **多 Agent** | ⭐ | ⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| **可观测性** | ⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| **自我进化** | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ |

---

## 七、相关文档

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — 完整架构设计
- [docs/KNOWLEDGE_SYSTEM_V2.md](docs/KNOWLEDGE_SYSTEM_V2.md) — 知识提炼系统 v2.0
- [docs/OPTIMIZATION.md](docs/OPTIMIZATION.md) — 当前代码优化项清单（35 项）
- [docs/GAP_ANALYSIS.md](docs/GAP_ANALYSIS.md) — 与行业最佳实践的详细差距分析
- [tests/TEST_REPORT.md](tests/TEST_REPORT.md) — 测试进度报告

---

*本文档为对外发布版本，如有疑问请联系维护团队。*
