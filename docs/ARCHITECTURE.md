# Evolving Agent 架构文档

> 版本: v3.1  
> 定位: 越聊越聪明的对话 Agent，基于 Kimi API，纯本地存储，具备持续学习与自我进化能力。

---

## 1. 设计哲学

- **Agent 不是工具，是关系**：代码的核心目标不是"准确回答"，而是"建立长期关系"。为此引入关系档案、情绪感知、人格演化。
- **学习即存在**：没有学习能力的 Agent 只是 prompt 的复读机。本项目把学习拆为三层（实时信号 / 会话级 / 周期反思），贯穿整个生命周期。
- **纯本地优先**：所有记忆、画像、反思均存储在本地 JSON + 向量索引中，不依赖外部数据库，隐私可控。

---

## 2. Agent 全生命周期状态机

```
初始化 (EvolvingAgent.__init__)
    │
    ▼
会话开始 (start_session)
    │── 检查是否满足反思阈值 ──→ 触发 Reflector.reflect()
    │── 重置 Mood / EmotionSensor 会话状态
    │── 发布 event: session.started
    │
    ▼
对话轮次 (chat)  ←────────────────────────┐
    │                                       │
    ├── 人格信号微调 (PersonalityEngine)     │
    ├── 情绪感知 (EmotionSensor.analyze)     │
    ├── Mood 更新 (AgentMood)                │
    ├── Skill 路由 (SkillRegistry)           │
    │   ├── 命中 → 执行 Skill → 返回字符串   │
    │   └── 未命中 → 组装 system prompt     │
    │       └── LLM 流式生成               │
    ├── 记录到短期记忆 (MemoryManager)       │
    └── 发布 events: turn.* / emotion.*     │
                                            │
会话结束 (end_session)                      │
    │── 提取关系事件 (RelationshipLog)       │
    │── 保存会话到本地 JSON                  │
    │── 启动后台学习线程 (Learner)           │
    │── 发布 event: session.ended            │
    └───────────────────────────────────────┘
```

### 关键行为说明

- **会话是学习的边界**：短期记忆只在会话内存在，`/bye` 触发会话归档 + 后台学习。
- **反思是进化的边界**：每 N 个会话（默认 5）触发一次 `Reflector.reflect()`，进行自我批评、目标设定、人格再校准。
- **后台学习不阻塞对话**：`_background_learn` 在 daemon 线程中运行，学习日志通过 `_learning_logs` 队列延迟到下一轮对话开始时打印。

---

## 3. 单轮对话决策链

每一轮 `chat(user_input)` 内部的数据流与决策顺序如下：

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
[5] SkillRegistry.find_handler()
    │   按优先级遍历已注册 Skill，调用 can_handle()
    │   ├── 命中 → execute() → 直接返回字符串（不走 LLM）
    │   └── 未命中 → 继续
    │
    ▼
[6] 组装动态 system prompt
    │   包含: 身份声明 + 关系档案 + Mood 指令 + 自我认知 +
    │         人格行为指令 + 语义召回知识 + 情绪适配指令
    │
    ▼
[7] LLM 流式生成 (KimiLLMClient.chat stream=True)
    │   temperature 由 Personality + Mood 共同决定
    │   max_tokens 由 verbosity 维度决定
    │
    ▼
[8] finalize_response()（流式结束后）
    │   记录 assistant 回复到短期记忆
    │   触发 SignalLearner.on_turn_complete() 实时学习
    │
    ▼
