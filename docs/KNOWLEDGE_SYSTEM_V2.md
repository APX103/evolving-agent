# 知识提炼系统 v2.0 设计文档

> 状态: 已实现  
> 关联代码: `agent/semantic_detector.py`, `agent/quality_judge.py`, `agent/knowledge_graph.py`, `agent/signal_learner.py`, `agent/learner.py`, `agent/memory.py`, `agent/core.py`

---

## 一、为什么要升级？

### v1.0 的问题

```
SignalLearner          Learner                  Reflector
    │                     │                        │
    ▼                     ▼                        ▼
正则匹配"请记住"      整轮对话文本              知识库摘要
→ 调用 LLM 精炼       → LLM Few-shot 提取        → LLM 自我批评
    │                     │                        │
    ▼                     ▼                        ▼
漏报/误报严重         token 消耗大               没有质量校验
"我偏爱火锅" 漏了      重复提取已知道识            幻觉知识直接入库
主客体经常混淆         没有 confidence 分数        无法溯源
```

**具体痛点**:
1. **正则匹配**: `"我喜欢火锅"` 能命中，`"我比较偏爱火锅"` 就漏了；维护成本随语言变体指数增长
2. **整轮对话喂 LLM**: 一次学习消耗 3000+ tokens，且每次会话都重复问"你叫什么"，每次都重复提取
3. **没有质量评估**: LLM 把"我同事喜欢 Python"提取成"用户喜欢 Python"直接入库，没有纠错机制
4. **扁平文本存储**: "用户喜欢火锅"只是一句话，不是 `(用户, 喜欢, 火锅)`，无法做推理
5. **没有反馈闭环**: 用户纠正了错误，系统不知道哪条知识错了，下次继续犯

---

## 二、v2.0 架构总览

```
用户输入
    │
    ├── 第一层：语义信号检测 (SemanticSignalDetector)
    │   Embedding 向量匹配 → 意图分类
    │   相似度 > 0.78 命中
    │
    ├── 第二层：正则 fallback
    │   语义检测失败时，用正则兜底
    │
    ├── 第三层：结构化提取
    │   LLM 输出严格 JSON Schema (subject/predicate/object/confidence/temporal_state)
    │
    ├── 第四层：RAG 去重
    │   提取前先召回已有知识，避免重复
    │
    ├── 第五层：LLM-as-Judge 质检
    │   第二个 LLM 评估：幻觉？主客体混淆？时态错误？
    │
    ├── 第六层：知识图谱化
    │   存为 (subject, predicate, object) 三元组 + 元数据
    │
    └── 第七层：反馈闭环
        用户表扬 → confidence +0.05
        用户纠正 → confidence -0.2，标记 corrected
```

---

## 三、六大模块详解

### 3.1 语义信号检测 (SemanticSignalDetector)

**文件**: `agent/semantic_detector.py`

**原理**: 预定义每个意图的示例列表，计算平均 Embedding 作为"锚点向量"。用户输入时计算与各个锚点的余弦相似度，超过阈值即命中。

**代码核心**:
```python
def detect(self, text: str, threshold: float = 0.78) -> Optional[Tuple[str, float]]:
    query_vec = self.llm_client.embed(text)
    query_vec = query_vec[0] / (np.linalg.norm(query_vec[0]) + 1e-8)

    for intent, anchor in self._anchor_vectors.items():
        sim = float(np.dot(query_vec, anchor))
        if sim > best_sim and sim > threshold:
            best_intent = intent
    return best_intent, best_sim
```

**意图定义**:
| 意图 | 示例 |
|---|---|
| remember | "请记住", "记住", "别忘了", "记一下", "remember this" |
| preference_positive | "我喜欢", "我爱", "我偏好", "i like", "i prefer" |
| preference_negative | "我讨厌", "我不喜欢", "i hate", "i dislike" |
| identity | "我叫", "我的名字是", "我是做", "my name is" |
| correction | "不对", "错了", "应该是", "wrong", "incorrect" |
| urgency | "紧急", "快点", "urgent", "asap" |
| gratitude | "谢谢", "感谢", "thank you" |
| frustration | "烦死了", "无语", "frustrated" |

**优势**:
- `"我比较偏爱火锅"` → 与 `"我偏好"` 向量相似度 0.85 → 命中
- `"我干AI这一行"` → 与 `"我是做AI的"` 向量相似度 0.88 → 命中
- 支持中英混合，无需维护正则

**缓存**: 锚点向量缓存到 `storage/semantic_cache/intent_anchors.npy`，重启秒加载。

---

### 3.2 结构化提取 (Structured Extraction)

**文件**: `agent/learner.py`, `agent/signal_learner.py`

**原理**: 不用自由文本 prompt，强制 LLM 输出带 schema 的 JSON。

**Schema 字段**:
```json
{
  "subject": "用户",
  "predicate": "喜欢",
  "object": "火锅",
  "temporal_state": "current",
  "confidence": 0.92,
  "category": "preference",
  "content": "用户喜欢吃火锅"
}
```

