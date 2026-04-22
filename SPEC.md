# Evolving Agent v4.0 SPEC — 多 Agent 协作系统

> 版本: v4.0  
> 基线: v3.2  
> 目标: 单体 Agent → 多 Agent 协作系统 + 飞书深度集成 + Context 自管理

---

## 1. 架构总览

```
用户输入（CLI / Web / 飞书 Bot）
    │
    ▼
┌─────────────────────────────────────────────────────┐
│                 AgentRegistry                        │
│  ┌─────────┐  ┌─────────┐  ┌─────────────────────┐ │
│  │ Router  │  │Companion│  │    GroupChatMgr     │ │
│  │ (调度员) │  │ (陪伴者) │  │    (群聊协调)       │ │
│  └────┬────┘  └────┬────┘  └─────────────────────┘ │
│       │            │                                 │
│  ┌────┴────────────┴─────────────────────────────┐ │
│  │           Specialized Agents                  │ │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐        │ │
│  │  │  Coder  │ │Researcher│ │ Writer  │        │ │
│  │  │(程序员) │ │ (研究员) │ │ (写手)  │        │ │
│  │  └─────────┘ └─────────┘ └─────────┘        │ │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐        │ │
│  │  │ Planner │ │Executor │ │Reviewer │        │ │
│  │  │(规划师) │ │(执行员) │ │(审稿人) │        │ │
│  │  └─────────┘ └─────────┘ └─────────┘        │ │
│  └──────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────┐
│              Multi-Agent Infrastructure              │
│  ┌──────────┐ ┌────────────┐ ┌──────────────────┐  │
│  │ContextManager│ │HandoffProtocol │ │MemoryNamespace   │  │
│  │(上下文分层)  │ │(状态传递)     │ │(记忆命名空间)    │  │
│  └──────────┘ └────────────┘ └──────────────────┘  │
│  ┌──────────┐ ┌────────────┐ ┌──────────────────┐  │
│  │AsyncLLM  │ │AgentPool   │ │EventBus          │  │
│  │(异步LLM) │ │(实例池)    │ │(事件总线)        │  │
│  └──────────┘ └────────────┘ └──────────────────┘  │
└─────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────┐
│              Shared Core Services                    │
│  MemoryManager │ Personality │ Emotion │ Skill      │
│  KnowledgeGraph│ Reflector   │ Learner │ MCPClient  │
└─────────────────────────────────────────────────────┘
```

---

## 2. 模块定义

### 2.1 BaseAgent — 所有 Agent 的抽象基类

```python
class BaseAgent(ABC):
    """Agent 抽象基类，定义统一接口"""

    name: str = "base"
    description: str = "基础 Agent"
    system_prompt_template: str = ""
    temperature: float = 0.7
    max_tokens: int = 4096

    def __init__(self, agent_id: str, memory: MemoryManager, llm_client: LLMClient, config: Dict):
        self.agent_id = agent_id          # 唯一标识
        self.memory = memory              # 共享 MemoryManager
        self.llm = llm_client             # LLM 客户端
        self.config = config
        self.working_memory: Dict = {}    # 私有工作记忆
        self.event_bus = default_bus

    @abstractmethod
    async def process(self, user_input: str, context: AgentContext) -> AgentResponse:
        """处理用户输入，返回响应"""
        pass

    @abstractmethod
    def can_handle(self, intent: IntentClassification) -> float:
        """返回置信度 0.0-1.0，表示能否处理该意图"""
        pass

    def build_system_prompt(self, context: AgentContext) -> str:
        """基于 context 构建 system prompt（可覆盖）"""
        parts = [self.system_prompt_template]
        # Layer 1: Eternal Memory
        eternal = context.get_layer(LayerType.ETERNAL)
        if eternal:
            parts.append(f"【用户核心画像】\n{eternal}")
        # Layer 3: Working Context
        working = context.get_layer(LayerType.WORKING)
        if working:
            parts.append(f"【当前任务】\n{working}")
        return "\n\n".join(parts)
```

### 2.2 AgentRegistry — Agent 注册与调度中心

