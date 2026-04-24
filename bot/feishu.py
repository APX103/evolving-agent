"""
飞书机器人启动入口
运行: python -m bot.feishu
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import logging
from bot.feishu_adapter import FeishuBotAdapter, FeishuConfig
from agent.core.config import Config

logger = logging.getLogger("bot.feishu")


async def main():
    config = Config("config.yaml")
    feishu_cfg = config.raw.get("feishu", {})

    if not feishu_cfg.get("enabled", False):
        print("飞书机器人未启用，请在 config.yaml 中设置 feishu.enabled: true")
        return

    bot_config = FeishuConfig(
        app_id=feishu_cfg["app_id"],
        app_secret=feishu_cfg["app_secret"],
        encrypt_key=feishu_cfg.get("encrypt_key", ""),
        verification_token=feishu_cfg.get("verification_token", ""),
        bot_name=feishu_cfg.get("bot_name", "Evo"),
        session_ttl=feishu_cfg.get("session_ttl", 1800),
    )

    adapter = FeishuBotAdapter(bot_config)
    await adapter.start()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
