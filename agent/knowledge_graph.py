"""
轻量级知识图谱
把扁平文本知识升级为 (subject, predicate, object, metadata) 三元组
支持关系推理和时序状态追踪
"""
import json
import os
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime


@dataclass
class Triple:
    """知识三元组"""
    subject: str           # 主体，如 "用户"
    predicate: str         # 关系，如 "喜欢"
    object: str            # 客体，如 "火锅"
    temporal_state: str    # current | past | planned | negated
    confidence: float      # 0-1
    source: str            # 来源对话摘要
    created_at: str
    updated_at: str
    access_count: int = 0

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict) -> "Triple":
        return cls(**d)

    def to_natural_language(self) -> str:
        """转回自然语言，用于 LLM prompt"""
        state_map = {
            "current": "",
            "past": "以前",
            "planned": "计划",
            "negated": "不",
        }
        prefix = state_map.get(self.temporal_state, "")
        if self.temporal_state == "negated":
            return f"{self.subject}{prefix}{self.predicate}{self.object}"
        return f"{self.subject}{prefix}{self.predicate}{self.object}"


class KnowledgeGraph:
    """
    轻量级知识图谱
    - 存储：本地 JSON（不依赖外部数据库）
    - 索引：按 subject + predicate 建立倒排
    - 推理：简单的传递闭包（A→B, B→C ⇒ A→C）
    """

    def __init__(self, storage_path: str = "./storage/knowledge_graph"):
        self.storage_path = storage_path
        os.makedirs(storage_path, exist_ok=True)

        self.triples_file = os.path.join(storage_path, "triples.json")
        self.triples: List[Triple] = self._load_triples()

        # 索引
        self._index_by_subject: Dict[str, List[int]] = {}
        self._index_by_predicate: Dict[str, List[int]] = {}
        self._rebuild_index()

    def _load_triples(self) -> List[Triple]:
        if os.path.exists(self.triples_file):
            try:
                with open(self.triples_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return [Triple.from_dict(t) for t in data]
            except Exception as e:
                print(f"[KnowledgeGraph] 加载失败: {e}")
        return []

    def _save_triples(self):
        with open(self.triples_file, "w", encoding="utf-8") as f:
            json.dump([t.to_dict() for t in self.triples], f, ensure_ascii=False, indent=2)

    def _rebuild_index(self):
        self._index_by_subject = {}
        self._index_by_predicate = {}
        for i, t in enumerate(self.triples):
            self._index_by_subject.setdefault(t.subject, []).append(i)
            self._index_by_predicate.setdefault(t.predicate, []).append(i)

    def add(self, triple: Triple) -> bool:
        """
        添加三元组，自动去重和更新
        返回: True=新增/更新, False=重复跳过
        """
        # 查找是否已存在相同 (subject, predicate, object)
        for existing in self.triples:
            if (existing.subject == triple.subject and
                existing.predicate == triple.predicate and
                existing.object == triple.object):
                # 更新：取更高 confidence，更新 temporal_state
                if triple.confidence > existing.confidence:
                    existing.confidence = triple.confidence
                    existing.temporal_state = triple.temporal_state
                    existing.updated_at = triple.updated_at
                    existing.source = triple.source
                    self._save_triples()
                return False

        self.triples.append(triple)
        self._rebuild_index()
        self._save_triples()
        return True

    def query(self, subject: Optional[str] = None,
              predicate: Optional[str] = None,
              object: Optional[str] = None,
              temporal_state: Optional[str] = None,
              min_confidence: float = 0.0) -> List[Triple]:
        """按条件查询三元组"""
        results = []
        for t in self.triples:
            if subject and t.subject != subject:
                continue
            if predicate and t.predicate != predicate:
                continue
            if object and t.object != object:
                continue
            if temporal_state and t.temporal_state != temporal_state:
                continue
            if t.confidence < min_confidence:
                continue
            results.append(t)
        return results

    def infer_related(self, subject: str, depth: int = 1) -> List[Tuple[str, str, str]]:
        """
        简单推理：找与 subject 相关的实体
        depth=1: 直接关联
        depth=2: 传递闭包（A喜欢B, B属于C ⇒ A可能喜欢C）
        返回: [(relation_path, inferred_object, reasoning)]
        """
        results = []
        visited = set()

        # depth 1
        direct = self.query(subject=subject)
        for t in direct:
            key = (t.predicate, t.object)
            if key not in visited:
                visited.add(key)
                results.append((
                    f"{t.predicate} {t.object}",
                    t.object,
                    f"{subject} {t.predicate} {t.object}"
                ))

        # depth 2: 传递
        if depth >= 2:
            for t in direct:
                # 找 t.object 作为 subject 的关系
                second_level = self.query(subject=t.object)
                for t2 in second_level:
                    if t2.predicate in ("属于", "是", "包含"):
                        inferred = f"{subject} 可能 {t.predicate} {t2.object}"
                        results.append((
                            f"{t.predicate} {t.object} → {t2.predicate} {t2.object}",
                            t2.object,
                            inferred
                        ))

        return results

    def detect_contradiction(self, new_triple: Triple) -> List[Triple]:
        """
        检测矛盾知识
        例如：已有 (用户, 喜欢, 辣, current) vs 新 (用户, 不喜欢, 辣, current)
        """
        contradictions = []
        # 查找同一 subject+predicate+object 的 negated 状态
        if new_triple.temporal_state == "current":
            negated = self.query(
                subject=new_triple.subject,
                predicate=new_triple.predicate,
                object=new_triple.object,
                temporal_state="negated"
            )
            contradictions.extend(negated)

        # 查找同一 subject+predicate 但 object 冲突（简单启发式）
        same_pred = self.query(
            subject=new_triple.subject,
            predicate=new_triple.predicate,
            temporal_state=new_triple.temporal_state
        )
        for t in same_pred:
            if t.object != new_triple.object:
                # 属于互斥类别才算矛盾（如"喜欢辣"vs"喜欢甜"不算矛盾，"是男生"vs"是女生"算）
                pass

        return contradictions

    def to_context_string(self, subject: str = "用户", limit: int = 10) -> str:
        """生成给用户画像的上下文文本"""
        triples = self.query(subject=subject, min_confidence=0.6)
        # 按访问频次排序
        triples.sort(key=lambda t: (t.access_count, t.confidence), reverse=True)

        lines = [f"【关于 {subject} 的结构化知识】"]
        for t in triples[:limit]:
            state_icon = {"current": "", "past": "[曾]", "planned": "[计划]", "negated": "[不]"}
            icon = state_icon.get(t.temporal_state, "")
            conf_bar = "█" * int(t.confidence * 5) + "░" * (5 - int(t.confidence * 5))
            lines.append(f"  {icon}{t.predicate}: {t.object} {conf_bar} {t.confidence:.2f}")

        # 加入推理结果
        inferences = self.infer_related(subject, depth=2)
        if inferences:
            lines.append("\n【推理关联】")
            for path, obj, reasoning in inferences[:5]:
                lines.append(f"  → {obj} ({path})")

        return "\n".join(lines) if len(lines) > 1 else ""