**字段说明**:
| 字段 | 含义 | 取值范围 |
|---|---|---|
| subject | 主体 | "用户"、"助手"、"事实" 等 |
| predicate | 关系 | "喜欢"、"职业"、"纠正"、"知道" |
| object | 客体 | 具体值 |
| temporal_state | 时态 | `current` / `past` / `planned` / `negated` |
| confidence | 置信度 | 0.0 - 1.0，根据原文明确程度 |
| category | 类别 | `fact` / `preference` / `concept` / `lesson` |
| content | 自然语言 | 用于传统知识库和向量索引 |

**时态标记的作用**:
- `"我以前喜欢火锅，现在戒了"` → `(用户, 喜欢, 火锅, past)` + `(用户, 喜欢, 火锅, negated)`
- 避免"用户喜欢火锅"和"用户不喜欢火锅"直接冲突

---

### 3.3 增量提取 + RAG 去重

**文件**: `agent/learner.py`

**原理**: 每轮对话结束后立即处理（不用等 `/bye`），提取前先做 RAG 召回已有知识，LLM 明确被告知"这些已经知道了，只提取新的"。

**接口**:
```python
def learn_from_turn(self, user_input: str, assistant_response: str) -> Dict:
    # 1. RAG 召回
    existing = self.memory.search_knowledge(query=user_input, limit=5)

    # 2. 增量提取（prompt 里注入已有知识）
    extracted = self._extract_incremental(user_input, assistant_response, existing_context)

    # 3. 入库
    applied = self._apply_to_memory(filtered)
```

**对比**:
| 模式 | 触发时机 | token 消耗 | 实时性 |
|---|---|---|---|
| v1.0 会话级学习 | `/bye` 后 | ~4000 tokens/次 | 延迟 |
| v2.0 增量学习 | 每轮结束后 | ~800 tokens/次 | 实时 |

---

### 3.4 LLM-as-Judge 质量过滤

**文件**: `agent/quality_judge.py`

**原理**: 用第二个 LLM 做"质检员"。质检 prompt 要求评估:
1. **幻觉 (hallucination)**: 提取的知识是否有原文依据？
2. **主客体混淆 (subject_confusion)**: `"同事喜欢"` 是否被误记为 `"用户喜欢"`？
3. **时态错误 (temporal_error)**: `"以前喜欢"` 是否被误记为 `"现在喜欢"`？
4. **Unsupported inference**: `"用户喜欢火锅"→"用户喜欢辣"` 是否有足够依据？

**输出**:
```json
[
  {
    "index": 0,
    "is_valid": true,
    "confidence": 0.95,
    "reason": "用户明确说了'我叫张三'",
    "issue_type": null
  },
  {
    "index": 1,
    "is_valid": false,
    "confidence": 0.3,
    "reason": "原文说的是'同事喜欢'，不是用户",
    "issue_type": "subject_confusion"
  }
]
```

**过滤策略**:
- `is_valid=false` → 直接丢弃
- `confidence < 0.5` → 丢弃或存入草稿区
- 通过的知识注入 `_confidence` 字段入库

---

### 3.5 知识图谱化 (KnowledgeGraph)

**文件**: `agent/knowledge_graph.py`

**存储结构**:
```python
@dataclass
class Triple:
    subject: str           # "用户"
    predicate: str         # "喜欢"
    object: str            # "火锅"
    temporal_state: str    # "current"
    confidence: float      # 0.92
    source: str            # "session_learning"
    created_at: str
    updated_at: str
    access_count: int = 0
```

**索引**:
- `_index_by_subject`: 按主体倒排
- `_index_by_predicate`: 按关系倒排

**API**:
```python
# 查询
kg.query(subject="用户", predicate="喜欢", temporal_state="current")

# 简单推理（传递闭包）
kg.infer_related("用户", depth=2)
# 返回: [("喜欢 火锅 → 属于 川菜", "川菜", "用户 可能 喜欢 川菜")]

# 矛盾检测
kg.detect_contradiction(new_triple)
# 返回: [已有的矛盾三元组]

# 生成上下文文本
kg.to_context_string("用户", limit=10)
# 用于注入 LLM system prompt
```

**存储**: 本地 JSON (`storage/knowledge/graph/triples.json`)，零外部依赖。

---

### 3.6 自监督反馈闭环

**文件**: `agent/core.py` 中的 `_apply_feedback_to_knowledge`

**机制**:

```
用户输入
    │
    ├── "谢谢，这个方案很清晰" (positive)
    │   └── 召回本轮相关 knowledge → confidence +0.05 → access_count +2
    │
    └── "不对，我说的是 React 不是 Vue" (correction)
        ├── 召回 assistant_response 相关的 knowledge → confidence -0.2
        ├── 标记 _status: "corrected"
        ├── 写入 _correction_note: "用户说不对，是 React"
        └── 新增 lesson 知识: "用户纠正: 是 React 不是 Vue"
```

