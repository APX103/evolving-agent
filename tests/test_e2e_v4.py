#!/usr/bin/env python3
"""
v4.0 端到端测试
- Cron 主动调度器
- Skill 自动生成
- SQLite FTS5 会话搜索
"""
import os
import sys
import asyncio
from datetime import datetime

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_scheduler_basic(tmp_path):
    """测试调度器基础功能"""
    print("[E2E] 测试 Scheduler...")
    from agent.engine.scheduler import AgentScheduler, ScheduledTask

    scheduler = AgentScheduler(storage_path=str(tmp_path))

    # 1. 添加 interval 任务
    task = ScheduledTask(
        task_id="",
        name="测试间隔任务",
        description="每2秒执行",
        trigger_type="interval",
        trigger_config={"seconds": 2},
        prompt="检查系统状态",
        agent_name="companion",
    )
    tid = scheduler.add_task(task)
    assert tid, "任务 ID 不应为空"

    # 2. 验证任务列表
    tasks = scheduler.list_tasks()
    assert len(tasks) == 1, f"应有 1 个任务，实际 {len(tasks)}"
    assert tasks[0]["name"] == "测试间隔任务"

    # 3. 自然语言解析
    parsed = scheduler.parse_natural_language("每天早上8点发日报")
    assert parsed is not None, "应解析成功"
    assert parsed.trigger_type == "cron"
    assert parsed.trigger_config["hour"] == 8
    assert parsed.trigger_config["minute"] == 0

    parsed2 = scheduler.parse_natural_language("每30分钟检查一次")
    assert parsed2 is not None
    assert parsed2.trigger_type == "interval"
    assert parsed2.trigger_config["minutes"] == 30

    parsed3 = scheduler.parse_natural_language("周五下午6点提醒下班")
    assert parsed3 is not None
    assert parsed3.trigger_config["day_of_week"] == "fri"

    # 4. 禁用/启用
    assert scheduler.disable_task(tid) is True
    assert scheduler._tasks[tid].enabled is False
    assert scheduler.enable_task(tid) is True
    assert scheduler._tasks[tid].enabled is True

    # 5. 删除
    assert scheduler.remove_task(tid) is True
    assert len(scheduler.list_tasks()) == 0

    # 6. 持久化验证
    scheduler2 = AgentScheduler(storage_path=str(tmp_path))
    assert len(scheduler2.list_tasks()) == 0, "删除后不应恢复"

    print("   ✅ Scheduler 全部测试通过")


@pytest.mark.slow
@pytest.mark.asyncio
async def test_scheduler_async_trigger(tmp_path):
    """测试调度器异步触发"""
    print("[E2E] 测试 Scheduler 异步触发...")
    from agent.engine.scheduler import AgentScheduler, ScheduledTask

    triggered = []

    async def callback(task):
        triggered.append(task.name)

    scheduler = AgentScheduler(storage_path=str(tmp_path))
    scheduler.set_callback(callback)
    scheduler.start()

    task = ScheduledTask(
        task_id="t_async",
        name="异步触发测试",
        description="",
        trigger_type="interval",
        trigger_config={"seconds": 1},
        prompt="test",
    )
    scheduler.add_task(task)

    # 等待触发
    await asyncio.sleep(2.5)
    assert len(triggered) >= 1, f"应至少触发 1 次，实际 {len(triggered)}"
    assert triggered[0] == "异步触发测试"

    scheduler.shutdown()
    print(f"   ✅ Scheduler 异步触发通过 (触发 {len(triggered)} 次)")


def test_auto_skill_generator(tmp_path):
    """测试 Skill 自动生成"""
    print("[E2E] 测试 AutoSkillGenerator...")
    from agent.skills.auto import AutoSkillGenerator

    gen = AutoSkillGenerator(storage_path=str(tmp_path))

    # 1. 生成 Skill
    trace = [
        {"step": 1, "tool": "llm", "input": "分析需求", "output": "用户需要爬虫脚本"},
        {"step": 2, "tool": "sandbox", "input": "写 requests 代码", "output": "import requests..."},
        {"step": 3, "tool": "sandbox", "input": "运行测试", "output": "成功抓取 10 条数据"},
    ]
    skill = gen.generate_skill("帮我写一个爬虫脚本抓取新闻", trace)
    assert skill is not None, "应生成 Skill"
    assert "name" in skill
    assert len(skill["steps"]) >= 2, "应至少提取 2 步"
    assert len(skill["keywords"]) >= 2, "应有关键词"

    # 2. 匹配 Skill
    matched = gen.find_matching_skill("帮我写个爬虫抓网页数据")
    assert matched is not None, "应匹配到 Skill"
    assert matched["name"] == skill["name"]

    # 3. 不匹配的情况
    no_match = gen.find_matching_skill("今天天气怎么样")
    assert no_match is None, "不应匹配"

    # 4. 记录成功/失败
    gen.record_success(skill["name"])
    gen.record_success(skill["name"])
    gen.record_failure(skill["name"])
    updated = gen._skill_index[skill["name"]]
    assert updated["use_count"] == 3
    assert updated["success_count"] == 2

    # 5. 列表
    skills = gen.list_skills()
    assert len(skills) == 1

    print("   ✅ AutoSkillGenerator 全部测试通过")


