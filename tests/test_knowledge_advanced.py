"""
高级知识提炼系统单元测试
运行: python tests/test_knowledge_advanced.py

覆盖模块:
- agent.knowledge_graph (无需外部依赖)
- agent.semantic_detector (需 mock embed)
- agent.quality_judge (需 mock LLM)
- agent.learner (需 mock LLM + MemoryManager)
"""
import os
import sys
import json
import tempfile
import shutil
import unittest
from unittest.mock import MagicMock
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.knowledge_graph import KnowledgeGraph, Triple
from agent.semantic_detector import SemanticSignalDetector


# ============================================================================
# KnowledgeGraph 测试
# ============================================================================
class TestKnowledgeGraph(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.kg = KnowledgeGraph(storage_path=self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_add_and_query(self):
        t = Triple(
            subject="用户", predicate="喜欢", object="火锅",
            temporal_state="current", confidence=0.9,
            source="test",
            created_at="2026-01-01T00:00:00",
            updated_at="2026-01-01T00:00:00",
        )
        ok = self.kg.add(t)
        self.assertTrue(ok)

        results = self.kg.query(subject="用户", predicate="喜欢")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].object, "火锅")

    def test_duplicate_rejection(self):
        t = Triple(subject="用户", predicate="喜欢", object="火锅",
                   temporal_state="current", confidence=0.9,
                   source="test",
                   created_at="2026-01-01T00:00:00",
                   updated_at="2026-01-01T00:00:00")
        self.kg.add(t)
        ok = self.kg.add(t)  # 重复添加
        self.assertFalse(ok)
        self.assertEqual(len(self.kg.triples), 1)

    def test_query_by_temporal_state(self):
        t1 = Triple(subject="用户", predicate="喜欢", object="火锅",
                    temporal_state="current", confidence=0.9,
                    source="test",
                    created_at="2026-01-01T00:00:00",
                    updated_at="2026-01-01T00:00:00")
        t2 = Triple(subject="用户", predicate="喜欢", object="川菜",
                    temporal_state="past", confidence=0.8,
                    source="test",
                    created_at="2026-01-01T00:00:00",
                    updated_at="2026-01-01T00:00:00")
        self.kg.add(t1)
        self.kg.add(t2)

        current = self.kg.query(temporal_state="current")
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0].object, "火锅")

    def test_min_confidence_filter(self):
        t1 = Triple(subject="用户", predicate="喜欢", object="火锅",
                    temporal_state="current", confidence=0.9,
                    source="test",
                    created_at="2026-01-01T00:00:00",
                    updated_at="2026-01-01T00:00:00")
        t2 = Triple(subject="用户", predicate="喜欢", object="烧烤",
                    temporal_state="current", confidence=0.3,
                    source="test",
                    created_at="2026-01-01T00:00:00",
                    updated_at="2026-01-01T00:00:00")
        self.kg.add(t1)
        self.kg.add(t2)

        high_conf = self.kg.query(min_confidence=0.5)
        self.assertEqual(len(high_conf), 1)
        self.assertEqual(high_conf[0].object, "火锅")

    def test_detect_contradiction(self):
        # 当前喜欢 vs 否定喜欢（同一 object 的 negated）
        t1 = Triple(subject="用户", predicate="喜欢", object="火锅",
                    temporal_state="current", confidence=0.9,
                    source="test",
                    created_at="2026-01-01T00:00:00",
                    updated_at="2026-01-01T00:00:00")
        t2 = Triple(subject="用户", predicate="喜欢", object="火锅",
                    temporal_state="negated", confidence=0.8,
                    source="test",
                    created_at="2026-01-01T00:00:00",
                    updated_at="2026-01-01T00:00:00")
        self.kg.add(t1)
        self.kg.add(t2)

        # 检测 current 的 contradictions（即查找 negated 的相同三元组）
        conflicts = self.kg.detect_contradiction(t1)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].temporal_state, "negated")

    def test_infer_related(self):
        t1 = Triple(subject="用户", predicate="喜欢", object="火锅",
                    temporal_state="current", confidence=0.9,
                    source="test",
                    created_at="2026-01-01T00:00:00",
                    updated_at="2026-01-01T00:00:00")
        t2 = Triple(subject="火锅", predicate="属于", object="川菜",
                    temporal_state="current", confidence=0.95,
                    source="test",
                    created_at="2026-01-01T00:00:00",
                    updated_at="2026-01-01T00:00:00")
        self.kg.add(t1)
        self.kg.add(t2)

        inferred = self.kg.infer_related("用户", depth=2)
        self.assertTrue(len(inferred) > 0)
        # 应该包含 "火锅 → 属于 川菜"
        # infer_related 返回 (relation_path, inferred_object, reasoning)
        self.assertTrue(any("火锅" in path and "川菜" in obj for path, obj, _ in inferred))

    def test_to_context_string(self):
        t = Triple(subject="用户", predicate="喜欢", object="火锅",
                   temporal_state="current", confidence=0.9,
                   source="test",
                   created_at="2026-01-01T00:00:00",
                   updated_at="2026-01-01T00:00:00")
        self.kg.add(t)
        ctx = self.kg.to_context_string("用户", limit=5)
        self.assertIn("喜欢: 火锅", ctx)

    def test_persistence(self):
        t = Triple(subject="用户", predicate="喜欢", object="火锅",
                   temporal_state="current", confidence=0.9,
                   source="test",
                   created_at="2026-01-01T00:00:00",
                   updated_at="2026-01-01T00:00:00")
        self.kg.add(t)
        # add() 内部已自动调用 _save_triples()

        # 重新加载
        kg2 = KnowledgeGraph(storage_path=self.tmpdir)
        results = kg2.query(subject="用户")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].object, "火锅")