```python
class AgentRegistry:
    """Agent 注册中心：管理所有 Agent 实例，负责路由和生命周期"""

    def __init__(self):
        self._agents: Dict[str, BaseAgent] = {}
        self._router: Optional[RouterAgent] = None

    def register(self, agent: BaseAgent) -> None:
        """注册 Agent"""
        self._agents[agent.name] = agent

    def set_router(self, router: RouterAgent) -> None:
        """设置路由 Agent"""
        self._router = router

    async def process(self, user_input: str, user_id: str, source: str = "cli") -> AgentResponse:
        """
        统一入口：
        1. 获取/创建 user_id 对应的 Context
        2. Router 意图分类
        3. 选择 Agent
        4. 执行并返回
        """
        context = await self._build_context(user_id, user_input)
        intent = await self._router.classify(user_input, context)
        agent = self._select_agent(intent)
        response = await agent.process(user_input, context)
        await self._post_process(user_id, user_input, response)
        return response

    def _select_agent(self, intent: IntentClassification) -> BaseAgent:
        """基于 Router 结果选择最合适的 Agent"""
        if intent.target_agent and intent.target_agent in self._agents:
            return self._agents[intent.target_agent]
        # fallback: 按置信度排序选择
        candidates = [(name, agent.can_handle(intent))
                      for name, agent in self._agents.items()]
        candidates.sort(key=lambda x: x[1], reverse=True)
        return self._agents[candidates[0][0]]
```

### 2.3 RouterAgent — 意图分类与调度

```python
class RouterAgent(BaseAgent):
    """路由 Agent：分析用户意图，决定激活哪个 Specialist"""

    name = "router"
    description = "意图分类与 Agent 调度"
    temperature = 0.3
    max_tokens = 512

    # 意图 → Agent 映射
    INTENT_AGENT_MAP = {
        "chat":         "companion",      # 闲聊/情感
        "emotional":    "companion",      # 情感支持
        "code":         "coder",          # 写代码
        "debug":        "coder",          # 调试
        "research":     "researcher",     # 信息检索
        "write":        "writer",         # 文案/报告
        "plan":         "planner",        # 复杂任务分解
        "execute":      "executor",       # 执行计划
        "review":       "reviewer",       # 审核/反思
    }

    async def classify(self, user_input: str, context: AgentContext) -> IntentClassification:
        """意图分类，返回目标 Agent 和置信度"""
        prompt = self._build_classify_prompt(user_input, context)
        response = await self.llm.achat(prompt, temperature=0.3, max_tokens=256)
        return self._parse_intent(response)
```

### 2.4 Specialist Agents

#### CompanionAgent
- **角色**: 陪伴者
- **职责**: 日常对话、情感交流
- **记忆权限**: 读写情绪、关系、人格
- **工具**: 基础 Skill
- **temperature**: 0.8（温暖灵活）

#### CoderAgent
- **角色**: 程序员
- **职责**: 代码编写、调试、文件操作
- **记忆权限**: 只读知识库；写沙箱结果
- **工具**: Sandbox, MCP(filesystem)
- **temperature**: 0.2（精确稳定）

#### ResearcherAgent
- **角色**: 研究员
- **职责**: 信息检索、网页浏览、调研
- **记忆权限**: 只读知识库；写工作记忆
- **工具**: MCP(fetch, search)
- **temperature**: 0.4（理性平衡）

#### WriterAgent
- **角色**: 写手
- **职责**: 文案、报告、总结
- **记忆权限**: 只读知识库、工作记忆
- **工具**: LLM, Skill(calc)
- **temperature**: 0.6（创意适中）

#### PlannerAgent
- **角色**: 规划师
- **职责**: 复杂任务分解为可执行计划
- **记忆权限**: 读写工作记忆(plan_state)
- **工具**: LLM
- **temperature**: 0.3（精确规划）

#### ExecutorAgent
- **角色**: 执行员
- **职责**: 按计划调用工具完成动作
- **记忆权限**: 读写工作记忆(step_results)
- **工具**: 全部工具
- **temperature**: 0.2（确定性高）

