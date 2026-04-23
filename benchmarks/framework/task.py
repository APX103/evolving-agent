"""Base task definition for benchmarks."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class TaskResult:
    """Result of evaluating a single task instance."""
    task_name: str
    input_data: Any
    expected: Any
    actual: Any
    score: float  # 0.0 - 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)


class Task(ABC):
    """Base class for benchmark tasks."""

    name: str = ""
    description: str = ""

    @abstractmethod
    def load_dataset(self) -> List[Dict[str, Any]]:
        """Return a list of {'input': ..., 'expected': ...} dicts."""
        ...

    @abstractmethod
    async def evaluate(self, agent, instance: Dict[str, Any]) -> TaskResult:
        """Run the agent on one instance and return a TaskResult."""
        ...
