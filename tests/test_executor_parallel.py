#!/usr/bin/env python3
"""
Executor 并行执行测试
验证无依赖步骤的并行执行能力
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.executor import Executor
from agent.plan import Plan, Step, StepStatus


class MockLLM:
    """模拟 LLM，记录调用次数和时间"""
    def __init__(self, delay: float = 0.1):
        self.delay = delay
        self.call_count = 0
        self.call_times = []

    def quick_chat(self, prompt, system=None):
        self.call_count += 1
        t0 = time.time()
        time.sleep(self.delay)
        t1 = time.time()
        self.call_times.append((t0, t1))
        return f"result_for_{prompt[:20]}"

    async def aquick_chat(self, prompt, system=None):
        import asyncio
        self.call_count += 1
        t0 = time.time()
        await asyncio.sleep(self.delay)
        t1 = time.time()
        self.call_times.append((t0, t1))
        return f"result_for_{prompt[:20]}"


def test_serial_execution():
    """测试串行计划（步骤有依赖）"""
    print("[Executor] 测试串行执行...")
    llm = MockLLM(delay=0.05)
    executor = Executor(llm_client=llm)

    plan = Plan(
        task="串行任务",
        steps=[
            Step(id=1, description="步骤1", tool="llm", arguments={"prompt": "step1"}),
            Step(id=2, description="步骤2", tool="llm", arguments={"prompt": "step2"}, depends_on=[1]),
            Step(id=3, description="步骤3", tool="llm", arguments={"prompt": "step3"}, depends_on=[2]),
        ]
    )

    t0 = time.time()
    result = executor.run(plan)
    elapsed = time.time() - t0

    assert result.is_success()
    assert all(s.status == StepStatus.SUCCESS for s in result.steps)
    # 串行 3 步，每步 0.05s，总时间应 ≈ 0.15s
    assert elapsed >= 0.12, f"串行执行时间过短: {elapsed:.3f}s"
    print(f"   ✅ 串行执行正确 ({elapsed:.3f}s)")


def test_parallel_execution():
    """测试并行计划（步骤无依赖）"""
    print("[Executor] 测试并行执行...")
    llm = MockLLM(delay=0.1)
    executor = Executor(llm_client=llm, max_workers=3)

    plan = Plan(
        task="并行任务",
        steps=[
            Step(id=1, description="步骤A", tool="llm", arguments={"prompt": "stepA"}),
            Step(id=2, description="步骤B", tool="llm", arguments={"prompt": "stepB"}),
            Step(id=3, description="步骤C", tool="llm", arguments={"prompt": "stepC"}),
        ]
    )

    t0 = time.time()
    result = executor.run(plan)
    elapsed = time.time() - t0

    assert result.is_success()
    assert all(s.status == StepStatus.SUCCESS for s in result.steps)
    # 3 步并行，每步 0.1s，总时间应 ≈ 0.1s（而不是 0.3s）
    assert elapsed < 0.25, f"并行执行时间过长: {elapsed:.3f}s（应接近 0.1s）"
    print(f"   ✅ 并行执行正确 ({elapsed:.3f}s，3 步并发)")


def test_mixed_dependencies():
    """测试混合依赖（部分并行，部分串行）"""
    print("[Executor] 测试混合依赖...")
    llm = MockLLM(delay=0.05)
    executor = Executor(llm_client=llm, max_workers=4)

    plan = Plan(
        task="混合任务",
        steps=[
            # 第一轮：1 和 2 可并行
            Step(id=1, description="准备A", tool="llm", arguments={"prompt": "prepA"}),
            Step(id=2, description="准备B", tool="llm", arguments={"prompt": "prepB"}),
            # 第二轮：3 依赖 1，4 依赖 2，3 和 4 可并行
            Step(id=3, description="处理A", tool="llm", arguments={"prompt": "procA"}, depends_on=[1]),
            Step(id=4, description="处理B", tool="llm", arguments={"prompt": "procB"}, depends_on=[2]),
            # 第三轮：5 依赖 3 和 4
            Step(id=5, description="汇总", tool="llm", arguments={"prompt": "summary"}, depends_on=[3, 4]),
        ]
    )

    t0 = time.time()
    result = executor.run(plan)
    elapsed = time.time() - t0

    assert result.is_success()
    # 最优时间：第一轮 0.05s + 第二轮 0.05s + 第三轮 0.05s = 0.15s
    # 最坏串行：5 * 0.05 = 0.25s
    assert elapsed < 0.22, f"混合执行时间过长: {elapsed:.3f}s"
    print(f"   ✅ 混合依赖执行正确 ({elapsed:.3f}s)")


def test_step_failure_handling():
    """测试步骤失败不影响其他并行步骤"""
    print("[Executor] 测试失败处理...")

    class FailingLLM:
        def quick_chat(self, prompt, system=None):
            if "fail" in prompt.lower():
                raise RuntimeError("模拟失败")
            return f"ok:{prompt}"

        async def aquick_chat(self, prompt, system=None):
            return self.quick_chat(prompt, system)

    executor = Executor(llm_client=FailingLLM(), max_workers=2)

    plan = Plan(
        task="失败测试",
        steps=[
            Step(id=1, description="成功A", tool="llm", arguments={"prompt": "okA"}),
            Step(id=2, description="失败B", tool="llm", arguments={"prompt": "failB"}),
            Step(id=3, description="依赖成功A", tool="llm", arguments={"prompt": "step3"}, depends_on=[1]),
        ]
    )

    result = executor.run(plan)
    assert result.steps[0].status == StepStatus.SUCCESS
    assert result.steps[1].status == StepStatus.FAILED
    assert result.steps[2].status == StepStatus.SUCCESS
    print("   ✅ 失败处理正确")


def test_variable_resolution():
    """测试跨步骤变量替换"""
    print("[Executor] 测试变量替换...")

    class TrackingLLM:
        def __init__(self):
            self.last_prompt = ""
        def quick_chat(self, prompt, system=None):
            self.last_prompt = prompt
            return "processed"

    llm = TrackingLLM()
    executor = Executor(llm_client=llm)

    plan = Plan(
        task="变量替换",
        steps=[
            Step(id=1, description="获取数据", tool="llm", arguments={"prompt": "fetch"}),
            Step(id=2, description="处理数据", tool="llm", arguments={"prompt": "process {{step1.result}}"}, depends_on=[1]),
        ]
    )

    # 预设第一步结果
    plan.steps[0].result = "raw_data_123"
    plan.steps[0].status = StepStatus.SUCCESS

    # 直接执行第二步
    executor._execute_step(plan, plan.steps[1])

    assert "raw_data_123" in llm.last_prompt
    print("   ✅ 变量替换正确")


if __name__ == "__main__":
    test_serial_execution()
    test_parallel_execution()
    test_mixed_dependencies()
    test_step_failure_handling()
    test_variable_resolution()
    print("\n🎉 Executor 并行执行全部测试通过!")
