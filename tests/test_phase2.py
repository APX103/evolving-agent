#!/usr/bin/env python3
"""
Phase 2 功能测试
- 多用户隔离
- 程序记忆
- 上下文压缩
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.context.user_context import UserContext
from agent.memory.procedural_memory import ProceduralMemory, ProceduralRule
from agent.memory.context_compressor import ContextCompressor


def test_user_context():
    """测试多用户隔离路径生成"""
    print("[Phase2] 测试 UserContext...")
    ctx = UserContext("user_42", base_path="/tmp/test_storage")
    assert ctx.path("conversations") == "/tmp/test_storage/user_42/conversations"
    assert ctx.path("knowledge", "vectors.npy") == "/tmp/test_storage/user_42/knowledge/vectors.npy"
    assert ctx.user_id == "user_42"
    print("   ✅ UserContext 路径正确")


def test_procedural_memory(tmp_path):
    """测试程序记忆的增删改查"""
    print("[Phase2] 测试 ProceduralMemory...")
    pm = ProceduralMemory(storage_path=str(tmp_path))

    # 添加规则
    rule = pm.add_rule("询问技术问题", "先确认技术栈和版本", confidence=0.8)
    assert rule.pattern == "询问技术问题"
    assert rule.confidence == 0.8

    # 重复添加应升级
    rule2 = pm.add_rule("询问技术问题", "先确认技术栈和版本", confidence=0.9)
    assert rule2.confidence == 0.9
    assert len(pm.list_rules()) == 1

    # 检索
    rules = pm.get_relevant_rules("我遇到一个 React bug")
    assert len(rules) >= 1
    assert rules[0].pattern == "询问技术问题"

    # prompt 文本
    prompt = pm.get_prompt_text("React bug")
    assert "learned behaviors" in prompt
    assert "先确认技术栈和版本" in prompt

    # 删除
    assert pm.remove_rule("询问技术问题") is True
    assert len(pm.list_rules()) == 0
    print("   ✅ ProceduralMemory CRUD 正常")


def test_procedural_memory_learn(tmp_path):
    """测试程序记忆从反馈学习"""
    print("[Phase2] 测试 ProceduralMemory 反馈学习...")
    pm = ProceduralMemory(storage_path=str(tmp_path))
    pm.learn_from_feedback("怎么解决这个 bug？", "试试重启", "positive")
    rules = pm.list_rules()
    assert len(rules) >= 1
    assert any("技术" in r.pattern for r in rules)

    pm.learn_from_feedback("你错了", "不对", "corrected", correction="用户不喜欢被说教")
    rules = pm.list_rules()
    assert any("用户不喜欢被说教" in r.action for r in rules)
    print("   ✅ ProceduralMemory 学习正常")


def test_context_compressor_simple():
    """测试上下文压缩的简单摘要模式"""
    print("[Phase2] 测试 ContextCompressor 简单摘要...")
    cc = ContextCompressor(llm_client=None, max_turns=3, compress_batch=6)

    # 未超过阈值，不压缩
    short = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    result = cc.compress(short)
    assert len(result) == 2

    # 超过阈值，压缩旧消息
    long = []
    for i in range(10):
        long.append({"role": "user", "content": f"msg {i}"})
        long.append({"role": "assistant", "content": f"reply {i}"})

    result = cc.compress(long)
    # 应该有 1 条摘要 + 最近 3 轮（6 条）
    assert result[0]["role"] == "system"
    assert "compressed" in result[0]
    assert len(result) == 7  # 1 summary + 6 kept
    print("   ✅ ContextCompressor 简单摘要正常")


def test_context_compressor_llm():
    """测试上下文压缩的 LLM 摘要模式（mock）"""
    print("[Phase2] 测试 ContextCompressor LLM 摘要...")

    class MockLLM:
        def chat(self, messages, **kwargs):
            return {"content": "用户和助手讨论了多个技术话题。"}

    cc = ContextCompressor(llm_client=MockLLM(), max_turns=2, compress_batch=6)
    long = []
    for i in range(6):
        long.append({"role": "user", "content": f"问题 {i}: 这是什么意思？"})
        long.append({"role": "assistant", "content": f"回答 {i}: 这是..." * 20})

    result = cc.compress(long)
    assert result[0]["role"] == "system"
    assert "讨论了多个技术话题" in result[0]["content"]
    print("   ✅ ContextCompressor LLM 摘要正常")


def test_full_compressed_context():
    """测试完整上下文构建"""
    print("[Phase2] 测试完整上下文构建...")
    cc = ContextCompressor(llm_client=None, max_turns=2)
    cc.session_summary = "之前讨论了部署问题。"

    short_term = [
        {"role": "user", "content": "现在怎么办？"},
        {"role": "assistant", "content": "继续。"},
    ]
    messages = cc.get_full_compressed_context("你是助手", short_term)
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == "你是助手"
    assert messages[1]["role"] == "system"
    assert "之前讨论了部署问题" in messages[1]["content"]
    assert messages[2]["role"] == "user"
    print("   ✅ 完整上下文构建正常")


if __name__ == "__main__":
    import tempfile
    import shutil

    test_user_context()
    _tmp = tempfile.mkdtemp()
    try:
        test_procedural_memory(_tmp)
        test_procedural_memory_learn(_tmp)
    finally:
        shutil.rmtree(_tmp, ignore_errors=True)
    test_context_compressor_simple()
    test_context_compressor_llm()
    test_full_compressed_context()
    print("\n🎉 Phase 2 全部测试通过!")