返回给调用方
```

### 为什么是这个顺序？

- **信号词在情绪之前**：用户明确说"简洁点"是最高优先级指令，应覆盖情绪驱动的风格调整。
- **情绪在 Skill 之前**：情绪结果可能影响 Skill 路由（未来扩展），且情绪标签会打印给用户看，提供即时反馈。
- **Skill 在 LLM 之前**：计算、文件读写等 Skill 是确定性操作，不需要 LLM 参与，应短路避免浪费 token。
- **实时学习在 finalize 中**：只有拿到完整的 assistant_response 后，才能判断回复长度是否触发 verbosity 自动调整。

---

## 4. 三层记忆系统数据流

```
┌─────────────────────────────────────────────────────────────┐
│                        三层记忆架构                           │
├─────────────┬─────────────┬─────────────────────────────────┤
│   短期记忆   │   工作记忆   │           长期记忆               │
│  short_term │ working_mem │      knowledge_base + vectors    │
├─────────────┼─────────────┼─────────────────────────────────┤
│ 当前会话    │  本次关键点  │   跨会话知识 + 向量语义索引        │
│ List[dict]  │   Dict[str]  │   List[dict] + np.ndarray        │
│ 内存中      │   内存中     │   JSON + NPY 本地持久化          │
│ 会话结束    │  会话结束    │   永久（自动老化清理）            │
│ 归档到文件  │   随会话归档  │   反思时 cleanup_stale_knowledge │
└─────────────┴─────────────┴─────────────────────────────────┘
```

### 知识写入链路（add_knowledge）

```
add_knowledge(content)
    │
    ├── 1. 精确匹配（内容完全一致或互相包含，>15字符）
    │       ├── 命中 → merge_content() → update access_count → save
    │       └── 未命中 → 继续
    │
    ├── 2. 向量相似度匹配（cosine_sim > 0.85）
    │       ├── 命中 → merge_content() → rebuild_vector → save
    │       └── 未命中 → 继续
    │
    └── 3. 新增
            ├── 生成 ID，append 到 knowledge_base
            ├── save_json(knowledge_base)
            └── _append_vector(content) → save_vectors()
```

### 知识读取链路（search_knowledge）

```
search_knowledge(query)
    │
    ├── 1. 向量语义召回（top_k=limit*3，sim > 0.55）
    │       ├── 更新 access_count + last_accessed
    │       └── 结果加入 candidates
    │
    ├── 2. 字符串匹配兜底（若向量召回不足 limit/2）
    │       └── 子串匹配，去重后加入 candidates
    │
    ├── 3. 若无 query，按 access_count + last_accessed 排序返回热门知识
    │
    └── 4. 按相似度排序，返回前 limit 条
