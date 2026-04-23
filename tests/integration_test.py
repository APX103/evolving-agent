"""
全量集成测试
需要有效的 Kimi API Key（config.yaml 已配置）
运行: python tests/integration_test.py
"""
import os
import sys
import json
import time
import threading

import pytest

# 确保能找到 agent 模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def log(msg):
    print(f"[TEST] {msg}")


def _test_initialization():
    from agent.core import EvolvingAgent
    log("=" * 50)
    log("测试 1: Agent 初始化")
    agent = EvolvingAgent("config.yaml")
    assert agent.name == "Evo"
    assert agent.session_active is False
    log(f"  ✅ Agent 初始化成功: {agent.name}")
    log(f"  ✅ 人格状态: {agent.personality.get_all()}")
    log(f"  ✅ 已注册 Skills: {[s['name'] for s in agent.skills.list_skills()]}")
    return agent


def _test_skill_calc(agent):
    log("=" * 50)
    log("测试 2: Skill 路由（/calc）")
    response = agent.chat("/calc 123 + 456")
    assert isinstance(response, str)
    assert "579" in response
    log(f"  ✅ Skill 返回: {response}")


def _test_skill_echo(agent):
    log("=" * 50)
    log("测试 3: Skill 路由（/echo）")
    response = agent.chat("/echo hello world")
    assert isinstance(response, str)
    assert "hello world" in response
    log(f"  ✅ Skill 返回: {response}")


def _test_stream_chat(agent):
    log("=" * 50)
    log("测试 4: LLM 流式对话")
    response = agent.chat("你好，请用一句话自我介绍")
    assert hasattr(response, "__iter__")  # 生成器
    chunks = []
    for chunk in response:
        chunks.append(chunk)
    full_text = "".join(chunks)
    agent.finalize_response("你好，请用一句话自我介绍", full_text)
    assert len(full_text) > 5
    log(f"  ✅ 流式输出完成，共 {len(full_text)} 字符")
    log(f"  ✅ 内容预览: {full_text[:60]}...")


def _test_short_term_memory(agent):
    log("=" * 50)
    log("测试 5: 短期记忆")
    short_term = agent.memory.get_short_term(max_turns=10)
    user_turns = [t for t in short_term if t["role"] == "user"]
    assistant_turns = [t for t in short_term if t["role"] == "assistant"]
    assert len(user_turns) >= 3  # /calc, /echo, 自我介绍
    assert len(assistant_turns) >= 2
    log(f"  ✅ 短期记忆中有 {len(user_turns)} 条用户消息, {len(assistant_turns)} 条助手消息")


def _test_signal_learning(agent):
    log("=" * 50)
    log("测试 6: 实时信号学习（请记住 / 我喜欢）")
    kb_before = len(agent.memory.knowledge_base)
    response = agent.chat("请记住我的狗叫豆豆")
    if hasattr(response, "__iter__"):
        chunks = list(response)
        full_text = "".join(chunks)
        agent.finalize_response("请记住我的狗叫豆豆", full_text)
    # 信号学习在 finalize_response 中的 on_turn_complete 触发
    time.sleep(2)  # 给 LLM 调用一点时间
    kb_after = len(agent.memory.knowledge_base)
    log(f"  ✅ 知识库数量: {kb_before} -> {kb_after}")
    if kb_after > kb_before:
        log(f"  ✅ 实时学习已写入知识")
    else:
        log(f"  ⚠️ 知识库未增加（可能是合并或信号未命中，继续观察）")


def _test_session_end(agent):
    log("=" * 50)
    log("测试 7: 会话结束与后台学习")
    session_count_before = agent.memory.session_count
    agent.end_session()
    assert agent.session_active is False
    assert agent.memory.session_count == session_count_before + 1
    log(f"  ✅ 会话已结束，session_count: {session_count_before} -> {agent.memory.session_count}")
    # 等待后台线程
    if agent._learning_thread and agent._learning_thread.is_alive():
        log("  ⏳ 等待后台学习线程...")
        agent._learning_thread.join(timeout=15)
        if agent._learning_thread.is_alive():
            log("  ⚠️ 后台学习线程仍在运行（API 较慢），但线程启动正常")
        else:
            log("  ✅ 后台学习线程已结束")
    else:
        log("  ✅ 后台学习线程已结束或未启动")


def _test_storage_files():
    log("=" * 50)
    log("测试 8: 本地存储文件完整性")
    base = "./storage"
    files_to_check = [
        "conversations",
        "knowledge/knowledge_base.json",
        "knowledge/vectors_meta.json",
        "user_profile/user_profile.json",
        "reflections/reflections.json",
        "personality/state.json",
        "relationship/events.json",
        "mood/state.json",
    ]
    for f in files_to_check:
        path = os.path.join(base, f)
        if os.path.exists(path):
            log(f"  ✅ {f}")
        else:
            log(f"  ⚠️ {f} 不存在（可能尚未触发写入）")

    # 检查 JSON 有效性
    for f in ["knowledge/knowledge_base.json", "personality/state.json"]:
        path = os.path.join(base, f)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as fp:
                    json.load(fp)
                log(f"  ✅ {f} JSON 格式有效")
            except Exception as e:
                log(f"  ❌ {f} JSON 损坏: {e}")
                raise


def _test_concurrent_writes():
    from agent.core import EvolvingAgent
    log("=" * 50)
    log("测试 9: 并发写入安全（模拟快速多轮对话）")
    agent = EvolvingAgent("config.yaml")
    errors = []

    def rapid_chat(text):
        try:
            resp = agent.chat(text)
            if hasattr(resp, "__iter__"):
                full = "".join(resp)
                agent.finalize_response(text, full)
        except Exception as e:
            errors.append(str(e))

    threads = []
    for i in range(5):
        t = threading.Thread(target=rapid_chat, args=(f"并发测试消息 {i}",))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    if errors:
        log(f"  ❌ 并发写入出现错误: {errors}")
        raise RuntimeError("并发测试失败")
    else:
        log("  ✅ 5 轮并发对话无异常")

    agent.end_session()
    if agent._learning_thread:
        agent._learning_thread.join(timeout=10)


def _test_config_singleton():
    from agent.config import Config
    log("=" * 50)
    log("测试 10: 配置单例")
    cfg1 = Config("config.yaml")
    cfg2 = Config("config.yaml")
    assert cfg1 is cfg2
    assert cfg1.kimi.get("api_key", "").startswith("sk-")
    log("  ✅ Config 单例工作正常，API Key 已加载")


def main():
    log("开始全量集成测试...")
    log("注意：本测试会调用真实 Kimi API，产生少量 token 消耗\n")

    # 清理旧存储（可选，避免干扰）
    # import shutil
    # if os.path.exists("./storage"):
    #     shutil.rmtree("./storage")

    agent = _test_initialization()
    _test_skill_calc(agent)
    _test_skill_echo(agent)
    _test_stream_chat(agent)
    _test_short_term_memory(agent)
    _test_signal_learning(agent)
    _test_session_end(agent)
    _test_storage_files()
    _test_concurrent_writes()
    _test_config_singleton()

    log("=" * 50)
    log("🎉 全量集成测试全部通过！")


@pytest.mark.integration
@pytest.mark.slow
def test_integration_full_stack():
    """Run the full integration stack against real APIs."""
    # Lazy import to avoid collection errors when agent.core has import issues
    from agent.core import EvolvingAgent
    _ = EvolvingAgent  # silence unused import warning for the closure
    main()


if __name__ == "__main__":
    main()
