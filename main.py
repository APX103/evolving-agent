"""
CLI 入口 (v4.0 多 Agent 模式)
运行方式:
  python main.py                    # 经典模式（v3.2 兼容）
  python main.py --mode multi       # 多 Agent 协作模式
  python main.py --mode multi --user <user_id>
"""
import sys
import os
import logging
import argparse

# 将项目根目录加入路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent.config import Config


def setup_logging():
    """配置日志：终端彩色输出 + 文件记录"""
    log_dir = "./storage/logs"
    os.makedirs(log_dir, exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S"
    )

    # 文件 handler
    file_handler = logging.FileHandler(
        os.path.join(log_dir, "agent.log"),
        encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)

    # 控制台 handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(file_handler)
    root.addHandler(console_handler)


def print_banner(version="3.2"):
    multi_tag = " [多 Agent 模式]" if version == "4.0" else ""
    print("=" * 55)
    print(f"  🦞 Evolving Agent — 越聊越聪明 (v{version}){multi_tag}")
    print("=" * 55)
    print("  输入你想说的话，和 Agent 对话")
    print("  特殊命令:")
    print("    /bye   - 结束当前会话并触发后台学习")
    print("    /stats - 查看 Agent 成长统计")
    print("    /mem   - 查看当前记忆摘要")
    print("    /clean - 清理陈旧知识")
    print("    /skills - 查看已注册 Skills")
    print("    /personality - 查看当前人格状态")
    print("    /agents - 查看可用的 Agent 列表 (v4.0)")
    print("    /help  - 显示帮助")
    print("=" * 55)
    print()


def run_classic_mode(args):
    """经典模式（v3.2 兼容）"""
    from agent.core import EvolvingAgent

    print_banner("3.2")

    if not os.path.exists("config.yaml"):
        print("❌ 配置文件不存在！")
        print("请复制模板并编辑：cp config.yaml.example config.yaml")
        return

    try:
        agent = EvolvingAgent("config.yaml", user_id=args.user)
    except Exception as e:
        print(f"❌ 初始化失败: {e}")
        return

    print(f"✅ {agent.name} 已上线！\n")

    while True:
        try:
            user_input = input("你 > ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n");
            user_input = "/bye"

        if not user_input:
            continue

        if user_input == "/bye":
            agent.end_session()
            print("再见！下次我会更聪明 👋\n")
            continue

        if user_input in ("/stats", "/mem", "/clean", "/skills", "/personality", "/help"):
            _handle_classic_command(agent, user_input)
            continue

        try:
            response = agent.chat(user_input)
            if isinstance(response, str):
                print(f"{agent.name} > {response}\n")
            else:
                print(f"{agent.name} > ", end="", flush=True)
                full_text = ""
                for chunk in response:
                    print(chunk, end="", flush=True)
                    full_text += chunk
                print("\n")
                agent.finalize_response(user_input, full_text)
        except Exception as e:
            print(f"❌ 出错了: {e}\n")


def _handle_classic_command(agent, cmd):
    """处理经典模式命令"""
    if cmd == "/stats":
        stats = agent.get_stats()
        print(f"\n📊 {stats['name']} 的成长统计")
        print(f"   累计会话: {stats['total_sessions']}")
        print(f"   知识库: {stats['knowledge_count']} 条")
        if 'triples_count' in stats:
            print(f"   知识图谱: {stats['triples_count']} 三元组")
        print(f"   反思次数: {stats['reflection_count']}")
        print()
    elif cmd == "/mem":
        context = agent.memory.get_relevant_context()
        print(f"\n🧠 当前记忆:\n{context or '还没有积累什么记忆'}\n")
    elif cmd == "/clean":
        removed = agent.memory.cleanup_stale_knowledge(days=60, min_access=1)
        print(f"\n🧹 清理了 {removed} 条陈旧知识\n" if removed else "\n🧹 没有需要清理的陈旧知识\n")
    elif cmd == "/skills":
        skills = agent.skills.list_skills()
        print(f"\n🔧 已注册 Skills ({len(skills)}个):")
        for s in skills:
            print(f"   {s['name']:12s} | {s['description']}")
        print()
    elif cmd == "/personality":
        print(f"\n{agent.get_personality_summary()}\n")
    elif cmd == "/help":
        print_banner("3.2")


def run_multi_agent_mode(args):
    """多 Agent 协作模式 (v4.0)"""
    import asyncio
    from agent.core import EvolvingAgent
    from agent.multi_agent.agents_init import create_registry

    print_banner("4.0")

    if not os.path.exists("config.yaml"):
        print("❌ 配置文件不存在！")
        print("请复制模板并编辑：cp config.yaml.example config.yaml")
        return

    try:
        # 用经典 Agent 作为 memory/llm 来源
        classic_agent = EvolvingAgent("config.yaml", user_id=args.user)
        registry = create_registry(
            classic_agent.memory,
            classic_agent.llm_client,
            classic_agent.config.raw.get("multi_agent", {})
        )
    except Exception as e:
        print(f"❌ 初始化失败: {e}")
        return

    agents_info = registry.list_agents()
    print(f"✅ 多 Agent 系统已启动！")
    print(f"   可用 Agent: {', '.join(a['name'] for a in agents_info)}")
    print(f"   Router 会自动为你选择最合适的 Agent\n")

    async def chat_loop():
        while True:
            try:
                user_input = input("你 > ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\n");
                user_input = "/bye"

            if not user_input:
                continue

            if user_input == "/bye":
                classic_agent.end_session()
                print("再见！下次我会更聪明 👋\n")
                continue

            if user_input == "/agents":
                print(f"\n🤖 可用 Agent 列表:")
                for a in agents_info:
                    print(f"   • {a['name']}: {a['description']}")
                print()
                continue

            if user_input in ("/stats", "/mem", "/clean", "/skills", "/personality", "/help"):
                _handle_classic_command(classic_agent, user_input)
                continue

            try:
                response = await registry.process(user_input, args.user, source="cli")
                agent_tag = f"[{response.agent_name}]" if response.agent_name != "companion" else ""
                print(f"{classic_agent.name}{agent_tag} > {response.content}\n")
            except Exception as e:
                print(f"❌ 出错了: {e}\n")

    asyncio.run(chat_loop())


def main():
    parser = argparse.ArgumentParser(description="Evolving Agent CLI (v4.0)")
    parser.add_argument("--user", default="default", help="用户 ID（多用户隔离）")
    parser.add_argument("--mode", choices=["classic", "multi"], default="classic",
                       help="运行模式: classic=经典模式, multi=多 Agent 协作模式")
    args = parser.parse_args()

    setup_logging()

    if args.mode == "multi":
        run_multi_agent_mode(args)
    else:
        run_classic_mode(args)


if __name__ == "__main__":
    main()
