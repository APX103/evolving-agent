# Evolving Agent — 越聊越聪明的对话 Agent

一个基于 Kimi API 的本地对话 Agent，它会记住你们的对话，从中学习，不断进化。

## 特点

- **分层记忆**：短期上下文 + 工作记忆 + 长期知识库（向量语义检索 + 知识图谱）
- **语义信号检测**：用 Embedding 向量匹配替代正则，捕捉 "我比较偏爱火锅" 等语言变体
- **增量学习**：每轮对话实时提取新知识，RAG 召回已知道识避免重复，无需等待 `/bye`
- **结构化提取**：强制 LLM 输出 JSON Schema（subject/predicate/object/confidence/temporal_state）
- **LLM-as-Judge 质检**：第二遍 LLM 过滤幻觉、主客体混淆、时态错误
- **知识图谱**：(S,P,O) 三元组存储，支持时态标记、矛盾检测、传递推理
- **自监督反馈闭环**：用户表扬提升 knowledge confidence，纠正自动标记并记录修正
- **知识去重**：语义相似的知识自动合并，避免膨胀
- **记忆老化**：长期未访问的低频知识自动清理
- **人格状态机**：9维动态性格参数，根据用户反馈实时微调
- **Skill 插件系统**：可扩展的能力模块（计算、文件读写、Shell 等）
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
python main.py
```

## 项目结构

```
evolving-agent/
├── agent/
│   ├── core.py          # 主 Agent：协调记忆、人格、Skill、对话
│   ├── kimi_client.py   # Kimi API 封装（支持流式输出）
│   ├── memory.py           # 分层记忆系统（向量索引 + 语义检索 + 去重合并 + 知识图谱）
│   ├── embedding.py        # Embedding 客户端（Kimi API / 本地 fallback）
│   ├── learner.py          # 增量学习引擎（RAG 去重 + 结构化提取 + 质量过滤）
│   ├── signal_learner.py   # 实时信号学习（语义检测 + 结构化提取）
│   ├── semantic_detector.py # 语义信号检测器（Embedding 意图匹配）
│   ├── quality_judge.py    # LLM-as-Judge 质量过滤
│   ├── knowledge_graph.py  # 知识图谱（S,P,O 三元组 + 推理 + 矛盾检测）
│   ├── reflector.py        # 反思进化模块（自我批评式 + 数值化人格调整）
│   ├── personality.py      # 人格状态机（9维动态参数 + 信号词实时调整）
│   ├── skill.py            # Skill 插件基类与注册中心
│   ├── skills_builtin.py   # 内置 Skills（计算、文件、Shell 等）
│   └── utils.py
├── storage/             # 本地记忆存储（自动生成）
│   ├── conversations/   # 对话历史
│   ├── knowledge/       # 知识库 + 向量索引 + 图谱三元组
│   ├── user_profile/    # 用户画像
│   ├── reflections/     # 反思日志
│   └── personality/     # 人格状态
├── main.py              # CLI 入口（流式输出 + 内心戏）
├── config.yaml          # 配置文件
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
| `/help` | 显示帮助 |

## 核心机制

### 三层记忆

| 层级 | 作用 | 生命周期 |
|---|---|---|
| 短期记忆 | 当前对话上下文 | 当前会话 |
| 工作记忆 | 本次会话关键点 | 会话结束提炼 |
| 长期记忆 | 跨会话知识 + 向量索引 + 知识图谱 | 永久（自动老化） |

### 人格状态机（9维）

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
