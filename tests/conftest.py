"""pytest 全局夹具。"""
import pytest


@pytest.fixture(autouse=True)
def _force_numbered_setup_menu(monkeypatch):
    """测试环境强制 `argos setup` 向导走编号输入回退,绝不进 termios raw 模式 ——
    即便 `pytest -s` 下 stdin 是真终端,也不会卡住等待键盘(_arrow_select 见此 env 即抛 _NotATTY)。"""
    monkeypatch.setenv("ARGOS_NO_ARROW_SELECT", "1")
