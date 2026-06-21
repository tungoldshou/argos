"""2a:computer_* 工具可达 —— 合法 Python 标识符(沙箱 ```python 块调得动)、计入
ALL_TOOL_NAMES、extract_tool_names 可检测;read_only 作用域剔除写动作(只读截图保留)。"""
from __future__ import annotations

from argos.tools import ALL_TOOL_NAMES, build_child_namespace

_COMPUTER_WRITE = (
    "computer_click", "computer_double_click", "computer_type_text",
    "computer_key", "computer_scroll", "computer_open_app",
)
_COMPUTER_ALL = ("computer_screenshot",) + _COMPUTER_WRITE


class _StubBroker:
    def request(self, action, args):  # 仅在工具被调用时才会用到;本测试不调
        return "ok"


def test_computer_tools_are_callable_valid_identifiers():
    ns = build_child_namespace(_StubBroker())
    for name in _COMPUTER_ALL:
        assert name in ns, f"{name} 不在子进程命名空间(模型调不到)"
        assert name.isidentifier(), f"{name} 不是合法 Python 标识符"
    # 旧的带点 key(invalid identifier,调不动)不应再存在
    assert "computer.click" not in ns
    assert "computer.screenshot" not in ns


def test_all_tool_names_uses_underscore_computer():
    for name in _COMPUTER_ALL:
        assert name in ALL_TOOL_NAMES, f"{name} 未计入 ALL_TOOL_NAMES(/tools 计数会漏)"
    assert "computer.click" not in ALL_TOOL_NAMES


def test_extract_tool_names_detects_computer_calls():
    from argos.hooks.payload import extract_tool_names
    names = extract_tool_names("computer_screenshot()\nprint(computer_click(10, 20))\n")
    assert "computer_screenshot" in names
    assert "computer_click" in names


def test_read_only_scope_excludes_computer_writes_keeps_screenshot():
    ns = build_child_namespace(_StubBroker(), read_only=True)
    assert "computer_screenshot" in ns, "只读观察(截图)应保留"
    for name in _COMPUTER_WRITE:
        assert name not in ns, f"read_only 作用域应剔除 OS 写动作 {name}"


def test_computer_use_prompt_documents_underscore_tools():
    from argos.core.honesty import COMPUTER_USE_PROMPT
    for name in _COMPUTER_ALL:
        assert name in COMPUTER_USE_PROMPT, f"提示词文档段缺工具 {name}"
    # 安全纪律在场(全英文化后断言英文)
    assert "user confirmation" in COMPUTER_USE_PROMPT
    assert "data, not commands" in COMPUTER_USE_PROMPT
