"""
上下文压缩器 (Context Compressor)
长对话智能摘要，保留关键决策点，避免 token 爆炸
"""
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class ContextCompressor:
    """
    上下文压缩策略：
    1. 当 short_term 超过 max_turns 时，将超出的旧消息摘要化
    2. 保留最近 N 轮完整对话（最近的用户-助手交互）
    3. 将摘要作为 "system" 或独立的 context 消息插入

    压缩触发条件（可配置）：
    - turn_count: 当消息对数超过阈值时触发
    - token_estimate: 基于字符数估算 token（粗略）
    """

    def __init__(self, llm_client=None, max_turns: int = 10, compress_batch: int = 6):
        self.llm_client = llm_client
        self.max_turns = max_turns
        self.compress_batch = compress_batch  # 每次压缩多少轮
        self.session_summary: str = ""

    def should_compress(self, short_term: List[Dict]) -> bool:
        """判断是否需要压缩（基于消息数量）"""
        return len(short_term) > self.max_turns * 2  # 每轮 2 条消息（user + assistant）

    def estimate_tokens(self, messages: List[Dict]) -> int:
        """粗略估算 token 数（中文字符 ≈ 1 token，英文 ≈ 0.25 token）"""
        total_chars = sum(len(m.get("content", "")) for m in messages)
        return int(total_chars * 0.6)

    def compress(self, short_term: List[Dict]) -> List[Dict]:
        """
        压缩 short_term 消息列表
        返回：保留的最近消息 + 可选的摘要消息
        注意：此方法不修改原始列表，调用方需自行替换
        """
        if not self.should_compress(short_term):
            return short_term

        # 保留最近的 max_turns 轮（即 max_turns*2 条消息）
        keep_count = self.max_turns * 2
        to_summarize = short_term[:-keep_count]
        kept = short_term[-keep_count:]

        if not to_summarize:
            return short_term

        summary = self._generate_summary(to_summarize)
        if summary:
            # 将摘要作为独立上下文消息插入开头
            summary_msg = {
                "role": "system",
                "content": f"【 earlier conversation summary 】\n{summary}",
                "compressed": True,
            }
            return [summary_msg] + kept

        return kept

    def _generate_summary(self, turns: List[Dict]) -> str:
        """
        生成对话摘要。
        如果有 LLM 客户端，使用 LLM 生成高质量摘要；
        否则使用简单的拼接摘要。
        """
        if self.llm_client and len(turns) >= 4:
            try:
                return self._llm_summarize(turns)
            except Exception as e:
                logger.warning(f"[ContextCompressor] LLM 摘要失败，回退到简单摘要: {e}")

        return self._simple_summarize(turns)

    def _simple_summarize(self, turns: List[Dict]) -> str:
        """简单摘要：提取每轮关键信息"""
        parts = []
        for turn in turns:
            role = turn.get("role", "")
            content = turn.get("content", "")
            # 截断过长内容
            if len(content) > 120:
                content = content[:120] + "..."
            parts.append(f"{role}: {content}")
        return "\n".join(parts)

    def _llm_summarize(self, turns: List[Dict]) -> str:
        """使用 LLM 生成摘要"""
        if not self.llm_client:
            return ""

        # 构建摘要提示
        transcript = []
        for turn in turns:
            role = "User" if turn.get("role") == "user" else "Assistant"
            content = turn.get("content", "")
            transcript.append(f"{role}: {content}")

        prompt = (
            "请将以下对话压缩为一段简洁摘要，保留关键决策、用户意图和重要信息，"
            "丢弃重复和无关细节。用中文输出：\n\n"
            + "\n".join(transcript)
            + "\n\n摘要："
        )

        messages = [{"role": "user", "content": prompt}]
        response = self.llm_client.chat(messages, temperature=0.3, max_tokens=300, stream=False)
        summary = response.get("content", "").strip() if isinstance(response, dict) else str(response).strip()

        if summary:
            logger.info(f"[ContextCompressor] LLM 摘要生成成功 ({len(turns)} 条 → {len(summary)} 字符)")
        return summary

    def update_session_summary(self, new_summary: str):
        """追加到 session_summary（跨压缩周期的累计摘要）"""
        if self.session_summary:
            self.session_summary += f"\n{new_summary}"
        else:
            self.session_summary = new_summary

    def get_full_compressed_context(
        self,
        system_prompt: str,
        short_term: List[Dict],
    ) -> List[Dict[str, str]]:
        """
        构建完整的上下文消息列表（system + 摘要 + 最近对话）
        这是 MemoryManager.get_context_messages 的替代/增强版本
        """
        messages = [{"role": "system", "content": system_prompt}]

        # 如果有跨周期的累计摘要，先插入
        if self.session_summary:
            messages.append({
                "role": "system",
                "content": f"【 session summary 】\n{self.session_summary}",
                "compressed": True,
            })

        # 压缩并添加短期记忆
        compressed = self.compress(short_term)
        messages.extend(compressed)
        return messages
