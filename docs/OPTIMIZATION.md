# Evolving Agent 优化项清单

> 生成时间: 2026-04-22  
> 基于代码库深度扫描 + 单元测试覆盖分析

---

## 一、高优先级 Bug（立即修复）

| # | 位置 | 问题 | 后果 | 修复方案 |
|---|------|------|------|----------|
| 1 | `semantic_detector.py:84-87` | 缓存加载时 `np.load(vec_cache_path)[i]` 假设向量顺序与 `dict.keys()` 严格一致。若 `SIGNAL_INTENT_EXAMPLES` 的 key 集合被修改，缓存会错乱 | 意图锚点向量错配，语义检测精度下降 | 将向量与 intent_name 成对存储（如 `np.save` 存结构化数组，或改用 `.npz` 带 key 存储） |
| 2 | `kimi_client.py:77-79` | `chat(stream=True)` 异常时返回 `_error_generator`，但 `main.py` 中区分 `isinstance(response, str)`，错误生成器会进入 else 分支被迭代 | 用户看到逐字输出的错误信息；异常生成器行为不可控 | 异常时返回字符串 `"[Kimi API 错误] ..."` 而非生成器；或在 `main.py` 和 `web/api.py` 中增加 `isgenerator` 判断 |
| 3 | `memory.py:207-213` | `_find_duplicate` 的子串匹配：`content_lower in item["content"].lower()` 可能过度匹配（如短文本 "我" 匹配所有含"我"的长知识） | 错误合并不相关的知识 | 增加最小长度限制（如子串 ≥ 10 字符），或改用编辑距离 / 语义相似度二次确认 |
| 4 | `skills_builtin.py:53,59` | `CalcSkill` 的 `eval` 虽限制 `__builtins__: None`，但 `()` 和 `[]` 等仍可能通过属性访问链执行恶意代码 | **安全风险**：理论上存在 eval 逃逸可能 | 替换为 `ast.literal_eval`（仅支持基本运算）或引入 `numexpr` / `simpleeval` 库 |
| 5 | `core.py:219` | `temperature += mood_adjustment` 后 `max(0.1, min(1.0, temperature))` 强制 temperature ≥ 0.1 | 无法使用 deterministic 模式（temperature=0） | 下限改为 `max(0.0, ...)`，允许 temperature=0 |

---

## 二、中优先级 Bug（近期修复）

| # | 位置 | 问题 | 后果 | 修复方案 |
|---|------|------|------|----------|
| 6 | `signal_learner.py:224` | `_execute_action` 中 `refined = self.llm_client.quick_chat(...).strip().strip("\"'")`，无法正确处理 markdown 代码块 | 结构化 JSON 解析失败，回退到扁平文本 | 复用 `Learner._clean_json()` 统一清理 markdown 包裹 |
| 7 | `mood.py:47-49` | `_load_state` 直接 `json.load(f)`，文件为空或损坏时抛异常，无 fallback | Agent 启动失败 | 增加 `try/except`，损坏时重置为默认状态 |
| 8 | `personality.py:79-82` | 同上，`_load_state` 无异常处理 | Agent 启动失败 | 同上 |
| 9 | `local_json.py:30-36` | `load_json` 在文件和 `.bak` 都损坏时抛出 `RuntimeError`，上层多数未捕获 | 模块初始化失败，Agent 无法启动 | 增加 `load_json` 的 fallback：损坏时返回 `{}` 并记录 error log |
| 10 | `web/api.py:36-38` | 每个 WebSocket 连接创建独立 `EvolvingAgent`，但 `Config` 是单例 | 多连接场景下配置变更不一致 | `Config` 提供 `reset()` 或改为非单例；Web 层按连接隔离配置 |
| 11 | `knowledge_graph.py:194-196` | `detect_contradiction` 中查找同一 predicate 不同 object 的冲突时，`pass` 未实现互斥类别判断 | 矛盾检测不完整，注释与实际逻辑不符 | 实现互斥类别映射（如 "是男生" vs "是女生"），或删除该未完成逻辑 |
| 12 | `memory.py:355-357` | `end_session()` 中直接用 `with open(...)` 写文件，未通过 `StorageBackend` | 破坏存储抽象层，切换存储后端时失效 | 改为 `self.storage.save_json(...)` |

