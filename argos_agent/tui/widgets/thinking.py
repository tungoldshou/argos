# argos_agent/tui/widgets/thinking.py
"""思考态 spinner(TUI v3 spec §6.1 §6.2):braille 帧 + 文案 + 实时秒数 + 眼慢眨。

braille spinner:10 帧 0.12s/帧(8 fps),色 $eye。
眼慢眨(§6.2):~4s 周期 ◉→◓→◉ 两帧,单字符变化零重排。
  - 每 _BLINK_INTERVAL_TICKS 个 spinner tick(约 4s)触发一次慢眨序列。
  - 慢眨期间短暂将 spinner 字形替换为 ◓,下一 tick 恢复 ◉——仅 1 字符改动,无重排。

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

# 眼慢眨帧:◉(注视/act,U+25C9)→◓(半阖/等待,U+25D3)→◉ — 两个字形均 EAW=N
_BLINK_GLYPHS = ("◉", "◓")

# 每隔多少个 spinner tick(0.12s)触发一次慢眨;~4s = 33 ticks
_BLINK_INTERVAL_TICKS = 33
# 慢眨持续的 tick 数:1 tick = 0.12s,保持短促(半阖感)
_BLINK_HOLD_TICKS = 2


class ThinkingIndicator(Static):
    """braille spinner + 眼慢眨(§6.1/§6.2)。色 $eye(金系主强调)。"""

    DEFAULT_CSS = """
    ThinkingIndicator { color: $eye; padding: 0 2; }
    """

    def __init__(self, label: str = "思考中…", **kwargs) -> None:
        super().__init__("", **kwargs)
        self._label = label
        self._frame = 0
        self._timer = None
        self._t0 = time.monotonic()
        self._tick_count = 0        # 自挂载以来的 tick 总数
        self._blink_ticks_left = 0  # 剩余慢眨 hold tick 数(>0 = 眨中)

    def on_mount(self) -> None:
        self._t0 = time.monotonic()
        self._timer = self.set_interval(0.12, self._tick)

    def _tick(self) -> None:
        """每 0.12s 推进一帧;每 ~4s 触发一次眼慢眨。"""
        self._tick_count += 1
        if self._blink_ticks_left > 0:
            # 眨中:倒计时,到期后恢复 spinner 帧推进
            self._blink_ticks_left -= 1
        else:
            # 正常推进 spinner 帧
            self._frame = (self._frame + 1) % len(_FRAMES)
            # 到达慢眨间隔时,开始一次慢眨
            if self._tick_count % _BLINK_INTERVAL_TICKS == 0:
                self._blink_ticks_left = _BLINK_HOLD_TICKS
        self.refresh()

    def render(self) -> str:
        """渲染单行:spinner(或眨眼字形) + 标签 + 实时秒数(≥1s)。"""
        elapsed = int(time.monotonic() - self._t0)
        suffix = f" {elapsed}s" if elapsed >= 1 else ""
        # 眨眼期间用 ◓(半阖),否则用当前 braille 帧
        if self._blink_ticks_left > 0:
            glyph = _BLINK_GLYPHS[1]  # ◓ 半阖
        else:
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