**长期效果**:
- 高频被认可的知识 → confidence → 1.0 → 优先召回
- 被纠正的知识 → confidence → 0.1 → 逐渐淘汰
- 系统自动"学会"哪些记忆是可靠的

---

## 四、数据流全景

### 单轮对话中的知识提炼

```
用户: "请记住我的狗叫豆豆，我喜欢吃火锅"
    │
    ▼
SemanticSignalDetector.detect()
    ├── "请记住我的狗叫豆豆" → remember (sim=0.91)
    └── "我喜欢吃火锅" → preference_positive (sim=0.89)
    │
    ▼
SignalLearner._execute_by_intent()
    ├── remember → LLM 提取结构化 JSON
    │   → {"subject":"用户","predicate":"拥有","object":"豆豆","temporal_state":"current"}
    │
    └── preference_positive → LLM 提取结构化 JSON
        → {"subject":"用户","predicate":"喜欢","object":"火锅","temporal_state":"current"}
    │
    ▼
QualityJudge.filter_valid()
    ├── 检查幻觉 → 原文有依据 → is_valid=true, confidence=0.95
    └── 检查主客体 → 正确 → is_valid=true, confidence=0.92
    │
    ▼
MemoryManager
    ├── 传统知识库: add_knowledge(category="fact", content="用户的狗叫豆豆")
    ├── 传统知识库: add_knowledge(category="preference", content="用户喜欢吃火锅")
    └── 知识图谱: knowledge_graph.add(Triple(subject="用户", predicate="拥有", object="豆豆"))
                  knowledge_graph.add(Triple(subject="用户", predicate="喜欢", object="火锅"))
    │
    ▼
用户: "谢谢！"
    │
    ▼
_apply_feedback_to_knowledge(positive)
    └── 召回 "用户的狗叫豆豆" / "用户喜欢吃火锅" → confidence +0.05
```

---

## 五、使用与扩展

### 5.1 动态添加新意图

```python
from agent.semantic_detector import SemanticSignalDetector

detector = SemanticSignalDetector(llm_client)
detector.add_intent("schedule", [
    "我明天要", "我计划", "我打算", "记得提醒我", "别忘了提醒我",
    "i need to", "remind me to", "i plan to"
])

result = detector.detect("我明天要去医院复查")
# → ("schedule", 0.86)
```

### 5.2 调整质检严格度

```python
from agent.quality_judge import QualityJudge

judge = QualityJudge(llm_client)
# 默认 confidence > 0.5 才入库
# 如果要更严格：
valid_items = [item for item in filtered if item.get("_confidence", 0) > 0.8]
```

### 5.3 知识图谱查询

```python
from agent.knowledge_graph import KnowledgeGraph

kg = KnowledgeGraph()

# 查用户所有当前偏好
kg.query(subject="用户", predicate="喜欢", temporal_state="current")

# 推理关联
kg.infer_related("用户", depth=2)

# 检测矛盾
new = Triple(subject="用户", predicate="喜欢", object="辣", temporal_state="current")
contradictions = kg.detect_contradiction(new)
```

### 5.4 切换回正则模式

如果 Embedding API 不可用，语义检测会自动退化：

```python
# SemanticSignalDetector.__init__ 中
if not self.llm_client:
    # fallback：_anchor_vectors 为空，detect() 返回 None
    # SignalLearner 会回退到正则匹配
```

---

## 六、性能与成本

| 操作 | Token 消耗 | 延迟 | 触发频率 |
|---|---|---|---|
| 语义信号检测 | 1 次 Embedding API | ~300ms | 每轮对话 |
| 实时结构化提取 | ~200 tokens prompt + ~100 tokens output | ~1-3s | 命中信号时 |
| 增量学习 | ~600 tokens prompt + ~200 tokens output | ~2-5s | 每轮对话 |
| LLM-as-Judge | ~800 tokens prompt + ~150 tokens output | ~2-4s | 提取后 |
| 知识图谱写入 | 本地 JSON，无 API 调用 | <10ms | 每次提取 |
| 会话级学习 | ~3000 tokens prompt + ~500 tokens output | ~5-15s | `/bye` 后 |

**优化建议**:
- 语义检测的锚点向量可缓存，重启后秒加载
- 增量学习可改为异步（后台线程），不阻塞回复
- 质检可批量处理（多条知识一次质检）

---

## 七、后续扩展方向

| 方向 | 现状 | 下一步 |
|---|---|---|
| **图数据库** | 本地 JSON | 可迁移到 Neo4j / 专业图数据库做复杂图查询 |
| **多模态知识** | 仅文本 | 支持图片、文件内容的知识提取 |
| **跨会话推理** | depth=2 的简单传递 | 引入 LLM 做复杂因果推理 |
| **知识衰减** | 基于时间的老化 | 基于 confidence + 访问频次的智能衰减 |
| **用户间隔离** | 单用户 | 按 user_id 分 knowledge_graph 实例 |
| **外部知识源** | 仅从对话学习 | 接入 Wikipedia / 文档 / API 做增强 |