---

## 三、代码层面优化

| # | 问题 | 影响 | 优化方案 |
|---|------|------|----------|
| 13 | **异常静默吞没** | 多处 `try...except Exception: pass`（signal_learner、finalize_response、_send_status 等），掩盖错误导致难以调试 | 至少记录 `logger.exception()`，区分可恢复异常和致命错误 |
| 14 | **重复的去重逻辑** | `_detect_quick_feedback` 在 `core.py` 和 `signal_learner.py` 中几乎相同 | 抽取到 `agent/utils.py` 的共享函数 |
| 15 | **硬编码阈值散落各处** | 0.85（向量去重）、0.78（语义检测）、0.55（搜索下限）、0.5（质检通过）等 | 集中到 `Config` 或常量模块，支持配置覆盖 |
| 16 | **print 与 logger 混用** | `memory.py`、`knowledge_graph.py`、`semantic_detector.py` 大量使用 `print()` | 统一使用 `logging.getLogger(__name__)` |
| 17 | **兼容层未清理** | `agent/kimi_client.py` 和 `agent/embedding.py` 已标记弃用但仍存在 | 彻底移除，更新所有 import |
| 18 | **Web 与 CLI 逻辑重复** | `web/api.py` 和 `main.py` 都实现了 `/bye`、`/stats`、`/personality` 等命令处理 | 抽取到 `agent/commands.py` 统一处理 |
| 19 | **config.yaml 与代码不同步** | README 说人格是"9维"，代码只有 8 维 | 统一文档与代码，或补全第 9 维 |
| 20 | **requirements.txt 不完整** | 缺少 `httpx`（kimi_client 直接 import），`sentence-transformers` 未标注为可选 | 补全依赖，用 `extras_require` 区分可选依赖 |

---

## 四、架构层面优化

| # | 问题 | 影响 | 优化方案 |
|---|------|------|----------|
| 21 | **同步学习阻塞回复** | 每轮 `finalize_response` 同步调用 SignalLearner + Learner + QualityJudge，增加 2-5s 延迟 | 将实时学习改为异步任务队列（`asyncio.create_task` 或后台线程池） |
| 22 | **每轮多次 LLM 调用** | 一轮对话最多触发 4 次 LLM 调用（情绪+增量学习+信号提取+质检） | ① 情绪分析缓存；② 增量学习与信号学习合并；③ 质检批量处理 |
| 23 | **缺乏多用户隔离** | `Config` 单例，`storage` 路径固定 | 按 `user_id` 动态生成 `storage/{user_id}/` 子目录 |
| 24 | **向量索引重建成本高** | 启动时长度不一致则重建全部向量（`O(n)` Embedding API 调用） | 增量重建：只计算新增/修改项的向量 |
| 25 | **知识图谱 O(n) 去重** | `KnowledgeGraph.add()` 线性扫描所有 triples | 用 `(S,P,O,temporal_state)` 作为 key 维护 `Dict` 索引 |
| 26 | **没有对话历史加载** | 新会话 `short_term` 始终为空 | 支持"续接上次会话"模式，或自动加载最近 N 轮 |
| 27 | **Skill 路由过于简单** | 只有关键词/正则匹配 | 引入 LLM-based 路由或 Embedding 相似度路由 |
| 28 | **配置单例全局污染** | `Config._instance = None` 在单元测试中造成状态污染 | 提供 `Config.reset()` 或改用依赖注入 |

---

## 五、功能层面优化

| # | 问题 | 影响 | 优化方案 |
|---|------|------|----------|
| 29 | **情绪分析无上下文** | `EmotionSensor.analyze()` 只接收当前文本 | 传入 `session_emotions` 摘要作为 context |
| 30 | **反馈闭环精度低** | `_apply_feedback_to_knowledge` 用 `search_knowledge(query=response, limit=3)` 召回，response 可能很长 | 只召回与 correction 相关的片段；或让用户明确指出哪部分不对 |
| 31 | **知识老化策略简单** | 仅基于时间和访问次数，未考虑 confidence 和重要性 | 综合 confidence、访问频次、时间、category 重要性做智能衰减 |
| 32 | **没有外部知识增强** | 所有知识仅从对话中学习 | 接入 RAG 管道，支持用户上传文档做知识增强 |
| 33 | **反思阈值固定** | `reflect_threshold=5` 固定值 | 根据会话长度、知识增量、用户反馈动态决定反思时机 |
| 34 | **缺少持久化的会话列表** | `main.py` 只能查看当前会话 | 在 CLI 和 Web 中增加 `/history` 命令和会话列表页面 |
| 35 | **LLM 输出无结构化保障** | 多处依赖 `json.loads()` 解析 LLM 输出，无类型校验 | 引入 Pydantic 模型做结构化输出验证 |

