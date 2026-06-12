"""perception.actions — OS 级计算机动作的冻结值对象。

ComputerAction 是对一次 OS 级操作的不可变描述,由 ComputerExecutor 执行。
字段校验在构造时完成(fail-fast);不合法入参抛 ValueError。

动作种类(kind):
  screenshot    — 截取全屏;不需要坐标/文本
  click         — 单击,需要 (x, y)
  double_click  — 双击,需要 (x, y)
  type_text     — 在当前焦点处键入文本,需要 text
  key           — 发送快捷键序列(如 "command+c"),需要 text
  scroll        — 在 (x, y) 处滚动 dy 行,需要 (x, y) + text=str(dy)
  open_app      — 用 `open -a` 打开应用,需要 app 名称

text 长度上限 TEXT_MAX_LEN = 2000,防止一次注入超长字符串。
app 名仅允许 [A-Za-z0-9 _.-] 字符集(防 shell 注入)。
坐标必须 >= 0(屏幕坐标系从左上角 0,0 起)。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

# ── 常量 ─────────────────────────────────────────────────────────────────────

ActionKind = Literal[
    "screenshot",
    "click",
    "double_click",
    "type_text",
    "key",
    "scroll",
    "open_app",
]

TEXT_MAX_LEN = 2000
# app 名白名单字符集:字母/数字/空格/下划线/连字符/点(防 shell 注入)
_APP_NAME_RE = re.compile(r"^[A-Za-z0-9 _.\-]+$")


@dataclass(frozen=True, slots=True)
class ComputerAction:
    """一次 OS 级计算机操作的不可变描述。

    字段含义:
      kind        — 动作种类(见模块文档)
      x           — 屏幕 x 坐标(像素),click/double_click/scroll 必填
      y           — 屏幕 y 坐标(像素),click/double_click/scroll 必填
      text        — 文本内容;type_text/key 为文本/快捷键;scroll 为 str(dy)
      app         — open_app 时的应用名称

    __post_init__ 做完整合法性校验:
      · 坐标非负
      · text 长度 <= TEXT_MAX_LEN
      · app 名仅含白名单字符
      · 各 kind 对应的必填字段不得缺失
    """
    kind: ActionKind
    x: int | None = None
    y: int | None = None
    text: str | None = None
    app: str | None = None

    def __post_init__(self) -> None:
        # ── 坐标非负校验 ────────────────────────────────────────────────────
        for name, val in (("x", self.x), ("y", self.y)):
            if val is not None and val < 0:
                raise ValueError(f"ComputerAction.{name} 必须 >= 0,得到 {val!r}")

        # ── text 长度上限 ────────────────────────────────────────────────────
        if self.text is not None and len(self.text) > TEXT_MAX_LEN:
            raise ValueError(
                f"ComputerAction.text 超过上限 {TEXT_MAX_LEN} 字符"
                f"(实际 {len(self.text)} 字符)"
            )

        # ── app 名白名单字符集(非空才检查;空串留给 open_app 必填校验报更清晰错误)──
        if self.app is not None and self.app != "" and not _APP_NAME_RE.match(self.app):
            raise ValueError(
                f"ComputerAction.app 名 {self.app!r} 含非法字符"
                f"(仅允许 A-Za-z0-9 空格 _ . -)"
            )

        # ── 各 kind 必填字段 ─────────────────────────────────────────────────
        if self.kind in ("click", "double_click"):
            if self.x is None or self.y is None:
                raise ValueError(
                    f"kind={self.kind!r} 需要 x 和 y 坐标"
                )
        elif self.kind in ("type_text", "key"):
            if not self.text:
                raise ValueError(
                    f"kind={self.kind!r} 需要非空 text"
                )
        elif self.kind == "scroll":
            if self.x is None or self.y is None:
                raise ValueError("kind='scroll' 需要 x 和 y 坐标")
            if not self.text:
                raise ValueError("kind='scroll' 需要 text=str(dy) 表示滚动行数")
        elif self.kind == "open_app":
            if not self.app:
                raise ValueError("kind='open_app' 需要非空 app 名称")
        # screenshot 无需额外字段