#### ReviewerAgent
- **角色**: 审稿人
- **职责**: 质量检查、反思、纠错
- **记忆权限**: 只读工作记忆、知识库
- **工具**: LLM
- **temperature**: 0.3（严格标准）

---

## 3. Context 分层架构（核心机制）

### 3.1 六层架构

```
Layer 0: System Prompt（~500 tokens）
  └─ Agent 身份 + 人格 + 情绪指令 + 关系上下文

Layer 1: Eternal Memory（~300 tokens）
  └─ 用户最核心的 3-5 条画像（自动提取，永不压缩）
  └─ 例："用户是前端工程师，喜欢简洁回答，讨厌啰嗦，常用 React"

Layer 2: Session Summaries（~800 tokens）
  └─ 过去每个会话的 LLM 生成摘要，按时间倒序
  └─ 旧摘要可进一步合并为"超摘要"

Layer 3: Working Context（~200 tokens）
  └─ 当前任务目标、用户最后需求、待办事项、跨 Agent 传递状态

Layer 4: Recent Turns（~1500 tokens）
  └─ 当前会话最近的完整对话轮次
  └─ 超限时：最旧 50% 轮次 → LLM 摘要 → 移至 Layer 2 → 删除原始轮次

Layer 5: Procedural Rules（~200 tokens）
  └─ 高置信度行为策略，上限 5 条
  └─ 例："用户问技术问题时，先确认技术栈和版本"
```

### 3.2 ContextManager

```python
class ContextManager:
    """上下文管理器：负责构建、压缩、维护分层上下文"""

    # 固定预算（tokens）
    BUDGET = {
        LayerType.SYSTEM:     500,
        LayerType.ETERNAL:    300,
        LayerType.SUMMARIES:  800,
        LayerType.WORKING:    200,
        LayerType.RECENT:    1500,
        LayerType.RULES:      200,
    }
    TOTAL_BUDGET = 3500

    async def build_context(self, user_id: str, query: str = "", source: str = "cli") -> AgentContext:
        """
        构建完整的 AgentContext
        1. 加载各层内容
        2. 按预算裁剪
        3. 组装为 AgentContext
        """

    async def compress_if_needed(self, user_id: str) -> None:
        """
        检查 Layer 4（Recent Turns）是否超预算
        超限时：最旧 50% 轮次 → LLM 摘要 → 移至 Layer 2
        """

    async def on_new_session(self, user_id: str) -> AgentContext:
        """
        新会话启动时：
        - 加载 L1（必带）+ L2（动态裁剪到 800 tokens）+ L3 + L5
        - 前置总长度控制在 1800-2000 tokens
        """
```

### 3.3 AgentContext

```python
@dataclass
class AgentContext:
    """Agent 上下文：包含所有层的内容"""
    user_id: str
    source: str                    # cli / web / feishu
    layers: Dict[LayerType, str]   # 各层内容
    short_term: List[Dict]         # 原始对话轮次（Layer 4）
    working_memory: Dict           # 工作记忆
    metadata: Dict                 # 额外元数据

    def to_messages(self, system_prompt: str) -> List[Dict[str, str]]:
        """转换为 LLM messages 格式"""
        messages = [{"role": "system", "content": system_prompt}]
        # 按 Layer 顺序添加
        for layer_type in [LayerType.ETERNAL, LayerType.SUMMARIES,
                           LayerType.WORKING, LayerType.RULES]:
            content = self.layers.get(layer_type, "")
            if content:
                messages.append({"role": "system", "content": f"[{layer_type.value}]\n{content}"})
        messages.extend(self.short_term)
        return messages

    def get_layer(self, layer_type: LayerType) -> str:
        return self.layers.get(layer_type, "")
```

---

## 4. Handoff 协议

### 4.1 核心原则
- Agent 间不直接调用方法
- 通过 `working_memory` 共享状态
- 每个 Handoff 带完整的上下文传递

### 4.2 Handoff 流程

