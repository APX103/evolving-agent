"""
分层记忆系统 (v2.1)
支持向量语义检索 + 知识去重合并 + 记忆老化
"""
import json
import os
import re
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import yaml
import numpy as np

from agent.embedding import EmbeddingClient, cosine_similarity


class MemoryManager:
    """
    三层记忆管理 + 向量索引
    - 短期记忆：当前会话
    - 工作记忆：本次关键点
    - 长期记忆：知识库（向量索引 + 语义搜索 + 去重合并）
    """

    def __init__(self, config_path: str = "config.yaml"):
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

        storage_cfg = cfg["storage"]
        self.base_path = storage_cfg["base_path"]
        self.conv_path = storage_cfg["conversations"]
        self.knowledge_path = storage_cfg["knowledge"]
        self.profile_path = storage_cfg["user_profile"]
        self.reflection_path = storage_cfg["reflections"]

        # 确保目录存在
        for p in [self.conv_path, self.knowledge_path, self.profile_path, self.reflection_path]:
            os.makedirs(p, exist_ok=True)

        # Embedding 客户端
        try:
            self.embedder = EmbeddingClient(config_path)
            self._embedding_available = True
        except Exception as e:
            print(f"[Memory] Embedding 未就绪: {e}")
            self.embedder = None
            self._embedding_available = False

        # 向量索引路径
        self.vector_path = os.path.join(self.knowledge_path, "vectors.npy")
        self.vector_meta_path = os.path.join(self.knowledge_path, "vectors_meta.json")

        # 内存中的当前会话状态
        self.short_term: List[Dict] = []
        self.working_memory: Dict = {}
        self.session_id: str = self._new_session_id()

        # 加载长期记忆
        self.knowledge_base = self._load_json("knowledge_base.json", self.knowledge_path, default=[])
        self.user_profile = self._load_json("user_profile.json", self.profile_path, default={})
        self.reflections = self._load_json("reflections.json", self.reflection_path, default=[])
        self.session_count = self.user_profile.get("session_count", 0)

        # 加载或构建向量索引
        self._vectors = self._load_vectors()
        # 🔧 修复：有知识但无向量时，重建索引
        if self._vectors is None and self.knowledge_base:
            print(f"[Memory] 检测到 {len(self.knowledge_base)} 条知识，重建向量索引...")
            self._build_all_vectors()

    # ── 底层工具 ──
    def _new_session_id(self) -> str:
        return datetime.now().strftime("%Y%m%d_%H%M%S")

    def _load_json(self, filename: str, directory: str, default=None):
        path = os.path.join(directory, filename)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return default if default is not None else {}

    def _save_json(self, data, filename: str, directory: str):
        path = os.path.join(directory, filename)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # ── 向量索引管理 ──
    def _load_vectors(self) -> Optional[np.ndarray]:
        """加载已有向量索引"""
        if os.path.exists(self.vector_path) and os.path.exists(self.vector_meta_path):
            try:
                vecs = np.load(self.vector_path)
                meta = self._load_json("vectors_meta.json", self.knowledge_path, default=[])
                # 校验长度一致
                if len(meta) == len(self.knowledge_base) == len(vecs):
                    return vecs
                else:
                    print(f"[Memory] 向量索引长度不一致，重建中...")
            except Exception as e:
                print(f"[Memory] 加载向量失败: {e}")
        return None

    def _save_vectors(self):
        """保存向量索引"""
        if self._vectors is not None:
            np.save(self.vector_path, self._vectors)
            meta = [{"id": k["id"], "idx": i} for i, k in enumerate(self.knowledge_base)]
            self._save_json(meta, "vectors_meta.json", self.knowledge_path)

    def _build_all_vectors(self):
        """全量重建向量索引"""
        if not self._embedding_available or not self.knowledge_base:
            self._vectors = None
            return

        texts = [k["content"] for k in self.knowledge_base]
        try:
            self._vectors = self.embedder.embed(texts)
            self._save_vectors()
            print(f"[Memory] 向量索引重建完成: {len(texts)} 条")
        except Exception as e:
            print(f"[Memory] 向量重建失败: {e}")
            self._vectors = None

    def _append_vector(self, text: str):
        """为单条知识追加向量"""
        if not self._embedding_available:
            return
        try:
            vec = self.embedder.embed(text)
            if self._vectors is None:
                self._vectors = vec
            else:
                self._vectors = np.vstack([self._vectors, vec])
            self._save_vectors()
        except Exception as e:
            print(f"[Memory] 追加向量失败: {e}")

    def _rebuild_vector_for(self, item: Dict):
        """🔧 修复：重建单条知识的向量（内容变更后）"""
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

            vec = self.embedder.embed(item["content"])
            self._vectors[idx] = vec[0]
            self._save_vectors()
        except Exception as e:
            print(f"[Memory] 单条向量重建失败: {e}")

    # ── 短期记忆 ──
    def add_turn(self, role: str, content: str):
        turn = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        }
        self.short_term.append(turn)

    def get_short_term(self, max_turns: int = 10) -> List[Dict]:
        return self.short_term[-max_turns:]

    def get_context_messages(self, system_prompt: str, max_turns: int = 10) -> List[Dict]:
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(self.get_short_term(max_turns))
        return messages

    # ── 工作记忆 ──
    def set_working(self, key: str, value: any):
        self.working_memory[key] = {
            "value": value,
            "timestamp": datetime.now().isoformat()
        }

    def get_working(self, key: str) -> Optional[any]:
        entry = self.working_memory.get(key)
        return entry["value"] if entry else None

    # ── 长期记忆（核心：去重合并 + 向量索引） ──
    def add_knowledge(self, category: str, content: str, source: str = "") -> Dict:
        """
        添加知识，自动去重合并
        返回: {"action": "added"|"merged"|"skipped", "id": str}
        """
        content = content.strip()
        if not content:
            return {"action": "skipped", "id": ""}

        # 1. 去重检查（语义相似度）
        duplicate = self._find_duplicate(content)
        if duplicate:
            # 合并：保留更完整的版本，更新访问时间
            merged_content = self._merge_content(duplicate["content"], content)
            duplicate["content"] = merged_content
            duplicate["last_accessed"] = datetime.now().isoformat()
            duplicate["access_count"] += 1
            duplicate["merge_count"] = duplicate.get("merge_count", 0) + 1
            self._save_json(self.knowledge_base, "knowledge_base.json", self.knowledge_path)
            # 🔧 修复：内容变了，重建该条向量
            self._rebuild_vector_for(duplicate)
            return {"action": "merged", "id": duplicate["id"]}

        # 2. 新增知识
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
        self._save_json(self.knowledge_base, "knowledge_base.json", self.knowledge_path)

        # 3. 追加向量
        self._append_vector(content)

        return {"action": "added", "id": item["id"]}

    def _find_duplicate(self, content: str) -> Optional[Dict]:
        """
        查找语义重复的知识
        先用精确匹配加速，再用向量相似度
        """
        # 精确匹配（内容完全一致或包含）
        content_lower = content.lower()
        for item in self.knowledge_base:
            if content_lower == item["content"].lower():
                return item
            # 互相包含视为重复（短句不做此判断，避免误杀）
            if len(content) > 15 and len(item["content"]) > 15:
                if content_lower in item["content"].lower() or item["content"].lower() in content_lower:
                    return item

        # 向量相似度匹配
        if not self._embedding_available or self._vectors is None or len(self.knowledge_base) == 0:
            return None

        try:
            query_vec = self.embedder.embed(content)
            sims = self.embedder.cosine_similarity(query_vec[0], self._vectors)
            best_idx = int(np.argmax(sims))
            best_sim = float(sims[best_idx])

            if best_sim > 0.85:  # 高阈值避免误判
                return self.knowledge_base[best_idx]
        except Exception:
            pass

        return None

    def _merge_content(self, old: str, new: str) -> str:
        """合并两条相似内容，保留更完整的"""
        old_l = old.lower()
        new_l = new.lower()
        if new_l in old_l:
            return old
        if old_l in new_l:
            return new
        return f"{old}\n（补充：{new}）"

    def search_knowledge(self, query: str = "", category: str = "", limit: int = 10) -> List[Dict]:
        """
        双路搜索：向量语义召回 + 字符串精确匹配兜底
        """
        results = []
        updated_any = False  # 🔧 标记是否有 access_count 被修改

        # 向量语义搜索（优先）
        if self._embedding_available and self._vectors is not None and query and len(self.knowledge_base) > 0:
            try:
                query_vec = self.embedder.embed(query)
                sims = self.embedder.cosine_similarity(query_vec[0], self._vectors)

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

                    # 标记访问
                    item["access_count"] += 1
                    item["last_accessed"] = datetime.now().isoformat()
                    updated_any = True

                    enriched = {**item, "_similarity": round(sim, 3)}
                    results.append(enriched)
            except Exception as e:
                print(f"[Memory] 向量搜索失败: {e}")

        # 字符串匹配兜底（如果向量没召回够）
        if len(results) < limit // 2 and query:
            for item in self.knowledge_base:
                if category and item["category"] != category:
                    continue
                if query.lower() in item["content"].lower():
                    if any(r["id"] == item["id"] for r in results):
                        continue
                    item["access_count"] += 1
                    item["last_accessed"] = datetime.now().isoformat()
                    updated_any = True
                    results.append({**item, "_similarity": 0.0})
                if len(results) >= limit:
                    break

        # 如果没有 query，按访问频次返回热门知识
        if not query:
            candidates = [k for k in self.knowledge_base if not category or k["category"] == category]
            candidates.sort(key=lambda x: (x["access_count"], x["last_accessed"]), reverse=True)
            results = [{**k, "_similarity": 0.0} for k in candidates[:limit]]

        # 🔧 修复：只要有 access_count 被改就保存（之前只在 results 非空时保存）
        if updated_any:
            self._save_json(self.knowledge_base, "knowledge_base.json", self.knowledge_path)

        results.sort(key=lambda x: x["_similarity"], reverse=True)
        return results[:limit]

    def update_profile(self, key: str, value: any):
        if "data" not in self.user_profile:
            self.user_profile["data"] = {}
        self.user_profile["data"][key] = {
            "value": value,
            "updated_at": datetime.now().isoformat()
        }
        self.user_profile["session_count"] = self.session_count
        self._save_json(self.user_profile, "user_profile.json", self.profile_path)

    def get_profile(self, key: str = "") -> any:
        data = self.user_profile.get("data", {})
        if key:
            entry = data.get(key)
            return entry["value"] if entry else None
        return {k: v["value"] for k, v in data.items()}

    def add_reflection(self, reflection: Dict):
        reflection["created_at"] = datetime.now().isoformat()
        self.reflections.append(reflection)
        self._save_json(self.reflections, "reflections.json", self.reflection_path)

    # ── 记忆老化与清理 ──
    def cleanup_stale_knowledge(self, days: int = 60, min_access: int = 1) -> int:
        """
        清理长时间未访问且访问次数少的知识
        返回清理数量
        """
        cutoff = datetime.now() - timedelta(days=days)
        cutoff_iso = cutoff.isoformat()

        kept = []
        removed = 0
        kept_indices = []

        for i, item in enumerate(self.knowledge_base):
            # 保留规则：高访问、近期访问、反思、用户画像
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
            self._save_json(self.knowledge_base, "knowledge_base.json", self.knowledge_path)

            # 🔧 修复：同步裁剪向量（做空保护）
            if self._vectors is not None:
                if len(kept_indices) == 0:
                    self._vectors = None
                else:
                    self._vectors = self._vectors[kept_indices]
                self._save_vectors()

            print(f"[Memory] 清理 {removed} 条陈旧知识，剩余 {len(kept)} 条")

        return removed

    # ── 会话管理 ──
    def end_session(self):
        if not self.short_term:
            return

        session_data = {
            "session_id": self.session_id,
            "started_at": self.short_term[0]["timestamp"],
            "ended_at": datetime.now().isoformat(),
            "turn_count": len(self.short_term),
            "messages": self.short_term,
            "working_memory": self.working_memory
        }

        filepath = os.path.join(self.conv_path, f"session_{self.session_id}.json")
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(session_data, f, ensure_ascii=False, indent=2)

        self.session_count += 1
        self.user_profile["session_count"] = self.session_count
        self._save_json(self.user_profile, "user_profile.json", self.profile_path)

        self.short_term = []
        self.working_memory = {}

    def get_relevant_context(self, query_hint: str = "", limit: int = 5) -> str:
        """
        构建上下文提示，支持基于当前 query 的语义召回
        """
        parts = []

        # 用户画像
        profile = self.get_profile()
        if profile:
            parts.append("【关于用户】")
            for k, v in list(profile.items())[:5]:
                parts.append(f"- {k}: {v}")

        # 语义召回知识
        if query_hint:
            relevant = self.search_knowledge(query=query_hint, limit=limit)
        else:
            relevant = self.search_knowledge(category="", limit=limit)

        if relevant:
            parts.append("\n【我记住的相关知识】")
            for item in relevant:
                sim_tag = f"(相关度{item['_similarity']})" if item.get("_similarity", 0) > 0 else ""
                parts.append(f"- [{item['category']}] {item['content']} {sim_tag}".strip())

        # 🔧 改进：只包含最近 3 次反思，避免陈旧的自我认知
        recent_reflections = self.reflections[-3:] if self.reflections else []
        if recent_reflections:
            last = recent_reflections[-1]
            parts.append(f"\n【我的自我认知】{last.get('summary', '')}")

        return "\n".join(parts) if parts else ""
