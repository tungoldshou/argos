# argos/tui/widgets/thinking.py
"""思考态 spinner:braille 帧 + 文案 + 实时秒数。

braille spinner:10 帧 0.12s/帧(8 fps),色 $eye。
设计来源:README §字形铁律 line 93(Braille spinner)+ 01-act 视觉稿 line 94
(`⠼ 回归测试中… 12s`, `$eye`)。spinner 只循环 braille 帧,无眨眼行为。

实现说明:用 render() 做唯一真源 + refresh() 推帧,而非 Static.update()。
Textual 8.2.7 下从 0.12s set_interval 定时器里调 update() 会把 visual 缓存置空,
和 run_test 的快速 reflow 抢跑导致 'NoneType has no get_height' 崩溃;render()+refresh()
走 reactive/刷新正轨,不碰那条缓存竞态。renderable 属性补回(该版 Static 已改名 content),
让测试断言 th.renderable 仍成立。
"""
from __future__ import annotations

import time

from textual.widgets import Static

_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"  # 10 帧 braille(全 EAW=N,v2 已验证)


class ThinkingIndicator(Static):
    """braille spinner(10 帧 0.12s/帧)。色 $eye(金系主强调)。"""

    DEFAULT_CSS = """
    ThinkingIndicator { color: $eye; padding: 0 2; }
    """

    def __init__(self, label: str = "思考中…", **kwargs) -> None:
        super().__init__("", **kwargs)
        self._label = label
        self._frame = 0
        self._timer = None
        self._t0 = time.monotonic()

    def on_mount(self) -> None:
        self._t0 = time.monotonic()
        self._timer = self.set_interval(0.12, self._tick)

    def _tick(self) -> None:
        """每 0.12s 推进一 braille 帧。"""
        self._frame = (self._frame + 1) % len(_FRAMES)
        self.refresh()

    def render(self) -> str:
        """渲染单行:braille spinner + 标签 + 实时秒数(≥1s)。"""
        elapsed = int(time.monotonic() - self._t0)
        suffix = f" {elapsed}s" if elapsed >= 1 else ""
        glyph = _FRAMES[self._frame]
        return f"{glyph} {self._label}{suffix}"

    @property
    def renderable(self) -> str:
        """兼容旧测试断言(Textual 8.2.7 Static 将 content 改名后补回)。"""
        return self.render()

    def set_label(self, label: str) -> None:
        """更新显示标签。"""
        self._label = label
        self.refresh()