# ============================================================================
# SemanticSignalDetector 测试
# ============================================================================
class TestSemanticSignalDetector(unittest.TestCase):
    def setUp(self):
        self.mock_llm = MagicMock()
        # 默认返回一个可被 mean() 调用的 numpy array
        self.mock_llm.embed = MagicMock(return_value=np.array([[0.1, 0.2, 0.3]]))

    def test_add_intent_and_detect(self):
        def mock_embed(texts):
            if isinstance(texts, str):
                texts = [texts]
            result = []
            for t in texts:
                if "intent_a" in t.lower():
                    result.append([1.0, 0.0, 0.0])
                elif "intent_b" in t.lower():
                    result.append([0.0, 1.0, 0.0])
                else:
                    result.append([0.5, 0.5, 0.0])
            return np.array(result)

        self.mock_llm.embed.side_effect = mock_embed
        detector = SemanticSignalDetector(self.mock_llm, cache_dir=tempfile.mkdtemp())
        detector.add_intent("intent_a", ["intent_a example"])
        detector.add_intent("intent_b", ["intent_b example"])

        # 查询接近 intent_a 的文本
        intent, score = detector.detect("intent_a query", threshold=0.7)
        self.assertEqual(intent, "intent_a")
        self.assertGreater(score, 0.7)

    def test_no_match_below_threshold(self):
        self.mock_llm.embed.return_value = np.array([[0.0, 0.0, 1.0]])
        detector = SemanticSignalDetector(self.mock_llm, cache_dir=tempfile.mkdtemp())
        detector.add_intent("test", ["example"])
        # 查询向量与锚点正交
        self.mock_llm.embed.return_value = np.array([[1.0, 0.0, 0.0]])
        result = detector.detect("unrelated", threshold=0.9)
        self.assertIsNone(result)

    def test_no_llm_fallback(self):
        detector = SemanticSignalDetector(None, cache_dir=tempfile.mkdtemp())
        result = detector.detect("any text")
        self.assertIsNone(result)


