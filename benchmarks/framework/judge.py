"""Judges for benchmark outputs."""
import re
from abc import ABC, abstractmethod
from typing import Any


class Judge(ABC):
    @abstractmethod
    def judge(self, expected: Any, actual: Any) -> float:
        """Return a score between 0.0 and 1.0."""
        ...


class ExactMatchJudge(Judge):
    """Simple exact-match judge (case-insensitive)."""

    def judge(self, expected: Any, actual: Any) -> float:
        if expected is None and actual is None:
            return 1.0
        if expected is None or actual is None:
            return 0.0
        return 1.0 if str(expected).strip().lower() == str(actual).strip().lower() else 0.0


class ContainsJudge(Judge):
    """Judge that checks if expected substring is present in actual."""

    def __init__(self, case_sensitive: bool = False):
        self.case_sensitive = case_sensitive

    def judge(self, expected: Any, actual: Any) -> float:
        if expected is None or actual is None:
            return 0.0
        e = str(expected)
        a = str(actual)
        if not self.case_sensitive:
            e = e.lower()
            a = a.lower()
        return 1.0 if e in a else 0.0


class LLMJudge(Judge):
    """Judge that uses an LLM to evaluate correctness."""

    def __init__(self, llm_client, prompt_template: str | None = None):
        self.llm_client = llm_client
        self.prompt_template = prompt_template or (
            "Evaluate whether the actual output correctly answers the expected output.\n"
            "Expected: {expected}\n"
            "Actual: {actual}\n"
            "Reply with only a number from 0 to 1."
        )

    def judge(self, expected: Any, actual: Any) -> float:
        prompt = self.prompt_template.format(expected=expected, actual=actual)
        try:
            response = self.llm_client.quick_chat(prompt)
            # Extract first float-looking number
            match = re.search(r"(0?\.\d+|1\.0|1)", response.strip())
            if match:
                score = float(match.group(1))
                return max(0.0, min(1.0, score))
        except Exception:
            pass
        return 0.0
