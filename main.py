"""
CLI 入口
运行方式: python main.py
"""
import sys
import os

# 将项目根目录加入路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent.core import EvolvingAgent


def print_banner():
    print("=" * 50)
    print("  🦞 Evolving Agent — 越聊越聪明 (v2.5)")
    print("=" * 50)
    print("  输入你想说的话，和 Agent 对话")
    print("  特殊命令:")
    print("    /bye   - 结束当前会话并触发后台学习")
    print("    /stats - 查看 Agent 成长统计")
    print("    /mem   - 查看当前记忆摘要")
    print("    /clean - 清理陈旧知识")
    print("    /skills - 查看已注册 Skills")
    print("    /personality - 查看当前人格状态")
    print("    /help  - 显示帮助")
    print("=" * 50)
    print()


def main():
    print_banner()
    
    # 检查配置文件
    if not os.path.exists("config.yaml"):
        print("❌ 配置文件不存在！")
        print("请复制模板并编辑：")
        print("  cp config.yaml.example config.yaml")
        print("然后填入你的 Kimi API Key。")
        return
    
    # 初始化 Agent
    try:
        agent = EvolvingAgent("config.yaml")
    except Exception as e:
        print(f"❌ 初始化失败: {e}")
        print("请检查 config.yaml 中的 API Key 是否正确。")
        return
    
    print(f"✅ {agent.name} 已上线！开始聊天吧~")
    print(f"   人格: {agent.personality.get_all()}")
    print(f"   Skills: {', '.join([s['name'] for s in agent.skills.list_skills()])}\n")
    
    # 对话循环
    while True:
        try:
            user_input = input("你 > ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n")
            user_input = "/bye"
        
        if not user_input:
            continue
        
        # 处理命令
        if user_input == "/bye":
            agent.end_session()
            print("再见！下次我会更聪明 👋\n")
            continue
        
        if user_input == "/stats":
            stats = agent.get_stats()
            print(f"\n📊 {stats['name']} 的成长统计")
            print(f"   累计会话: {stats['total_sessions']}")
            print(f"   知识库: {stats['knowledge_count']} 条")
            print(f"   反思次数: {stats['reflection_count']}")
            print(f"   用户画像: {', '.join(stats['profile_keys']) if stats['profile_keys'] else '（暂无）'}")
            print(f"   当前会话: {'进行中' if stats['current_session_active'] else '已结束'}\n")
            continue
        
        if user_input == "/mem":
            context = agent.memory.get_relevant_context()
            if context:
                print(f"\n🧠 当前记忆:\n{context}\n")
            else:
                print("\n🧠 还没有积累什么记忆，多聊聊吧！\n")
            continue
        
        if user_input == "/clean":
            removed = agent.memory.cleanup_stale_knowledge(days=60, min_access=1)
            if removed:
                print(f"\n🧹 清理了 {removed} 条陈旧知识\n")
            else:
                print("\n🧹 没有需要清理的陈旧知识\n")
            continue
        
        if user_input == "/skills":
            skills = agent.skills.list_skills()
            print(f"\n🔧 已注册 Skills ({len(skills)}个):")
            for s in skills:
                print(f"   {s['name']:12s} | {s['description']} (优先级{s['priority']})")
            print()
            continue
        
        if user_input == "/personality":
            print(f"\n{agent.get_personality_summary()}\n")
            print(f"   当前 temperature: {agent.personality.get_temperature()}")
            print(f"   当前 max_tokens:  {agent.personality.get_max_tokens()}\n")
            continue
        
        if user_input == "/help":
            print_banner()
            continue
        
        # 正常对话
        try:
            response = agent.chat(user_input)
            
            # Skill 直接返回字符串
            if isinstance(response, str):
                print(f"{agent.name} > {response}\n")
            else:
                # LLM 流式输出（生成器）
                print(f"{agent.name} > ", end="", flush=True)
                full_text = ""
                for chunk in response:
                    print(chunk, end="", flush=True)
                    full_text += chunk
                print("\n")
                
                # 流式结束后收尾：记录记忆 + 实时学习
                agent.finalize_response(user_input, full_text)
        except Exception as e:
            print(f"❌ 出错了: {e}\n")


if __name__ == "__main__":
    main()
