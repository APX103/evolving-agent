# Evolving Agent 手动测试手册

> 适用版本: v3.1  
> 测试方式: 交互式手动验证  
> 预计用时: 15-20 分钟

---

## 前置准备

```bash
cd /Users/apx103/work/evolving-agent
source .venv/bin/activate   # 或直接用 .venv/bin/python
```

确认 `config.yaml` 已配置：
- `api_key`: 你的 `sk-kimi-...` token
- `base_url`: `https://api.kimi.com/coding/v1`
- `model`: `kimi-for-coding`
- `user_agent`: `KimiCLI/1.3`

> ⚠️ **关键**: 当前 `storage/` 中 `session_count=10`，启动会触发反思（约等 90 秒）。建议先改 `reflect_threshold: 999` 或 `rm -rf storage/` 从零开始。

---

## 第一轮：CLI 核心功能（10 分钟）

启动 CLI：
```bash
python main.py
```

### 1.1 基础对话

**操作**: 输入 `你好`

**预期结果**:
- 2-5 秒内开始输出（如果是首次启动且 session_count 触发反思，可能等 90 秒）
- 看到流式打字机效果，逐字出现
- 内容在 `Evo > ` 后面显示

**验证点**:
```bash
# 检查日志
cat storage/logs/agent.log | tail -20
# 应看到 [agent.core] INFO: turn.started / emotion.detected 等事件
```

---

### 1.2 短期记忆

**操作**: 连续输入：
```
我叫张三
我是做后端开发的
我喜欢用 Go 语言
```

**预期结果**:
- 每轮都有回复
- 第三轮回复中可能引用"后端开发"或"Go 语言"

**验证点**:
```
/mem
```

**预期**: 显示用户画像中包含 `name: 张三`、`职业: 后端开发` 等（信号学习实时写入）

---

### 1.3 信号词实时学习

**操作**: 输入：
```
请记住我的狗叫豆豆
```

**预期结果**:
- 正常回复
- 日志或终端中可能显示 `[实时学习: remember → added]`（取决于实时学习是否命中）

**验证点**:
```bash
# 新开个终端
cat storage/knowledge/knowledge_base.json | grep -i 豆豆
```
**预期**: JSON 中新增一条 category="fact"、content 包含"豆豆"的知识

---

### 1.4 Skill 路由

**操作**: 依次输入：
```
/calc 123 + 456
/echo 测试 Skill 系统
```

**预期结果**:
- `/calc` 秒回：`🧮 123 + 456 = 579`
- `/echo` 秒回：`🔊 回声: 测试 Skill 系统`
- 不调用 LLM，无打字机延迟

---

### 1.5 人格信号微调

**操作**: 输入：
```
简洁点
```

**预期结果**:
- 终端显示 `[人格微调: verbosity→-0.15, directness→+0.1]`（或类似）
- 后续回复明显变短

**验证点**:
```
/personality
```
**预期**: `verbosity` 值下降（从 0.5 降到 0.35 左右）

---

### 1.6 会话结束与后台学习

**操作**: 输入：
```
/bye
```

**预期结果**:
- 显示 "会话已保存。累计进行了 X 次会话。"
- 显示 "📚 复盘学习在后台进行..."
- 程序不退出，继续等待输入

**验证点**:
```bash
# 新终端
ls storage/conversations/ | tail -3          # 应有新的 session_*.json
cat storage/knowledge/knowledge_base.json | tail -50  # 知识数量可能增加
```

---

### 1.7 统计与状态

**操作**: 重新输入任意内容开启新会话，然后：
```
/stats
/personality
/mem
/skills
```

**预期结果**:
- `/stats`: 显示 session_count、knowledge_count、reflection_count
- `/personality`: 8 维参数 + temperature + max_tokens
- `/mem`: 显示当前记忆摘要（用户画像 + 相关知识）
- `/skills`: 列出 5 个内置 Skill

---

### 1.8 清理陈旧知识

**操作**: 输入：
```
/clean
```

**预期结果**:
- 显示清理数量（如有）或"没有需要清理的陈旧知识"

---

## 第二轮：边界与异常（5 分钟）

### 2.1 空输入

**操作**: 直接按回车

**预期**: 无任何反应，不报错

### 2.2 超长输入

**操作**: 粘贴一段 2000 字以上的文本

**预期**: 正常接收，LLM 正常回复（可能被截断到 max_tokens）

### 2.3 特殊字符

**操作**: 输入：
```
```python
print("hello")
```
```

**预期**: 正常接收，代码块格式保留

### 2.4 快速连续输入

**操作**: 连续快速发送 5 条消息（复制粘贴）

**预期**: 无并发错误，storage JSON 无损坏

### 2.5 中断恢复

**操作**: 对话中按 `Ctrl+C`

**预期**: 自动触发 `/bye`，保存会话并退出

---

## 第三轮：多会话与进化（5 分钟）

### 3.1 多轮会话

**操作**:
1. 聊 2-3 轮
2. `/bye`
3. 再聊 2-3 轮
4. `/bye`

**验证点**:
```bash
ls storage/conversations/ | wc -l    # 应增加 2 个 session 文件
```

### 3.2 反思触发（可选，会等 90 秒）

如果你把 `reflect_threshold` 保持默认值 5，当 `session_count` 达到 5 的倍数时，下次 `start_session` 会自动触发反思。

**现象**:
- 终端显示 "🧠 正在反思之前的对话，准备进化一下..."
- 等待约 90 秒
- 显示反思摘要 + 人格调整

**验证点**:
```bash
cat storage/reflections/reflections.json | tail -100
```

### 3.3 情绪与 Mood

**操作**: 输入：
```
今天烦死了，项目又出 bug 了
```