def test_session_search_engine(tmp_path):
    """测试 FTS5 会话搜索"""
    print("[E2E] 测试 SessionSearchEngine...")
    from agent.planning.session_search import SessionSearchEngine

    db_path = tmp_path / "test.db"
    engine = SessionSearchEngine(db_path=str(db_path))

    # 1. 索引消息
    engine.index_message("user_1", "sess_a", "user", "我想做一个爬虫项目")
    engine.index_message("user_1", "sess_a", "assistant", "好的，用 requests + BeautifulSoup")
    engine.index_message("user_1", "sess_a", "user", "帮我写代码")
    engine.index_message("user_1", "sess_a", "assistant", "这是代码...")
    engine.index_message("user_1", "sess_b", "user", "我上周说的那个方案呢")
    engine.index_message("user_1", "sess_b", "assistant", "方案在这里：使用微服务架构")
    engine.index_message("user_2", "sess_c", "user", "用户2的消息")

    # 2. 关键词搜索
    results = engine.search("爬虫", user_id="user_1")
    assert len(results) >= 1, f"应找到至少 1 条，实际 {len(results)}"
    contents = [r["content"] for r in results]
    assert any("爬虫" in c for c in contents)

    # 3. 用户隔离
    results_u2 = engine.search("用户2")
    assert len(results_u2) >= 1
    assert results_u2[0]["user_id"] == "user_2"

    results_isolated = engine.search("用户2", user_id="user_1")
    assert len(results_isolated) == 0, "用户1不应搜到用户2的消息"

    # 4. 角色过滤
    user_only = engine.search("爬虫", user_id="user_1", role="user")
    assert all(r["role"] == "user" for r in user_only)

    # 5. 带上下文搜索
    enriched = engine.search_with_context("方案", user_id="user_1")
    assert len(enriched) >= 1
    assert len(enriched[0]["context"]) >= 1

    # 6. 批量索引会话
    msgs = [
        {"role": "user", "content": "测试批量索引", "timestamp": "2026-04-20T10:00:00"},
        {"role": "assistant", "content": "收到", "timestamp": "2026-04-20T10:01:00"},
    ]
    engine.index_session("user_1", "sess_d", msgs, summary="批量测试")
    batch_results = engine.search("批量索引", user_id="user_1")
    assert len(batch_results) >= 1

    # 7. 最近会话
    sessions = engine.recent_sessions("user_1", limit=3)
    assert len(sessions) >= 1

    engine.close()
    print("   ✅ SessionSearchEngine 全部测试通过")


def test_session_search_time_filter(tmp_path):
    """测试时间过滤"""
    print("[E2E] 测试 SessionSearch 时间过滤...")
    from agent.planning.session_search import SessionSearchEngine

    db_path = tmp_path / "time_test.db"
    engine = SessionSearchEngine(db_path=str(db_path))

    # 旧消息
    engine.index_message("u1", "s1", "user", "旧消息", "2025-01-01T00:00:00")
    # 新消息
    engine.index_message("u1", "s2", "user", "新消息爬虫", datetime.now().isoformat())

    # 不限时间
    all_results = engine.search("消息", user_id="u1")
    assert len(all_results) == 2

    # 限制最近 7 天
    recent = engine.search("消息", user_id="u1", days=7)
    assert len(recent) == 1, f"应只有 1 条最近消息，实际 {len(recent)}"
    assert "新消息" in recent[0]["content"]

    engine.close()
    print("   ✅ 时间过滤测试通过")


if __name__ == "__main__":
    import tempfile
    import shutil

    _tmp = tempfile.mkdtemp()
    try:
        test_scheduler_basic(_tmp)
        asyncio.run(test_scheduler_async_trigger(_tmp))
        test_auto_skill_generator(_tmp)
        test_session_search_engine(_tmp)
        test_session_search_time_filter(_tmp)
    finally:
        shutil.rmtree(_tmp, ignore_errors=True)
    print("\n🎉 v4.0 端到端测试全部通过!")
