# argos_agent/tui/widgets/top_bar.py
"""TopBar:自绘单行顶栏(TUI v3 spec §4.1),替代 stock Header + sub_title 机制。

左:眼(随阶段) Argos v{version} · {model};右:状态徽标(plan / YOLO / DEMO / 未配 key / LIVE)。
徽标全部来自真实状态(诚实铁律:DEMO 标识绝不可省;真 loop 注入 demo=False 后自动消失;
has_key=False 时绝不出现 LIVE(契约6);有 key 且非 demo 时显 LIVE)。
用 render() 返回 Rich Text 做左右对齐与分段着色 —— 不走 markup 解析(防任意文本崩)。

v3 变更:
- 品牌符 ✳ → 状态眼(idle=◌ plan=◔ act=◉ verify=❂ report/done=◕)
- 新增 set_phase(phase) 接收阶段切换
- 新增 LIVE 徽标(有 key + 非 demo 时显示)
- 徽标去方括号:[plan mode] → plan;⏻ YOLO → YOLO
- DEFAULT_CSS 底色改 $well
"""
from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

# 与 theme.ARGOS_NIGHT 同源的固定色(Rich style 无法引用 Textual CSS 变量)
# v3 新色 token 映射(theme.py 里的真实值)
_EYE_SOFT = "#A8854A"   # $eye-soft:idle 暗金之眼
_EYE = "#D9A85C"        # $eye:主强调眼、当前阶段字形
_INK_BRIGHT = "#ECEEF5" # $ink-bright:品牌名
_INK_DIM = "#7E869C"    # $ink-dim:model label、阶段标签(spec §4.1)
_PLAN = "#7AA2F7"       # $plan:plan mode 蓝
_FAIL = "#F7768E"       # $fail:YOLO 危险红(裁决②)
_PASS = "#9ECE6A"       # $pass:LIVE 绿
_UNVERIF = "#FF9E64"    # $unverif:DEMO/未配key 橙

# 眼系字形:phase → glyph(spec §3.1 词典)
_PHASE_GLYPH: dict[str, str] = {
    "idle":   "◌",   # U+25CC 空态
    "plan":   "◔",   # U+25D4 扫视
    "act":    "◉",   # U+25C9 注视
    "verify": "❂",   # U+2742 聚焦
    "report": "◕",   # U+25D5 阅毕
    "done":   "◕",   # done 与 report 同形
}


class TopBar(Static):
    DEFAULT_CSS = """
    TopBar { height: 1; background: $surface; padding: 0 1; }  /* $surface 槽位即 $well 值(裸App可解析) */
    """

    def __init__(self, *, version: str = "0.x", model_label: str = "—", **kwargs) -> None:
        super().__init__("", **kwargs)
        self._version = version
        self._model = model_label
        self._plan_mode = False
        self._yolo = False
        self._demo = True
        self._has_key = True
        self._phase = "idle"

    def set_state(
        self, *,
        model_label: str | None = None,
        plan_mode: bool | None = None,
        yolo: bool | None = None,
        demo: bool | None = None,
        has_key: bool | None = None,
    ) -> None:
        """app 侧状态变化的单入口(任意子集更新);只重渲,不解析。"""
        if model_label is not None:
            self._model = model_label
        if plan_mode is not None:
            self._plan_mode = bool(plan_mode)
        if yolo is not None:
            self._yolo = bool(yolo)
        if demo is not None:
            self._demo = bool(demo)
        if has_key is not None:
            self._has_key = bool(has_key)
        self.refresh()

    def set_phase(self, phase: str) -> None:
        """接收阶段切换(plan/act/verify/report/done/idle),更新品牌眼字形。"""
        self._phase = phase
        self.refresh()

    def badges(self) -> list[str]:
        """当前应显示的徽标文本列表(渲染与测试断言共用的单一真源)。

        v3 规则:
        - plan_mode → "plan"(去方括号)
        - yolo → "YOLO"(去 ⏻ 前缀)
        - demo → "DEMO 脚本演示"
        - 非 demo + 无 key → "未配 key"
        - 非 demo + 有 key → "LIVE"(契约6:has_key=False 绝不出现 LIVE)
        """
        out: list[str] = []
        if self._plan_mode:
            out.append("plan")
        if self._yolo:
            out.append("YOLO")
        if self._demo:
            out.append("DEMO 脚本演示")
        elif not self._has_key:
            out.append("未配 key")
        else:
            # has_key=True + demo=False → 真实运行,显示 LIVE
            out.append("LIVE")
        return out

    @property
    def render_text(self) -> str:
        """纯文本快照(测试断言用)。"""
        return str(self.render())

    def render(self) -> Text:
        # 左侧:状态眼 + 品牌名 + 模型
        glyph = _PHASE_GLYPH.get(self._phase, "◌")
        eye_color = _EYE_SOFT if self._phase == "idle" else _EYE
        left = Text()
        left.append(f"{glyph} ", style=f"bold {eye_color}")
        left.append(f"Argos v{self._version}", style=f"bold {_INK_BRIGHT}")
        left.append(f" · {self._model}", style=_INK_DIM)

        # 右侧:徽标区(v3 颜色规则)
        _badge_styles: dict[str, str] = {
            "plan":          _PLAN,
            "YOLO":          _FAIL,
            "DEMO 脚本演示": _UNVERIF,
            "未配 key":      _UNVERIF,
            "LIVE":          _PASS,
        }
        right = Text()
        for i, b in enumerate(self.badges()):
            if i:
                right.append("  ")
            right.append(b, style=_badge_styles.get(b, _UNVERIF))

        width = self.size.width or 0
        pad = max(1, width - left.cell_len - right.cell_len - 2)
        return Text.assemble(left, " " * pad, right) if right.cell_len else left
