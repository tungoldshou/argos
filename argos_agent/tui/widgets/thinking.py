# argos_agent/tui/widgets/thinking.py
"""思考态 spinner:暖橙星型字形循环 + 文案(spec §thinking)。首个 token 到达由 Transcript 移除。

实现说明:用 render() 做唯一真源 + refresh() 推帧,而非 Static.update()。
Textual 8.2.7 下从 0.12s set_interval 定时器里调 update() 会把 visual 缓存置空,
和 run_test 的快速 reflow 抢跑导致 'NoneType has no get_height' 崩溃;render()+refresh()
走 reactive/刷新正轨,不碰那条缓存竞态。renderable 属性补回(该版 Static 已改名 content),
让测试断言 th.renderable 仍成立。
"""
from __future__ import annotations

from textual.widgets import Static

_FRAMES = "·✻✽✶✳✢"


class ThinkingIndicator(Static):
    DEFAULT_CSS = """
    ThinkingIndicator { color: $accent; padding: 0 1; }
    """
    def __init__(self, label: str = "思考中…", **kwargs) -> None:
        super().__init__("", **kwargs)
        self._label = label
        self._frame = 0
        self._timer = None

    def on_mount(self) -> None:
        self._timer = self.set_interval(0.12, self._tick)

    def _tick(self) -> None:
        self._frame = (self._frame + 1) % len(_FRAMES)
        self.refresh()

    def render(self) -> str:
        return f"{_FRAMES[self._frame]} {self._label}"

    @property
    def renderable(self) -> str:
        return self.render()

    def set_label(self, label: str) -> None:
        self._label = label
        self.refresh()
