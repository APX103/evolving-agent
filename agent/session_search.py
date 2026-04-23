"""
SQLite FTS5 会话全文搜索
索引所有历史消息，支持时间/关键词/多模态搜索
"""
import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class SessionSearchEngine:
    """
    会话全文搜索引擎
    - SQLite FTS5 虚拟表索引所有对话消息
    - 支持自然语言关键词搜索、时间范围过滤、角色过滤
    - 比向量搜索更适合精确匹配（如"上周说的那个方案"）
    """

    def __init__(self, db_path: str = "./storage/conversations.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _init_db(self):
        """初始化 FTS5 表结构"""
        conn = self._get_conn()
        # 主表：消息内容
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS messages USING fts5(
                content,
                role,
                user_id,
                session_id,
                timestamp,
                token=porter
            )
        """)
        # 辅助表：会话元数据
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                user_id TEXT,
                start_time TEXT,
                end_time TEXT,
                message_count INTEGER DEFAULT 0,
                summary TEXT
            )
        """)
        conn.commit()
        logger.info("[SessionSearch] FTS5 数据库初始化完成")

    def index_message(self, user_id: str, session_id: str, role: str,
                      content: str, timestamp: Optional[str] = None):
        """索引单条消息"""
        if not content or not content.strip():
            return
        ts = timestamp or datetime.now().isoformat()
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO messages (content, role, user_id, session_id, timestamp) VALUES (?, ?, ?, ?, ?)",
                (content, role, user_id, session_id, ts)
            )
            conn.commit()
        except Exception as e:
            logger.warning(f"[SessionSearch] 索引消息失败: {e}")

    def index_session(self, user_id: str, session_id: str, messages: List[Dict],
                      summary: str = ""):
        """批量索引一个会话的所有消息"""
        if not messages:
            return
        conn = self._get_conn()
        try:
            for msg in messages:
                content = msg.get("content", "")
                if not content:
                    continue
                conn.execute(
                    "INSERT INTO messages (content, role, user_id, session_id, timestamp) VALUES (?, ?, ?, ?, ?)",
                    (content, msg.get("role", "unknown"), user_id, session_id,
                     msg.get("timestamp", datetime.now().isoformat()))
                )
            # 更新会话元数据
            start_time = messages[0].get("timestamp", datetime.now().isoformat())
            end_time = messages[-1].get("timestamp", datetime.now().isoformat())
            conn.execute(
                """INSERT OR REPLACE INTO sessions
                   (session_id, user_id, start_time, end_time, message_count, summary)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (session_id, user_id, start_time, end_time, len(messages), summary)
            )
            conn.commit()
            logger.info(f"[SessionSearch] 索引会话 {session_id}: {len(messages)} 条消息")
        except Exception as e:
            logger.warning(f"[SessionSearch] 索引会话失败: {e}")

    def search(self, query: str, user_id: Optional[str] = None,
               role: Optional[str] = None,
               days: Optional[int] = None,
               limit: int = 10) -> List[Dict]:
        """
        全文搜索（FTS5 MATCH + LIKE fallback for CJK）
        """
        conn = self._get_conn()
        results = []

        # 1. 尝试 FTS5 MATCH（对英文效果好）
        try:
            sql = "SELECT * FROM messages WHERE content MATCH ?"
            params = [query]
            conditions = []
            if user_id:
                conditions.append("user_id = ?")
                params.append(user_id)
            if role:
                conditions.append("role = ?")
                params.append(role)
            if days:
                since = (datetime.now() - timedelta(days=days)).isoformat()
                conditions.append("timestamp > ?")
                params.append(since)
            if conditions:
                sql += " AND " + " AND ".join(conditions)
            sql += " ORDER BY rank LIMIT ?"
            params.append(limit)

            rows = conn.execute(sql, params).fetchall()
            for row in rows:
                results.append({
                    "content": row["content"],
                    "role": row["role"],
                    "user_id": row["user_id"],
                    "session_id": row["session_id"],
                    "timestamp": row["timestamp"],
                })
        except Exception as e:
            logger.debug(f"[SessionSearch] MATCH 失败: {e}")

        # 2. 如果 MATCH 无结果（常见于中文），fallback 到 LIKE
        if not results:
            try:
                sql = "SELECT * FROM messages WHERE content LIKE ?"
                params = [f"%{query}%"]
                conditions = []
                if user_id:
                    conditions.append("user_id = ?")
                    params.append(user_id)
                if role:
                    conditions.append("role = ?")
                    params.append(role)
                if days:
                    since = (datetime.now() - timedelta(days=days)).isoformat()
                    conditions.append("timestamp > ?")
                    params.append(since)
                if conditions:
                    sql += " AND " + " AND ".join(conditions)
                sql += " ORDER BY timestamp DESC LIMIT ?"
                params.append(limit)

                rows = conn.execute(sql, params).fetchall()
                for row in rows:
                    results.append({
                        "content": row["content"],
                        "role": row["role"],
                        "user_id": row["user_id"],
                        "session_id": row["session_id"],
                        "timestamp": row["timestamp"],
                    })
            except Exception as e:
                logger.warning(f"[SessionSearch] LIKE fallback 失败: {e}")

        return results

    def search_with_context(self, query: str, user_id: Optional[str] = None,
                           context_window: int = 2) -> List[Dict]:
        """
        带上下文窗口的搜索
        返回匹配消息及其前后 context_window 条消息
        """
        matches = self.search(query, user_id=user_id, limit=10)
        if not matches:
            return []

        conn = self._get_conn()
        enriched = []
        for match in matches:
            # 获取同一 session 中前后消息
            session_id = match["session_id"]
            ts = match["timestamp"]
            try:
                before = conn.execute(
                    """SELECT content, role, timestamp FROM messages
                       WHERE session_id = ? AND timestamp < ?
                       ORDER BY timestamp DESC LIMIT ?""",
                    (session_id, ts, context_window)
                ).fetchall()
                after = conn.execute(
                    """SELECT content, role, timestamp FROM messages
                       WHERE session_id = ? AND timestamp > ?
                       ORDER BY timestamp ASC LIMIT ?""",
                    (session_id, ts, context_window)
                ).fetchall()

                context = []
                for row in reversed(before):
                    context.append({"role": row["role"], "content": row["content"]})
                context.append({"role": match["role"], "content": match["content"], "match": True})
                for row in after:
                    context.append({"role": row["role"], "content": row["content"]})

                enriched.append({
                    "match": match,
                    "context": context,
                    "session_id": session_id,
                })
            except Exception as e:
                logger.warning(f"[SessionSearch] 获取上下文失败: {e}")
                enriched.append({"match": match, "context": []})

        return enriched

    def recent_sessions(self, user_id: str, limit: int = 5) -> List[Dict]:
        """获取最近的会话列表"""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """SELECT * FROM sessions WHERE user_id = ?
                   ORDER BY start_time DESC LIMIT ?""",
                (user_id, limit)
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.warning(f"[SessionSearch] 获取会话失败: {e}")
            return []

    def delete_old_messages(self, days: int = 365):
        """清理旧消息"""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        conn = self._get_conn()
        try:
            conn.execute("DELETE FROM messages WHERE timestamp < ?", (cutoff,))
            conn.commit()
            logger.info(f"[SessionSearch] 清理 {days} 天前的消息")
        except Exception as e:
            logger.warning(f"[SessionSearch] 清理失败: {e}")

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None