```

### 记忆老化（cleanup_stale_knowledge）

- **触发时机**：每次反思时自动调用；用户可手动 `/clean` 触发。
- **清理规则**：`access_count < min_access` 且 `last_accessed < cutoff_days` 的知识被删除。
- **保护规则**：category 为 `reflection` 或 `personality` 的知识永不删除。
- **向量同步**：删除知识后同步裁剪 `_vectors`，保持 knowledge_base 与向量索引长度一致。

---

## 5. 学习体系

### 5.1 实时信号学习（SignalLearner）

- **触发时机**：每轮对话完成后 `finalize_response()` 中调用。
- **检测机制**：正则模式匹配用户输入，捕获"请记住...""我喜欢...""我叫...""不对..."等信号。
- **执行动作**：
  - `add_knowledge`：调用 LLM 精炼提取内容，写入长期记忆。
  - `update_profile`：提取身份信息，更新用户画像。
  - `feedback_positive/negative`：触发人格微调。
- **开销**：每次命中信号都调用一次 `quick_chat()`（单条 LLM 请求），延迟约 300-800ms。

### 5.2 会话级学习（Learner）

- **触发时机**：`end_session()` 后启动后台线程执行。
- **策略分流**：根据对话内容自动判断类型（casual / technical / corrected / planning / mixed），决定学习重点。
- **提取内容**：
  - 用户画像更新（_extract_profile）
  - 新知识提取（_extract_knowledge）
  - 经验教训（_extract_lessons：successes / failures / improvements）
- **去重感知**：提取的知识通过 `MemoryManager.add_knowledge()` 写入，自动语义去重合并。

### 5.3 周期反思（Reflector）

- **触发条件**：`session_count > 0` 且 `session_count % threshold == 0`（默认 threshold=5）。
- **输入素材**：最近 25 条知识、用户画像、过往反思记录。
- **输出产物**：
  - `summary`：核心发现
  - `strengths / weaknesses`：优缺点（自我批评）
  - `growth_goals`：下阶段目标
  - `confidence_change`：建议的自信度调整
  - `personality_update`：文本性自我认知更新（写入 user_profile.agent_personality）
- **副作用**：触发 `cleanup_stale_knowledge()` 清理旧知识。

---

## 6. 人格与情绪双循环

### 6.1 人格状态机（PersonalityEngine）

- **8 维动态参数**：verbosity, formality, humor, confidence, proactive, warmth, technical, directness。
- **取值范围**：每维 0.0-1.0（confidence 最低 0.1），持久化到 `storage/personality/state.json`。
- **调整来源**：
  1. 信号词（SIGNAL_ADJUSTMENTS）：用户说"简洁点"→ verbosity -0.15。
  2. 情绪映射（EMOTION_RESPONSE_MAP）：用户愤怒→ verbosity -0.4, warmth +0.1。
  3. 明确反馈（adapt_from_feedback）：positive / negative / correction / enthusiasm / boredom。
  4. 反思输出（Reflector）：confidence_change 直接 adjust。
- **行为指令生成**：`get_behavior_instructions()` 将数值参数翻译为自然语言指令，注入 system prompt。
- **LLM 参数映射**：
  - `get_temperature()`：confidence↑ → temperature↑；formality↑ → temperature↓。
  - `get_max_tokens()`：verbosity 决定 512/1024/2048/4096。

### 6.2 情绪感知（EmotionSensor）

- **不是关键词匹配**：每轮调用 LLM 做深度分析，识别"还行"背后可能是疲惫或敷衍。
- **情绪标签**：疲惫、焦虑、兴奋、沮丧、愤怒、敷衍、好奇、平静、困惑。
- **输出应用**：
  - `get_response_instruction()` → 追加到 system prompt。
  - `get_style_adjustments()` → 实时微调 PersonalityEngine。

### 6.3 Agent 自身 Mood（AgentMood）

- **4 维内在状态**：energy, inspiration, caution, warmth。
- **波动因素**：
  - 长对话消耗 energy（>8 轮 -0.01，>15 轮 -0.03）。
  - 用户情绪感染（兴奋→ energy+；愤怒→ caution+）。
  - 用户反馈（positive→ energy+；correction→ caution+）。
  - 随机噪声（±0.02，模拟人的自然起伏）。
- **对 LLM 的影响**：
  - `get_instruction()` 生成"你今天感觉有点累"等自我认知文本，注入 system prompt。
  - `get_temperature_adjustment()` 根据 inspiration/caution/energy 偏移 temperature。
- **5% 意外性**：随机触发"突然想开个玩笑"等 quirks，避免机械感。

---

## 7. Skill 插件系统

```
Skill (ABC)
    │── name, description, triggers, priority
    │── can_handle(user_input, context) → bool
    │── execute(user_input, context) → SkillResult
    │
    ├── EchoSkill         (/echo)
    ├── CalcSkill         (/calc, 正则表达式)
    ├── FileReadSkill     (/read, 路径安全检查)
    ├── FileWriteSkill    (/write, 路径安全检查)
    └── ShellSkill        (/sh, 白名单+黑名单双校验)

SkillRegistry
    │── register(skill)   按 priority 排序
    │── find_handler()    顺序匹配，第一个命中即执行
    └── list_skills()     元信息查询