```python
@dataclass
class HandoffRequest:
    """Agent 间传递的请求"""
    from_agent: str           # 来源 Agent
    to_agent: str             # 目标 Agent
    user_input: str           # 原始用户输入
    context_summary: str      # 上下文摘要
    working_memory: Dict      # 需要传递的工作记忆
    handoff_reason: str       # 交接原因

@dataclass
class HandoffResult:
    """Agent 间传递的结果"""
    from_agent: str
    response: str             # 响应内容
    updated_working_memory: Dict
    learnings: List[Dict]     # 学习成果（带 source_agent 标签）

class HandoffProtocol:
    """Handoff 协议：管理 Agent 间的状态传递"""

    async def handoff(self, request: HandoffRequest) -> HandoffResult:
        """
        执行 Handoff：
        1. 获取目标 Agent
        2. 将 working_memory 注入目标 Agent
        3. 调用目标 Agent.process()
        4. 收集结果和学习成果
        5. 返回 HandoffResult
        """
```

### 4.3 协作流程示例

```
用户: "帮我调研一下 Python 的异步框架，然后写个对比报告"

Router → intent: "research" + "write" → Planner

Planner:
  Step 1: Researcher 调研 asyncio, trio, curio
  Step 2: Researcher 收集性能数据
  Step 3: Writer 生成对比报告
  Step 4: Reviewer 审核报告质量

执行:
  Planner.decompose() → Plan
  Executor.run(plan):
    - Step 1 → Handoff to Researcher → working_memory["research_results"]
    - Step 2 → Handoff to Researcher → working_memory["benchmark_data"]
    - Step 3 → Handoff to Writer (inject research_results + benchmark_data)
    - Step 4 → Handoff to Reviewer (inject draft_report)
  → 返回最终报告
```

---

## 5. 记忆命名空间

### 5.1 目录结构

```
storage/{user_id}/
  ├── shared/                    # 所有 Agent 共享（只读为主）
  │   ├── knowledge_base.json    # 统一知识库（带 source_agent 字段）
  │   ├── vectors.npy            # 统一向量索引
  │   ├── graph/
  │   │   └── triples.json       # 统一知识图谱
  │   ├── user_profile.json      # 用户画像
  │   ├── relationship/          # 关系档案
  │   │   ├── events.json
  │   │   └── meta.json
  │   └── eternal_memory.json    # Layer 1 永恒记忆
  │
  ├── companion/                 # Companion 私有
  ├── coder/                     # Coder 私有
  ├── researcher/                # Researcher 私有
  ├── writer/                    # Writer 私有
  ├── planner/                   # Planner 私有
  ├── executor/                  # Executor 私有
  ├── reviewer/                  # Reviewer 私有
  │
  └── working/                   # 临时工作区（当前任务状态）
      ├── current_plan.json
      ├── current_task.json
      └── temp_context.json
```

### 5.2 MemoryNamespace

```python
class MemoryNamespace:
    """记忆命名空间管理：隔离各 Agent 的私有记忆"""

    def __init__(self, user_id: str, storage: StorageBackend):
        self.user_id = user_id
        self.storage = storage
        self.base_path = os.path.join(storage.base_path, user_id)

    def get_shared_path(self, filename: str) -> str:
        """获取共享文件路径"""
        return os.path.join(self.base_path, "shared", filename)

    def get_agent_path(self, agent_name: str, filename: str) -> str:
        """获取 Agent 私有文件路径"""
        return os.path.join(self.base_path, agent_name, filename)

    def get_working_path(self, filename: str) -> str:
        """获取工作区文件路径"""
        return os.path.join(self.base_path, "working", filename)

    def load_shared(self, filename: str, default=None):
        """加载共享记忆"""
        path = self.get_shared_path(filename)
        return self.storage.load_json(filename, os.path.dirname(path), default=default)

    def save_shared(self, data, filename: str):
        """保存共享记忆"""
        path = self.get_shared_path(filename)
        self.storage.ensure_dir(os.path.dirname(path))
        self.storage.save_json(data, filename, os.path.dirname(path))
```

---

## 6. 飞书集成

### 6.1 架构