---

## 六、依赖优化建议

### 6.1 缺失的依赖声明

```diff
# requirements.txt
  openai>=1.0.0
  pyyaml>=6.0
  numpy>=1.24.0
  fastapi>=0.104.0
  uvicorn>=0.24.0
  websockets>=12.0
+ httpx>=0.27.0          # kimi_client.py 直接 import
```

### 6.2 可选依赖分组

```
# requirements.txt 保持不变
# 新增 requirements-web.txt
fastapi>=0.104.0
uvicorn>=0.24.0
websockets>=12.0

# 新增 requirements-dev.txt
pytest
black
ruff

# pyproject.toml 中 extras_require
[project.optional-dependencies]
web = ["fastapi>=0.104.0", "uvicorn>=0.24.0", "websockets>=12.0"]
local-embed = ["sentence-transformers>=2.0.0"]
dev = ["pytest", "black", "ruff"]
```

### 6.3 可替代方案评估

| 当前 | 替代 | 建议 |
|------|------|------|
| `openai` SDK | 原生 `httpx` | 保留 openai SDK，减少维护成本 |
| `numpy` | 纯 Python | **保留**，未来扩展 FAISS 等需要基础 |
| `fastapi` | `flask` | **保留**，FastAPI 的类型安全和性能更好 |
| `eval` in CalcSkill | `numexpr` / `simpleeval` | **替换**，消除安全风险 |

---

## 七、测试覆盖缺口

| 模块 | 当前测试 | 缺口 |
|------|----------|------|
| `core.py` | 集成测试 | 缺少单元测试（情绪+Mood+人格交互） |
| `personality.py` | 无 | 8 维参数调整逻辑未覆盖 |
| `emotion.py` | 无 | LLM mock 下的情绪分析未覆盖 |
| `mood.py` | 无 | 状态波动+随机 quirks 未覆盖 |
| `reflector.py` | 无 | 反思触发+输出解析未覆盖 |
| `skill.py` / `skills_builtin.py` | 无 | Skill 路由+各 Skill 执行未覆盖 |
| `relationship.py` | 无 | 亲密度计算未覆盖 |
| `storage/` | 无 | 原子写入+并发安全未覆盖 |

---

## 八、安全审计清单

| 检查项 | 状态 | 说明 |
|--------|------|------|
| `CalcSkill.eval` 逃逸风险 | ⚠️ | 需替换为安全表达式求值 |
| `ShellSkill` 命令注入 | ✅ | 白名单+黑名单双重过滤 |
| `FileWriteSkill` 路径穿越 | ✅ | `os.path.abspath` + 根目录检查 |
| API Key 存储 | ✅ | 存于 `config.yaml`（gitignored） |
| 用户输入直接拼接到 prompt | ⚠️ | `core.py` 中 `user_input` 直接进入 LLM prompt，需做长度限制和敏感信息过滤 |
| 存储文件权限 | ❓ | 未检查 JSON/NPY 文件权限（建议 `0o600`） |

---

## 九、修复优先级排序

### 本周（安全+稳定）
1. 修复 `CalcSkill.eval` 安全风险
2. 修复 `kimi_client.py` 异常生成器问题
3. 修复 `semantic_detector.py` 缓存加载顺序 bug
4. 修复 `memory.py` 子串匹配过度合并
5. 统一 `print` → `logging`

### 本月（性能+架构）
6. 实时学习异步化
7. 情绪分析 + 增量学习 LLM 调用合并
8. 知识图谱 Dict 索引优化
9. 向量索引增量重建
10. 引入 Pydantic 结构化输出

### 本季度（功能扩展）
11. MCP Client 集成
12. Plan-and-Execute 任务规划
13. 代码执行沙箱
14. 跨用户隔离
15. 外部文档 RAG 增强