# ============================================================================
# QualityJudge 测试
# ============================================================================
class TestQualityJudge(unittest.TestCase):
    def setUp(self):
        from agent.quality_judge import QualityJudge
        self.mock_llm = MagicMock()
        self.judge = QualityJudge(self.mock_llm)

    def test_filter_valid_all_pass(self):
        def mock_chat(*args, **kwargs):
            return json.dumps([
                {"index": 0, "is_valid": True, "confidence": 0.95, "reason": "ok", "issue_type": None},
                {"index": 1, "is_valid": True, "confidence": 0.88, "reason": "ok", "issue_type": None},
            ])

        self.mock_llm.quick_chat = MagicMock(side_effect=mock_chat)
        items = [
            {"subject": "用户", "predicate": "喜欢", "object": "火锅", "content": "用户喜欢吃火锅"},
            {"subject": "用户", "predicate": "职业", "object": "程序员", "content": "用户是程序员"},
        ]
        result = self.judge.filter_valid(items, "用户说我喜欢吃火锅，我是程序员")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["_confidence"], 0.95)

    def test_filter_valid_some_fail(self):
        def mock_chat(*args, **kwargs):
            return json.dumps([
                {"index": 0, "is_valid": True, "confidence": 0.9, "reason": "ok", "issue_type": None},
                {"index": 1, "is_valid": False, "confidence": 0.2, "reason": "hallucination", "issue_type": "hallucination"},
            ])

        self.mock_llm.quick_chat = MagicMock(side_effect=mock_chat)
        items = [
            {"subject": "用户", "predicate": "喜欢", "object": "火锅", "content": "用户喜欢吃火锅"},
            {"subject": "用户", "predicate": "喜欢", "object": "不存在的", "content": "用户喜欢不存在的"},
        ]
        result = self.judge.filter_valid(items, "用户说我喜欢吃火锅")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["object"], "火锅")

    def test_filter_valid_empty_input(self):
        result = self.judge.filter_valid([], "任何文本")
        self.assertEqual(result, [])

    def test_filter_valid_malformed_response(self):
        # LLM 返回非 JSON，fallback 到全部通过，confidence = 0.7
        self.mock_llm.quick_chat = MagicMock(return_value="invalid json")
        items = [{"subject": "用户", "predicate": "喜欢", "object": "火锅", "content": "用户喜欢吃火锅"}]
        result = self.judge.filter_valid(items, "用户说我喜欢吃火锅")
        self.assertEqual(len(result), 1)
        self.assertIn("_confidence", result[0])
        self.assertEqual(result[0]["_confidence"], 0.7)