```
飞书开放平台
    │  WebSocket 长连接 / HTTP Webhook
    ▼
┌─────────────────────────────────────┐
│         FeishuBotAdapter            │
│  - 验签                             │
│  - 事件接收（消息/回调/群聊）        │
│  - 消息类型转换                      │
│  - 会话生命周期管理（30min TTL）     │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│         FeishuMessageHandler        │
│  - @mention 过滤（群聊）            │
│  - 消息格式转换（→ 统一 Message）    │
│  - 审批 Card 渲染与回调处理          │
│  - 流式输出（"正在输入" + 编辑）     │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│         AgentRegistry.process()     │
└─────────────────────────────────────┘
```

### 6.2 FeishuBotAdapter

```python
class FeishuBotAdapter:
    """飞书机器人适配器"""

    def __init__(self, app_id: str, app_secret: str, encrypt_key: str = ""):
        self.app_id = app_id
        self.app_secret = app_secret
        self.encrypt_key = encrypt_key
        self.event_handler = FeishuEventHandler()

    async def handle_webhook(self, request: Request) -> Response:
        """
        处理飞书 webhook 回调
        1. 验签
        2. 解密（如启用加密）
        3. 分发事件类型
        """

    async def handle_websocket(self, ws: WebSocket):
        """
        WebSocket 长连接维持
        - 自动重连
        - 心跳保活
        """

    async def send_message(self, chat_id: str, content: Union[str, CardMessage],
                          msg_type: str = "text") -> str:
        """发送消息，返回 message_id"""

    async def update_message(self, message_id: str, content: Union[str, CardMessage]):
        """编辑已发送的消息（用于流式输出 chunk 更新）"""

    async def send_typing_indicator(self, chat_id: str):
        """发送"正在输入"状态"""

    async def send_approval_card(self, chat_id: str, request: ApprovalRequest) -> str:
        """发送交互式审批 Card，返回 message_id"""
```

### 6.3 消息格式

```python
@dataclass
class UnifiedMessage:
    """统一消息格式（所有端通用）"""
    message_id: str
    user_id: str
    chat_id: str          # 群聊 ID（私聊为空）
    chat_type: str        # "p2p" | "group"
    content: str
    content_type: str     # "text" | "markdown" | "card" | "image"
    mention_bot: bool     # 是否 @了机器人
    create_time: int
    raw: Dict             # 原始消息数据
```

### 6.4 会话生命周期

```python
class SessionLifecycleManager:
    """
    会话生命周期管理
    - 30 分钟无消息自动 end_session()
    - 收到新消息自动 start_session()
    - 群聊中仅响应 @机器人的消息
    """

    SESSION_TTL_SECONDS = 1800  # 30 分钟

    def __init__(self):
        self._sessions: Dict[str, SessionState] = {}
        self._timers: Dict[str, asyncio.TimerHandle] = {}

    async def on_message(self, user_id: str, message: UnifiedMessage) -> bool:
        """
        收到消息时调用
        返回: 是否应该处理此消息
        """
        # 群聊中未 @机器人，跳过
        if message.chat_type == "group" and not message.mention_bot:
            return False

        # 检查会话状态
        state = self._sessions.get(user_id)
        if state is None or state.is_expired():
            # 新会话或已过期
            if state:
                await self._end_session(user_id)
            await self._start_session(user_id)

        # 重置 TTL 定时器
        self._reset_timer(user_id)
        return True

    def _reset_timer(self, user_id: str):
        """重置会话 TTL 定时器"""
        if user_id in self._timers:
            self._timers[user_id].cancel()
        self._timers[user_id] = asyncio.get_event_loop().call_later(
            self.SESSION_TTL_SECONDS,
            lambda: asyncio.create_task(self._end_session(user_id))
        )
```

### 6.5 审批 Card

