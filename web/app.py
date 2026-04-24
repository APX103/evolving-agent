"""
Web 服务启动入口
运行: python -m web.app
或: uvicorn web.app:app --reload --host 0.0.0.0 --port 8000
"""
import sys
import os

# 确保能找到 agent 模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web.api import app

if __name__ == "__main__":
    import uvicorn
    import logging
    # 降低第三方库的日志级别，避免污染控制台
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    uvicorn.run(
        "web.app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
