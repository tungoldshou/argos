"""pytest 全局夹具。"""
import pytest


@pytest.fixture(autouse=True)
def _force_numbered_setup_menu(monkeypatch):
    """测试环境强制 `argos setup` 向导走编号输入回退,绝不进 termios raw 模式 ——
    即便 `pytest -s` 下 stdin 是真终端,也不会卡住等待键盘(_arrow_select 见此 env 即抛 _NotATTY)。"""
    monkeypatch.setenv("ARGOS_NO_ARROW_SELECT", "1")


@pytest.fixture(autouse=True)
def _neutralize_mcp_singleton(monkeypatch):
    """测试隔离:绝不让 loop._build_system 连真实 ~/.argos/mcp.json 里的 MCP server
    (那会 spawn npx、联网下包、拖慢/污染测试,且让系统提示断言不稳)。把进程内单例的
    CONFIG_PATH 指到不存在的路径 → list_tools/tools_summary 恒空。需要测真 MCP 的用例
    自己构造独立 McpManager(config_path=...),不受此影响。"""
    from pathlib import Path

    from argos_agent import mcp_native
    mcp_native.shutdown()  # 清掉可能已建的单例
    monkeypatch.setattr(mcp_native, "CONFIG_PATH", Path("/nonexistent/argos-test/mcp.json"))
    yield
    mcp_native.shutdown()