```python
class FeishuApprovalRenderer:
    """飞书审批 Card 渲染器"""

    def render(self, request: ApprovalRequest) -> CardMessage:
        """渲染交互式审批卡片"""
        return CardMessage(
            header=CardHeader(title="🔒 敏感操作需要确认", subtitle=request.description),
            elements=[
                CardText(request.details),
                CardActions([
                    CardButton("✅ 确认执行", action_type="approve", value=request.request_id,
                               style="primary"),
                    CardButton("❌ 拒绝", action_type="reject", value=request.request_id,
                               style="danger"),
                ])
            ]
        )

    async def handle_callback(self, callback: CardCallback) -> ApprovalResult:
        """处理 Card 按钮回调"""
        request_id = callback.action_value
        if callback.action_type == "approve":
            return self.approval_manager.approve(request_id)
        else:
            return self.approval_manager.reject(request_id)
```

---

## 7. 异步 LLM 客户端

```python
class AsyncLLMClient(ABC):
    """异步 LLM 客户端接口"""

    @abstractmethod
    async def achat(self, messages: List[Dict], **kwargs) -> str:
        pass

    @abstractmethod
    async def astream_chat(self, messages: List[Dict], **kwargs) -> AsyncGenerator[str, None]:
        pass

    @abstractmethod
    async def aembed(self, texts: List[str]) -> np.ndarray:
        pass

class AsyncKimiClient(AsyncLLMClient):
    """基于 aiohttp 的异步 Kimi 客户端"""

    def __init__(self, config: Config):
        self.config = config
        self.session: Optional[aiohttp.ClientSession] = None
        self._semaphore = asyncio.Semaphore(10)  # 并发限制

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(limit=100, limit_per_host=20),
                timeout=aiohttp.ClientTimeout(total=30),
            )
        return self.session

    async def achat(self, messages: List[Dict], temperature: float = 0.7,
                    max_tokens: int = 4096) -> str:
        async with self._semaphore:
            session = await self._get_session()
            # ... API 调用，带重试

    async def astream_chat(self, messages: List[Dict], **kwargs) -> AsyncGenerator[str, None]:
        """流式输出，用于打字机效果"""
        async with self._semaphore:
            # ... SSE 流式读取
```

---

## 8. 事件总线（扩展）

```python
class MultiAgentEventBus(EventBus):
    """扩展事件总线，支持跨 Agent 事件"""

    # 新增事件类型
    EVENTS = {
        # Agent 生命周期
        "agent.handoff.request":  "Agent 交接请求",
        "agent.handoff.complete": "Agent 交接完成",
        "agent.activated":        "Agent 被激活",
        "agent.completed":        "Agent 完成处理",

        # 上下文管理
        "context.compressed":     "上下文被压缩",
        "context.layer.updated":  "上下文层更新",

        # 飞书特有
        "feishu.message.received": "收到飞书消息",
        "feishu.card.callback":    "飞书 Card 回调",
        "feishu.session.expired":  "飞书会话过期",
    }
```

---

## 9. 数据流

### 9.1 单轮对话完整数据流

```
用户输入 (CLI/Web/飞书)
    │
    ▼
[1] 统一格式化为 UnifiedMessage
    │
    ▼
[2] SessionLifecycleManager.on_message()
    │   ├── 检查会话状态（30min TTL）
    │   ├── 群聊检查 @mention
    │   └── 返回是否处理
    │
    ▼
[3] AgentRegistry.process()
    │   ├── 获取/创建 AgentContext
    │   │   ├── ContextManager.build_context()
    │   │   │   ├── Layer 0: System Prompt
    │   │   │   ├── Layer 1: Eternal Memory
    │   │   │   ├── Layer 2: Session Summaries（裁剪到 800）
    │   │   │   ├── Layer 3: Working Context
    │   │   │   ├── Layer 4: Recent Turns
    │   │   │   └── Layer 5: Procedural Rules
    │   │   └── 检查是否需压缩
    │   └── Router.classify() → IntentClassification
    │
    ▼
[4] _select_agent() → BaseAgent
    │
    ▼
[5] agent.process(user_input, context)
    │   ├── 构建 system prompt（含 Layer 1,3,5）
    │   ├── 组装 messages（context.to_messages()）
    │   ├── LLM 调用（stream/async）
    │   ├── 实时学习（SignalLearner）
    │   └── 返回 AgentResponse
    │
    ▼
[6] _post_process()
    │   ├── 保存对话到 short_term
    │   ├── 更新工作记忆
    │   └── 发布事件
    │
    ▼
[7] 格式化输出（CLI/Web/飞书适配）
    │
    ▼
用户看到响应
```