**预期**:
- 终端可能显示 `[情绪感知: 沮丧 X.X]`
- 回复语气更温和、简短
- `/personality` 中 `warmth` 可能微升，`verbosity` 可能微降

---

## 第四轮：Web 端测试（5 分钟）

### 4.1 启动服务

```bash
python -m web.app
```

**预期**: 终端显示 uvicorn 启动信息，`Uvicorn running on http://0.0.0.0:8000`

### 4.2 前端页面

**操作**: 浏览器打开 `http://localhost:8000`

**预期**:
- 页面加载成功，左侧边栏显示 Agent 状态
- 右侧聊天区有欢迎消息
- 连接指示灯为绿色

### 4.3 WebSocket 对话

**操作**: 输入 `你好`，发送

**预期**:
- 出现打字机动画（三个跳动圆点）
- 逐字显示回复
- 左侧状态栏更新：personality 条形图、mood 文本、session/knowledge 计数

### 4.4 Web 端命令

**操作**: 点击顶部 `/bye` 或 `/stats` 按钮

**预期**:
- `/bye`: 显示系统消息"会话已保存，后台学习中..."
- `/stats`: 显示统计卡片

### 4.5 多标签页

**操作**: 开两个浏览器标签，都访问 `http://localhost:8000`

**预期**:
- 各自独立会话（每个 WebSocket 连接独立 Agent 实例）
- 互不影响

---

## 第五轮：数据文件验证（随时可做）

### 5.1 文件清单检查

```bash
ls -la storage/
# 应有:
# conversations/   knowledge/   user_profile/   reflections/
# personality/     relationship/   mood/   logs/
```

### 5.2 JSON 完整性

```bash
# 逐一验证
python -c "import json; json.load(open('storage/knowledge/knowledge_base.json'))"
python -c "import json; json.load(open('storage/personality/state.json'))"
python -c "import json; json.load(open('storage/user_profile/user_profile.json'))"
python -c "import json; json.load(open('storage/relationship/events.json'))"
python -c "import json; json.load(open('storage/mood/state.json'))"
# 全部应无报错
```

### 5.3 向量索引一致性

```bash
python -c "
import json, numpy as np
kb = json.load(open('storage/knowledge/knowledge_base.json'))
vecs = np.load('storage/knowledge/vectors.npy')
meta = json.load(open('storage/knowledge/vectors_meta.json'))
assert len(kb) == len(vecs) == len(meta), '长度不一致！'
print(f'知识库: {len(kb)} 条, 向量: {len(vecs)} 条, 一致 ✅')
"
```

---

## 第六轮：工程化扩展点验证（可选）

### 6.1 配置中心

```bash
python -c "
from agent.config import Config
c = Config('config.yaml')
print(c.get('kimi.model'))          # kimi-for-coding
print(c.get('agent.name'))          # Evo
print(c.get('nonexist.key', 'default'))  # default
"
```

### 6.2 事件总线

```bash
python -c "
from agent.events import default_bus
def handler(payload):
    print('收到事件:', payload)
default_bus.subscribe('test.event', handler)
default_bus.publish('test.event', {'msg': 'hello'})
"
# 预期输出: 收到事件: {'msg': 'hello'}
```

### 6.3 存储抽象层切换（仅验证接口）

```bash
python -c "
from agent.storage import LocalJsonStorage
s = LocalJsonStorage()
s.save_json({'test': 123}, 'test.json', 'storage/tmp')
data = s.load_json('test.json', 'storage/tmp')
assert data['test'] == 123
print('存储抽象层正常 ✅')
"
```

---

## 测试通过标准

| 模块 | 最低通过标准 | 优秀标准 |
|---|---|---|
| CLI 对话 | 能聊 3 轮以上，不崩溃 | 流式输出流畅，信号学习命中 |
| Skill | 3 个 Skill 都能触发 | 错误输入有友好提示 |
| 记忆 | `/mem` 有内容，`/bye` 后文件生成 | 知识库去重合并正常 |
| 人格 | `/personality` 数值有变化 | 信号词实时调整可见 |
| 存储 | JSON 无损坏，向量长度一致 | 并发 5 轮无异常 |
| Web | 页面能打开，能发一条消息 | 状态栏实时更新，多标签独立 |
| 日志 | `storage/logs/agent.log` 有内容 | 按模块分级，无异常堆栈 |

---

## 常见问题速查

| 现象 | 原因 | 解决 |
|---|---|---|
| 启动后卡 90 秒无响应 | `session_count` 达到反思阈值 | 改 `reflect_threshold: 999` 或 `rm -rf storage/` |
| `[Kimi API 错误] 403` | User-Agent 被覆盖 | 已修复，确保代码是最新版 |
| 流式输出为空 | `kimi-for-coding` 输出在 `reasoning_content` | 已修复，如果仍空检查模型是否返回内容 |
| `Embedding 不可用` | `sentence-transformers` 未安装 | `pip install sentence-transformers`（可选，API embedding 已通） |
| `/calc` 不触发 | 输入格式不对 | 必须 `/calc 123 + 456`，中间有空格 |
| Web 页面空白 | 静态文件挂载失败 | 确认 `web/static/index.html` 存在 |
| WebSocket 断开重连 | 服务端崩溃或网络问题 | 看服务端日志，检查 `web/api.py` 异常 |

---

## 测试完成后的反馈

测试结束后，建议把以下信息发给我：

1. **是否遇到崩溃或报错**（贴日志/截图）
2. **哪些功能不正常**（具体输入和输出）
3. **主观体验**：回复速度、记忆引用准确度、人格调整是否明显
4. **期望改进**：哪些行为不够智能，想加什么功能