```

### 安全设计

- **CalcSkill**：正则过滤只允许数字和 `+-*/()^`，`eval` 在空 globals 下运行。
- **FileReadSkill / FileWriteSkill**：`os.path.abspath` 解析后，检查是否在允许根目录内（工作区、用户目录）。
- **ShellSkill**：
  - 黑名单正则拦截 `rm -rf`、`sudo`、`curl | sh` 等危险模式。
  - 白名单精确匹配第一个 token（`ls`、`git`、`python` 等），防止 `lsb_release` 命中 `ls` 前缀逃逸。
  - 超时 30 秒，限制输出长度 2000 字符。

---

## 8. 模块依赖图

```
┌──────────────────────────────────────────┐
│           EvolvingAgent (协调器)           │
│  ┌─────────────┐  ┌─────────────────────┐ │
│  │ MemoryManager│  │ PersonalityEngine   │ │
│  │ (三层记忆)   │  │ (8维人格状态机)      │ │
│  └──────┬──────┘  └─────────────────────┘ │
│         │                                 │
│  ┌──────┴──────┐  ┌──────────┐  ┌────────┐│
│  │ SkillRegistry│  │ AgentMood │  │RelationshipLog│
│  │ (插件路由)   │  │ (内在状态)│  │ (关系档案)   ││
│  └─────────────┘  └──────────┘  └────────┘│
│         │                                 │
│  ┌──────┴──────┐  ┌─────────────────────┐ │
│  │ SignalLearner│  │ EmotionSensor       │ │
│  │ (实时学习)   │  │ (情绪感知)          │ │
│  └─────────────┘  └─────────────────────┘ │
│         │                                 │
│  ┌──────┴──────┐  ┌─────────────────────┐ │
│  │ Learner      │  │ Reflector           │ │
│  │ (会话级学习) │  │ (周期反思)          │ │
│  └─────────────┘  └─────────────────────┘ │
│         │                                 │
│  ┌──────┴──────────────────────────────┐  │
│  │         KimiLLMClient (LLM 抽象)     │  │
│  │   chat / quick_chat / embed          │  │
│  └─────────────────────────────────────┘  │
│         │                                 │
│  ┌──────┴──────────────────────────────┐  │
│  │      LocalJsonStorage (存储抽象)      │  │
│  │   原子写入 + 线程锁 + 自动备份         │  │
│  └─────────────────────────────────────┘  │
└──────────────────────────────────────────┘
```

### 依赖原则

- **EvolvingAgent 是唯一的协调器**：各子系统不直接互相调用，通过 Agent 注入依赖。
- **LLM 与存储均被抽象**：`KimiLLMClient` 实现 `LLMClient` 接口，`LocalJsonStorage` 实现 `StorageBackend` 接口。
- **无环形依赖**：Memory 不依赖 Personality，Personality 不依赖 Emotion，所有交叉影响通过 Agent 中转。
- **事件总线解耦**：`EventBus` 允许模块订阅生命周期事件，无需硬编码回调。

---

## 9. 工程化扩展点

| 扩展需求 | 当前伏笔 | 实施方式 |
|---|---|---|
| 接入 OpenAI / Claude | `LLMClient` 接口 | 新建 `OpenAILLMClient`，注入 EvolvingAgent |
| 换 SQLite / Redis 存储 | `StorageBackend` 接口 | 新建 `SQLiteStorage`，注入各模块 |
| 多用户隔离 | `Config` 单例 + Storage 路径 | 按 user_id 动态生成 storage 子目录 |
| 异步后台学习 | `EventBus` + daemon thread | 将 `_background_learn` 改为 async task queue |
| 审计与监控 | `EventBus.publish()` | 订阅 `turn.*` / `session.*` 事件，写日志或推 webhook |
| 指标上报 | `EventBus` + `logging` | 按模块分级日志，便于聚合查询 |

---

## 10. 数据存储目录结构

```
storage/
├── conversations/      # 会话归档（session_*.json）
├── knowledge/
│   ├── knowledge_base.json   # 长期知识库
│   └── vectors.npy           # 向量索引
├── user_profile/
│   └── user_profile.json     # 用户画像
├── reflections/
│   └── reflections.json      # 反思记录
├── personality/
│   └── state.json            # 人格状态
├── relationship/
│   ├── events.json           # 关系事件
│   └── meta.json             # 亲密度 / 信任度
├── mood/
│   └── state.json            # Agent 自身 Mood
└── logs/
    └── agent.log             # 运行日志
```

所有 JSON 文件通过 `LocalJsonStorage` 原子写入（`.tmp` → `os.replace`），并保留 `.bak` 备份，崩溃后可恢复。