### 9.2 多 Agent 协作数据流

```
用户输入: "帮我调研 Python 异步框架，写对比报告"
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
    ├── 按依赖执行步骤
    │   ├── Step 1: Handoff to Researcher
    │   │   ├── Researcher.process("调研 asyncio")
    │   │   └── 结果 → working_memory["step_1_result"]
    │   ├── Step 2: Handoff to Researcher
    │   │   ├── Researcher.process("调研 trio, curio")
    │   │   └── 结果 → working_memory["step_2_result"]
    │   ├── Step 3: Handoff to Writer
    │   │   ├── 注入 step_1_result + step_2_result
    │   │   ├── Writer.process("生成对比报告")
    │   │   └── 结果 → working_memory["draft_report"]
    │   └── Step 4: Handoff to Reviewer
    │       ├── 注入 draft_report
    │       ├── Reviewer.process("审核报告")
    │       └── 结果 → working_memory["final_report"]
    ├── 汇总结果
    └── 返回最终报告
    │
    ▼
AgentRegistry 格式化输出
    │
    ▼
用户看到最终报告
```

---

## 10. 测试策略

### 10.1 单元测试
- 每个 Agent: `test_router_agent.py`, `test_companion_agent.py`, ...
- ContextManager: token 预算测试、压缩准确性测试
- HandoffProtocol: 状态传递完整性测试
- FeishuAdapter: 消息转换测试

### 10.2 集成测试
- 每个 Handoff 路径: `test_handoff_paths.py`
- CLI → AgentRegistry → Agent 完整链路
- Web → WebSocket → AgentRegistry 完整链路
- 飞书 Webhook → AgentRegistry 完整链路

### 10.3 端到端测试
- 飞书消息转换: `test_feishu_e2e.py`
- Context 压缩准确性: `test_context_compression.py`

---

## 11. 部署

### 11.1 单机部署
```bash
git clone <repo>
cd evolving-agent
pip install -r requirements.txt
cp config.yaml.example config.yaml
# 编辑 config.yaml，填入 API Key 和飞书配置
python main.py           # CLI 模式
python -m web.app        # Web 模式
python -m bot.feishu     # 飞书 Bot 模式
```

### 11.2 配置

```yaml
# config.yaml 新增配置
agent:
  name: "Evo"
  max_short_term_turns: 10
  reflect_threshold: 5
  context_budget: 3500

  # 多 Agent 配置
  multi_agent:
    enabled: true
    router_temperature: 0.3
    default_agent: "companion"

  # 飞书配置
  feishu:
    enabled: true
    app_id: "cli_xxxxxxxx"
    app_secret: "xxxxxxxx"
    encrypt_key: ""           # 可选
    verification_token: "xxx"  # 可选
    bot_name: "Evo"           # 群聊中响应的 @名
    session_ttl: 1800         # 30 分钟

# LLM 配置（新增异步选项）
kimi:
  api_key: "sk-xxxxxxxx"
  base_url: "https://api.moonshot.cn/v1"
  model: "kimi-latest"
  async_mode: true            # 启用异步
  connection_pool_size: 20
  timeout: 30
  max_retries: 3
```

---

## 12. 演进计划

| 阶段 | 内容 | 优先级 |
|------|------|--------|
| **Phase 1** | 基础设施: BaseAgent, AgentRegistry, AsyncLLMClient, ContextManager | P0 |
| **Phase 2** | 多 Agent 核心: Router, Companion, Coder, Researcher, Handoff | P0 |
| **Phase 3** | 飞书集成: Webhook, Card, 群聊, 会话生命周期 | P0 |
| **Phase 4** | Planner + Executor + Reviewer 完整链路 | P1 |
| **Phase 5** | 记忆命名空间重构, Agent 级 Reflector | P1 |
| **Phase 6** | Skill Library, 性能监控, 知识库自动维护 | P2 |
