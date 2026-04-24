# Evolving Agent 调试记录

## 修复列表

### 1. main.py - 缺失 asyncio 导入
**问题**: 代码使用了 `asyncio.run()` 但没有导入 asyncio 模块
**修复**: 添加 `import asyncio`

### 2. main.py & web/app.py - 日志污染
**问题**: httpx 的 HTTP 请求日志大量输出到控制台
**修复**: 在 setup_logging() 和 app.py 中设置 `logging.getLogger("httpx").setLevel(logging.WARNING)`

### 3. agent/llm/kimi_client.py - 异步 event hooks 类型错误
**问题**: httpx.AsyncClient 的 event_hooks 使用了同步函数，导致异步 API 调用返回 403
**修复**: 为异步客户端创建 `_async_force_ua` async 函数

### 4. agent/llm/kimi_client.py - aclose() 方法错误
**问题**: `aclose()` 调用了 `self._async_http_client.close()` 而不是 `aclose()`
**修复**: 改为 `await self._async_http_client.aclose()`

### 5. agent/llm/kimi_client.py - 流式输出包含 reasoning_content
**问题**: kimi-2.6 模型在 stream 模式下会输出推理过程（reasoning_content），被错误地返回给用户
**修复**: 所有流式生成器只返回 `delta.content`，过滤掉 `reasoning_content`

### 6. agent/llm/kimi_client.py - chat_structured 不支持 dict schema
**问题**: `chat_structured()` 只支持 Pydantic 模型，但 emotion.py 传入 dict
**修复**: 增加 `isinstance(response_model, dict)` 分支，直接返回解析后的 JSON dict

### 7. agent/semantic_detector.py - 缓存文件名不匹配
**问题**: `np.savez()` 保存为 `intent_anchors.npz`，但加载时使用路径 `intent_anchors.npy`
**修复**: 将 `vec_cache_path` 从 `.npy` 改为 `.npz`

### 8. agent/emotion.py - Prompt 过长导致 API 延迟
**问题**: emotion 分析 prompt 过长，导致 chat_structured() 调用耗时 12+ 秒
**修复**: 简化 prompt，减少不必要的内容

### 9. web/api.py - 日志配置不完整
**问题**: logger 没有 handler，INFO 级别日志不输出
**修复**: 添加 StreamHandler 并设置日志级别

### 10. web/api.py - WebSocket 错误处理
**问题**: stream 结束后 finalize_response() 可能抛出异常，导致 done 消息无法发送
**修复**: 添加 try-except 包裹 finalize_response 和 _send_status

## 功能验证状态

| 功能 | 状态 | 说明 |
|------|------|------|
| CLI 经典模式 | ✅ | 正常对话、/stats、/skills、/personality、/bye |
| CLI 多Agent模式 | ✅ | 可启动（需进一步测试完整流程）|
| Web HTTP 服务 | ✅ | 首页、/api/metrics、/api/traces |
| WebSocket 聊天 | ✅ | thinking、stream、done 消息完整 |
| 前端页面 | ✅ | HTML加载、WebSocket连接、暗黑模式 |
| LLM API (同步) | ✅ | quick_chat、chat、chat_structured |
| LLM API (异步) | ✅ | achat、astreaming |
| 情绪分析 | ✅ | 优化后约 5 秒 |
| SemanticDetector | ✅ | 缓存加载正常 |

## 已知限制

1. **首次 SemanticDetector 初始化**: 如果没有缓存，需要调用 embedding API 8 次（约 8-16 秒）
2. **情绪分析延迟**: 每次对话需要 1 次 LLM 调用（约 5 秒）
3. **WebSocket 超时**: 客户端需设置足够长的超时时间（建议 30 秒以上）
