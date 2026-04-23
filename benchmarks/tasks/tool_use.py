"""Tool-use benchmark: does the agent correctly route to calculator skill?"""
import sys
import os
from typing import Any, Dict, List

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from benchmarks.framework.task import Task, TaskResult
from benchmarks.framework.judge import ContainsJudge


class ToolUseBenchmark(Task):
    """
    Simple benchmark that checks whether the agent routes
    arithmetic queries to the /calc skill.
    """

    name = "tool_use"
    description = "Evaluate skill routing for calculator queries"

    def load_dataset(self) -> List[Dict[str, Any]]:
        return [
            {"input": "/calc 123 + 456", "expected": "579"},
            {"input": "/calc 10 * 5", "expected": "50"},
            {"input": "/calc 100 - 33", "expected": "67"},
            {"input": "What is 7 times 8?", "expected": "56"},  # May or may not route
        ]

    async def evaluate(self, agent, instance: Dict[str, Any]) -> TaskResult:
        user_input = instance["input"]
        expected = instance["expected"]

        response = agent.chat(user_input)
        # Handle streaming responses
        if hasattr(response, "__iter__") and not isinstance(response, str):
            full_text = "".join(response)
        else:
            full_text = str(response)

        judge = ContainsJudge(case_sensitive=False)
        score = judge.judge(expected, full_text)

        return TaskResult(
            task_name=self.name,
            input_data=user_input,
            expected=expected,
            actual=full_text,
            score=score,
            metadata={"routed_to_skill": user_input.startswith("/calc")},
        )
