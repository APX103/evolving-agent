"""
长期知识库 Store
知识条目的存储、去重合并、向量索引、语义搜索
"""
import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import numpy as np

from agent.memory.base import MemoryStore

logger = logging.getLogger(__name__)


class LongTermStore(MemoryStore):
    """
    长期记忆：知识库 + 向量索引
    - 去重合并
    - 向量语义搜索
    - 记忆老化清理
    """

    def __init__(
        self,
        storage=None,
        knowledge_path: str = "./storage/knowledge",
        llm_client=None,
    ):
        super().__init__(storage)
        self.knowledge_path = self.storage.ensure_dir(knowledge_path)
        self.llm_client = llm_client
        self._embedding_available = llm_client is not None

        self.vector_path = os.path.join(self.knowledge_path, "vectors.npy")
        self.vector_meta_path = os.path.join(self.knowledge_path, "vectors_meta.json")

        self.knowledge_base = self.storage.load_json("knowledge_base.json", self.knowledge_path, default=[])
        self._vectors = self._load_vectors()
        if self._vectors is None and self.knowledge_base:
            logger.info(f"[LongTermStore] 检测到 {len(self.knowledge_base)} 条知识，重建向量索引...")
            self._build_all_vectors()

    # ── 向量索引 ──

    def _load_vectors(self) -> Optional[np.ndarray]:
        if os.path.exists(self.vector_path) and os.path.exists(self.vector_meta_path):
            try:
                vecs = np.load(self.vector_path)
                meta = self.storage.load_json("vectors_meta.json", self.knowledge_path, default=[])
                if len(meta) == len(self.knowledge_base) == len(vecs):
                    return vecs
                else:
                    logger.info("[LongTermStore] 向量索引长度不一致，重建中...")
            except Exception as e:
                logger.info(f"[LongTermStore] 加载向量失败: {e}")
        return None

    def _save_vectors(self):
        if self._vectors is not None:
            np.save(self.vector_path, self._vectors)
            meta = [{"id": k["id"], "idx": i} for i, k in enumerate(self.knowledge_base)]
            self.storage.save_json(meta, "vectors_meta.json", self.knowledge_path)

    def _build_all_vectors(self):
        if not self._embedding_available or not self.knowledge_base:
            self._vectors = None
            return
        texts = [k["content"] for k in self.knowledge_base]
        try:
            self._vectors = self.llm_client.embed(texts)
            self._save_vectors()
            logger.info(f"[LongTermStore] 向量索引重建完成: {len(texts)} 条")
        except Exception as e:
            logger.info(f"[LongTermStore] 向量重建失败: {e}")
            self._vectors = None

    def _append_vector(self, text: str):
        if not self._embedding_available:
            return
        try:
            vec = self.llm_client.embed(text)
            if self._vectors is None:
                self._vectors = vec
            else:
                self._vectors = np.vstack([self._vectors, vec])
            self._save_vectors()
        except Exception as e:
            logger.info(f"[LongTermStore] 追加向量失败: {e}")

    def _rebuild_vector_for(self, item: Dict[str, Any]):
        if not self._embedding_available or self._vectors is None:
            return
        try:
            idx = None
            for i, k in enumerate(self.knowledge_base):
                if k["id"] == item["id"]:
                    idx = i
                    break
            if idx is None or idx >= len(self._vectors):
                return
            vec = self.llm_client.embed(item["content"])
            self._vectors[idx] = vec[0]
            self._save_vectors()
        except Exception as e:
            logger.info(f"[LongTermStore] 单条向量重建失败: {e}")

    # ── 知识管理 ──

    def add_knowledge(self, category: str, content: str, source: str = "") -> Dict[str, str]:
        content = content.strip()
        if not content:
            return {"action": "skipped", "id": ""}

        duplicate = self._find_duplicate(content)
        if duplicate:
            merged_content = self._merge_content(duplicate["content"], content)
            duplicate["content"] = merged_content
            duplicate["last_accessed"] = datetime.now().isoformat()
            duplicate["access_count"] = duplicate.get("access_count", 0) + 1
            duplicate["merge_count"] = duplicate.get("merge_count", 0) + 1
            self.storage.save_json(self.knowledge_base, "knowledge_base.json", self.knowledge_path)
            self._rebuild_vector_for(duplicate)
            return {"action": "merged", "id": duplicate["id"]}

        item = {
            "id": f"k_{datetime.now().strftime('%Y%m%d%H%M%S')}_{len(self.knowledge_base)}",
            "category": category,
            "content": content,
            "source": source,
            "created_at": datetime.now().isoformat(),
            "last_accessed": datetime.now().isoformat(),
            "access_count": 0,
            "merge_count": 0
        }
        self.knowledge_base.append(item)
        self.storage.save_json(self.knowledge_base, "knowledge_base.json", self.knowledge_path)
        self._append_vector(content)
        return {"action": "added", "id": item["id"]}

    def _find_duplicate(self, content: str) -> Optional[Dict[str, Any]]:
        content_lower = content.lower()
        for item in self.knowledge_base:
            if content_lower == item["content"].lower():
                return item
            min_len = 10
            if len(content) >= min_len and len(item["content"]) >= min_len:
                if content_lower in item["content"].lower() or item["content"].lower() in content_lower:
                    return item

        if not self._embedding_available or self._vectors is None or len(self.knowledge_base) == 0:
            return None

        try:
            query_vec = self.llm_client.embed(content)
            sims = self.llm_client.cosine_similarity(query_vec[0], self._vectors)
            best_idx = int(np.argmax(sims))
            best_sim = float(sims[best_idx])
            if best_sim > 0.85:
                return self.knowledge_base[best_idx]
        except Exception:
            pass
        return None

    def _merge_content(self, old: str, new: str) -> str:
        old_l = old.lower()
        new_l = new.lower()
        if new_l in old_l:
            return old
        if old_l in new_l:
            return new
        return f"{old}\n（补充：{new}）"

    def search_knowledge(self, query: str = "", category: str = "", limit: int = 10) -> List[Dict[str, Any]]:
        results = []
        updated_any = False

        if self._embedding_available and self._vectors is not None and query and len(self.knowledge_base) > 0:
            try:
                query_vec = self.llm_client.embed(query)
                sims = self.llm_client.cosine_similarity(query_vec[0], self._vectors)
                top_k = min(limit * 3, len(sims))
                top_indices = np.argsort(sims)[-top_k:][::-1]
                for idx in top_indices:
                    idx = int(idx)
                    item = self.knowledge_base[idx]
                    sim = float(sims[idx])
                    if sim < 0.55:
                        continue
                    if category and item["category"] != category:
                        continue
                    item["access_count"] = item.get("access_count", 0) + 1
                    item["last_accessed"] = datetime.now().isoformat()
                    updated_any = True
                    results.append({**item, "_similarity": round(sim, 3)})
            except Exception as e:
                logger.info(f"[LongTermStore] 向量搜索失败: {e}")

        if len(results) < limit // 2 and query:
            for item in self.knowledge_base:
                if category and item["category"] != category:
                    continue
                if query.lower() in item["content"].lower():
                    if any(r["id"] == item["id"] for r in results):
                        continue
                    item["access_count"] = item.get("access_count", 0) + 1
                    item["last_accessed"] = datetime.now().isoformat()
                    updated_any = True
                    results.append({**item, "_similarity": 0.0})
                if len(results) >= limit:
                    break

        if not query:
            candidates = [k for k in self.knowledge_base if not category or k["category"] == category]
            candidates.sort(key=lambda x: (x.get("access_count", 0), x.get("last_accessed", "")), reverse=True)
            results = [{**k, "_similarity": 0.0} for k in candidates[:limit]]

        if updated_any:
            self.storage.save_json(self.knowledge_base, "knowledge_base.json", self.knowledge_path)

        results.sort(key=lambda x: x["_similarity"], reverse=True)
        return results[:limit]

    def cleanup_stale_knowledge(self, days: int = 60, min_access: int = 1) -> int:
        cutoff = datetime.now() - timedelta(days=days)
        cutoff_iso = cutoff.isoformat()
        kept = []
        removed = 0
        kept_indices = []

        for i, item in enumerate(self.knowledge_base):
            if item["category"] in ("reflection", "personality"):
                kept.append(item)
                kept_indices.append(i)
                continue
            last_accessed = item.get("last_accessed", item["created_at"])
            access_count = item.get("access_count", 0)
            if access_count >= min_access or last_accessed > cutoff_iso:
                kept.append(item)
                kept_indices.append(i)
            else:
                removed += 1

        if removed > 0:
            self.knowledge_base = kept
            self.storage.save_json(self.knowledge_base, "knowledge_base.json", self.knowledge_path)
            if self._vectors is not None:
                if len(kept_indices) == 0:
                    self._vectors = None
                else:
                    self._vectors = self._vectors[kept_indices]
                self._save_vectors()
            logger.info(f"[LongTermStore] 清理 {removed} 条陈旧知识，剩余 {len(kept)} 条")
        return removed