# ============================================================================
# Learner 测试 (增量学习接口)
# ============================================================================
class TestLearner(unittest.TestCase):
    def setUp(self):
        from agent.learner import Learner
        self.mock_llm = MagicMock()
        self.mock_memory = MagicMock()
        self.mock_memory.search_knowledge = MagicMock(return_value=[])
        self.mock_memory.add_knowledge = MagicMock(return_value={"action": "added", "id": "test-1"})
        self.mock_memory.knowledge_graph = None

        self.learner = Learner(self.mock_llm, self.mock_memory)

    def test_learn_from_turn_empty_result(self):
        # mock LLM 返回空列表（没有新知识）
        self.mock_llm.quick_chat = MagicMock(return_value="[]")
        result = self.learner.learn_from_turn("你好", "你好！")
        self.assertIn("learned", result)
        self.assertEqual(result["learned"], False)
        self.assertEqual(result["new_knowledge"], 0)

    def test_learn_from_turn_with_knowledge(self):
        extracted_json = json.dumps([
            {
                "subject": "用户", "predicate": "喜欢", "object": "火锅",
                "temporal_state": "current", "confidence": 0.9,
                "category": "preference", "content": "用户喜欢吃火锅"
            }
        ])
        self.mock_llm.quick_chat = MagicMock(return_value=extracted_json)
        result = self.learner.learn_from_turn("我喜欢吃火锅", "好的，我记住了")
        self.assertEqual(result["learned"], True)
        self.assertEqual(result["new_knowledge"], 1)

    def test_learn_from_turn_with_existing_knowledge_dedup(self):
        # 模拟已有知识（需要 category 和 content 字段）
        self.mock_memory.search_knowledge = MagicMock(return_value=[
            {"category": "preference", "content": "用户喜欢吃火锅"}
        ])
        # LLM 返回的知识中包含已有内容
        # 注意：去重主要在 LLM 层面（prompt 要求不提取已知信息），
        # 以及 _apply_to_memory 层面（add_knowledge 内部去重）。
        # 这里测试 add_knowledge 返回 merged 的情况。
        self.mock_memory.add_knowledge = MagicMock(side_effect=[
            {"action": "merged", "id": "test-merged"},  # 火锅被合并
            {"action": "added", "id": "test-added"},     # 烧烤是新知识
        ])
        extracted_json = json.dumps([
            {
                "subject": "用户", "predicate": "喜欢", "object": "火锅",
                "temporal_state": "current", "confidence": 0.9,
                "category": "preference", "content": "用户喜欢吃火锅"
            },
            {
                "subject": "用户", "predicate": "喜欢", "object": "烧烤",
                "temporal_state": "current", "confidence": 0.85,
                "category": "preference", "content": "用户喜欢吃烧烤"
            }
        ])
        self.mock_llm.quick_chat = MagicMock(return_value=extracted_json)
        result = self.learner.learn_from_turn("我喜欢吃火锅和烧烤", "好的")
        # 火锅被 merged，不计入 new_knowledge
        self.assertEqual(result["merged_count"], 1)
        # 烧烤被 added，计入 new_knowledge
        self.assertEqual(result["new_knowledge"], 1)
        objects = [k["object"] for k in result["details"]["knowledge"]]
        self.assertIn("烧烤", objects)

    def test_detect_strategy(self):
        strategy = self.learner._detect_strategy("你好啊，最近怎么样？")
        self.assertEqual(strategy, "casual")

        # "帮我写个 Python 函数" 中只有 "Python" 不在 tech_signals 里，
        # 且 tech_count < 3，所以是 casual
        strategy = self.learner._detect_strategy("帮我写个 Python 函数")
        self.assertEqual(strategy, "casual")

        # 包含足够多的技术关键词（注意避免包含 correction_signals 如"错了"）
        strategy = self.learner._detect_strategy(
            "这个代码有 bug，帮我看看，我用 docker 部署在服务器上"
        )
        self.assertEqual(strategy, "technical")

        strategy = self.learner._detect_strategy("不对，应该是 42")
        self.assertEqual(strategy, "corrected")

        # planning 需要 >= 2 个 planning_signals
        strategy = self.learner._detect_strategy("我计划做一个新方案，第一步怎么设计架构")
        self.assertEqual(strategy, "planning")

    def test_dict_to_triple(self):
        item = {
            "subject": "用户", "predicate": "喜欢", "object": "火锅",
            "temporal_state": "current", "confidence": 0.9,
            "category": "preference", "content": "用户喜欢吃火锅"
        }
        triple = self.learner._dict_to_triple(item)
        self.assertIsNotNone(triple)
        self.assertEqual(triple.subject, "用户")
        self.assertEqual(triple.object, "火锅")
        self.assertEqual(triple.confidence, 0.9)

    def test_dict_to_triple_uses_defaults(self):
        # 缺少字段时使用默认值，不会返回 None
        item = {"subject": "用户"}
        triple = self.learner._dict_to_triple(item)
        self.assertIsNotNone(triple)
        self.assertEqual(triple.subject, "用户")
        self.assertEqual(triple.predicate, "知道")
        self.assertEqual(triple.temporal_state, "current")

    def test_dict_to_triple_invalid_content_type(self):
        # content 不是字符串时可能触发异常
        item = {"subject": "用户", "content": 12345}
        triple = self.learner._dict_to_triple(item)
        # int 不支持 [:50]，会触发 except Exception 返回 None
        self.assertIsNone(triple)


# ============================================================================
# 运行入口
# ============================================================================
if __name__ == "__main__":
    unittest.main(verbosity=2)
