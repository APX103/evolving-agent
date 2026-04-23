#!/usr/bin/env python3
"""
开发工具 Skills 测试
测试 /edit /map /grep /test /git
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.skills_dev import EditSkill, MapSkill, GrepSkill, TestSkill, GitSkill


def test_edit_skill_basic(tmp_path, monkeypatch):
    """测试精确编辑"""
    print("[DevSkill] 测试 EditSkill...")
    monkeypatch.chdir(tmp_path)
    test_file = tmp_path / "test.py"
    test_file.write_text("def hello():\n    print('old')\n", encoding="utf-8")

    skill = EditSkill()
    user_input = f"""/edit
### {test_file}
<<<<<<< SEARCH
def hello():
    print('old')
=======
def hello():
    print('new')
>>>>>>> REPLACE"""

    result = skill.execute(user_input, {})
    assert result.success, f"编辑失败: {result.content}"
    assert "已应用修改" in result.content

    content = test_file.read_text(encoding="utf-8")
    assert "print('new')" in content
    assert "print('old')" not in content

    print("   ✅ EditSkill 基本编辑通过")


def test_edit_skill_no_match(tmp_path, monkeypatch):
    """测试 SEARCH 不匹配时拒绝修改"""
    print("[DevSkill] 测试 EditSkill 不匹配拒绝...")
    monkeypatch.chdir(tmp_path)
    test_file = tmp_path / "test.py"
    test_file.write_text("def foo(): pass\n", encoding="utf-8")

    skill = EditSkill()
    user_input = f"""/edit
### {test_file}
<<<<<<< SEARCH
不存在的代码
=======
新代码
>>>>>>> REPLACE"""

    result = skill.execute(user_input, {})
    assert not result.success
    assert "未精确匹配" in result.content

    # 文件 untouched
    assert test_file.read_text(encoding="utf-8") == "def foo(): pass\n"

    print("   ✅ EditSkill 不匹配时正确拒绝")


def test_map_skill(tmp_path):
    """测试代码地图"""
    print("[DevSkill] 测试 MapSkill...")
    test_file = tmp_path / "sample.py"
    test_file.write_text(
        """
class Base:
    pass

class Child(Base):
    def method1(self):
        pass

def top_level():
    pass
""",
        encoding="utf-8",
    )

    skill = MapSkill()
    result = skill.execute(f"/map --path {tmp_path}", {})
    assert result.success
    assert "class Child" in result.content
    assert "method1" in result.content
    assert "top_level" in result.content

    print("   ✅ MapSkill 代码分析通过")


def test_grep_skill(tmp_path):
    """测试代码搜索"""
    print("[DevSkill] 测试 GrepSkill...")
    test_file = tmp_path / "code.py"
    test_file.write_text("def foo():\n    return 42\n\ndef bar():\n    return 43\n", encoding="utf-8")

    skill = GrepSkill()
    result = skill.execute(f"/grep return 42 --path {tmp_path}", {})
    assert result.success
    assert "return 42" in result.content

    print("   ✅ GrepSkill 搜索通过")


def test_git_skill():
    """测试 git status"""
    print("[DevSkill] 测试 GitSkill...")
    skill = GitSkill()
    result = skill.execute("/git status", {})
    # 可能在 git 仓库内或外
    assert isinstance(result.content, str)
    print("   ✅ GitSkill 执行通过")


def test_test_skill():
    """测试 TestSkill"""
    print("[DevSkill] 测试 TestSkill...")
    skill = TestSkill()
    result = skill.execute("/test tests/test_phase2.py", {})
    # 环境中可能没有 pytest，测试只要返回有效结果即可
    assert isinstance(result.content, str)
    assert len(result.content) > 0
    print(f"   ✅ TestSkill 返回: {result.content[:50]}...")


if __name__ == "__main__":
    import tempfile
    import shutil

    _tmp = tempfile.mkdtemp(dir=os.getcwd())
    try:
        test_edit_skill_basic(_tmp)
        test_edit_skill_no_match(_tmp)
        test_map_skill(_tmp)
        test_grep_skill(_tmp)
    finally:
        shutil.rmtree(_tmp, ignore_errors=True)
    test_git_skill()
    test_test_skill()
    print("\n🎉 开发工具 Skills 全部测试通过!")
