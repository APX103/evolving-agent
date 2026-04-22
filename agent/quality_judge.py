"""
LLM-as-Judge 质量过滤层
用第二个 LLM 评估提取结果的可信度，减少幻觉和错误
"""
import json
from typing import Dict, List, Optional
from dataclasses import dataclass

from agent.llm.base import LLMClient


@dataclass
class JudgmentResult:
    """质检结果"""
    index: int
    is_valid: bool
    confidence: float       # 0-1
    reason: str             # 判断理由
    issue_type: Optional[str]  # hallucination | subject_confusion | temporal_error | unsupported


class QualityJudge:
    """
    知识提取质量检查员
    - 检查幻觉（提取的知识是否有原文依据）
    - 检查主客体混淆
    - 检查时态错误
    - 给每条知识打 confidence 分数
    """

    JUDGE_PROMPT_TEMPLATE = """你是一位严格的质量检查员。请评估以下从对话中提取的知识是否准确可靠。

【原始对话】
{source_text}

【提取的知识】（JSON 格式）
{extracted_json}

【检查要求】
1. hallucination（幻觉）：知识是否在对话中有明确依据？如果 LLM "脑补"了对话中没有的信息，标记为 invalid。
2. subject_confusion（主客体混淆）："我喜欢"vs"同事喜欢"、"我要做"vs"公司要做"是否被正确区分？
3. temporal_error（时态错误）："以前喜欢"是否被误记为"现在喜欢"？"计划做"是否被误记为"正在做"？
4. unsupported（ unsupported inference）："用户喜欢火锅"→"用户喜欢辣"这种推理是否有足够依据？

【输出格式】
只返回 JSON 数组，不要其他文字：
[
  {{
    "index": 0,
    "is_valid": true/false,
    "confidence": 0.0-1.0,
    "reason": "判断理由",
    "issue_type": "hallucination/subject_confusion/temporal_error/unsupported/null"
  }}
]
"""

    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client

    def judge(self, extracted_items: List[Dict], source_text: str) -> List[JudgmentResult]:
        """
        对提取结果进行质量评估
        """
        if not extracted_items:
            return []

        # 如果 source_text 太长，截断到合理长度
        max_source_len = 4000
        if len(source_text) > max_source_len:
            source_text = source_text[:max_source_len] + "...（已截断）"

        prompt = self.JUDGE_PROMPT_TEMPLATE.format(
            source_text=source_text,
            extracted_json=json.dumps(extracted_items, ensure_ascii=False, indent=2)
        )

        try:
            response = self.llm_client.quick_chat(
                prompt,
                system="你只返回 JSON 数组，不做任何解释。"
            )
            results = self._parse_judgment(response, len(extracted_items))
            return results
        except Exception as e:
            print(f"[QualityJudge] 质检失败: {e}")
            # 质检失败时，全部通过（保守策略）
            return [
                JudgmentResult(i, True, 0.7, "质检未执行，默认通过", None)
                for i in range(len(extracted_items))
            ]

    def _parse_judgment(self, text: str, expected_count: int) -> List[JudgmentResult]:
        """解析质检 JSON"""
        try:
            cleaned = text.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            if cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()

            data = json.loads(cleaned)
            if not isinstance(data, list):
                data = []

            results = []
            for i in range(expected_count):
                item = data[i] if i < len(data) else {}
                results.append(JudgmentResult(
                    index=item.get("index", i),
                    is_valid=item.get("is_valid", True),
                    confidence=float(item.get("confidence", 0.7)),
                    reason=item.get("reason", "无说明"),
                    issue_type=item.get("issue_type") or None
                ))
            return results

        except Exception as e:
            print(f"[QualityJudge] 解析质检结果失败: {e}")
            return [
                JudgmentResult(i, True, 0.7, "解析失败，默认通过", None)
                for i in range(expected_count)
            ]

    def filter_valid(self, extracted_items: List[Dict], source_text: str) -> List[Dict]:
        """
        过滤掉低质量知识，返回有效项
        同时给每条知识注入 confidence 字段
        """
        judgments = self.judge(extracted_items, source_text)
        valid_items = []

        for item, judgment in zip(extracted_items, judgments):
            if judgment.is_valid and judgment.confidence > 0.5:
                item["_confidence"] = judgment.confidence
                item["_judge_reason"] = judgment.reason
                valid_items.append(item)
            else:
                print(f"[QualityJudge] 过滤低质量知识: {item.get('content', item)[:50]}... "
                      f"原因: {judgment.reason}")

        return valid_items
