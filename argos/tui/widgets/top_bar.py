# argos/tui/widgets/top_bar.py
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

from argos.i18n import t

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
    "idle":    "◌",   # U+25CC 空态
    "plan":    "◔",   # U+25D4 扫视
    "act":     "◉",   # U+25C9 注视
    "verify":  "❂",   # U+2742 聚焦
    "report":  "◕",   # U+25D5 阅毕
    "done":    "◕",   # done 与 report 同形
    "blocked": "◓",   # U+25D3 审批/硬确认挂起 — $unverif 橙(字形铁律 README §字形铁律 line 85)
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
        # Trust 徽标状态(README §152/§188;默认无 trust 信息时不显示)
        self._trust_level: int | None = None   # 0–4;None=未设置,不渲染 Trust 徽标
        self._trust_label: str = ""            # e.g. "只有危险操作才问"

    def set_state(
        self, *,
        model_label: str | None = None,
        plan_mode: bool | None = None,
        yolo: bool | None = None,
        demo: bool | None = None,
        has_key: bool | None = None,
        trust_level: int | None = None,
        trust_label: str | None = None,
    ) -> None:
        """app 侧状态变化的单入口(任意子集更新);只重渲,不解析。

        trust_level: 0–4(L0 最宽松/L4 最严格);None=不更改当前值。
        trust_label: 与 trust_level 配套的短描述(如 '只有危险操作才问')。
        """
        if model_label is not None:
            self._model = model_label
        if plan_mode is not None:
            self._plan_mode = bool(plan_mode)
        if yolo is not None:
            self._yolo = bool(yolo)
        # ponytail: demo 参数现为显示惰性 shim —— DEMO 徽标已移除(2026-07-01),保留入参
        # 仅为兼容既有测试构造点。彻底清理 = 删 demo 入参 + ~17 个测试调用点(留作后续机械 pass)。
        if demo is not None:
            self._demo = bool(demo)
        if has_key is not None:
            self._has_key = bool(has_key)
        if trust_level is not None:
            self._trust_level = int(trust_level)
        if trust_label is not None:
            self._trust_label = trust_label
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
        - 无 key → "未配 key"
        - 有 key → "LIVE"(契约6:has_key=False 绝不出现 LIVE)
        - trust_level 已设置 → "L{n} · {label}"(最后,README §188 顺序:模式徽标+LIVE+Trust)
          L4 时前缀 '⏻ ':README §152 升 L4 顶栏亮红灯
        """
        out: list[str] = []
        if self._plan_mode:
            out.append(t("widget.badge_plan"))
        if self._yolo:
            out.append(t("widget.badge_yolo"))
        if not self._has_key:
            out.append(t("widget.badge_no_key"))
        else:
            out.append(t("widget.badge_live"))
        # Trust 徽标排最后(README §188)
        if self._trust_level is not None:
            prefix = "⏻ " if self._trust_level == 4 else ""
            label_part = f" · {self._trust_label}" if self._trust_label else ""
            out.append(f"{prefix}L{self._trust_level}{label_part}")
        return out

    @property
    def render_text(self) -> str:
        """纯文本快照(测试断言用)。"""
        return str(self.render())

    def render(self) -> Text:
        # 左侧:状态眼 + 品牌名 + 模型
        glyph = _PHASE_GLYPH.get(self._phase, "◌")
        # blocked 相(◓)染 $unverif 橙;idle 染 $eye-soft 暗金;其余染 $eye 亮金
        if self._phase == "blocked":
            eye_color = _UNVERIF
        elif self._phase == "idle":
            eye_color = _EYE_SOFT
        else:
            eye_color = _EYE
        left = Text()
        left.append(f"{glyph} ", style=f"bold {eye_color}")
        left.append(f"Argos v{self._version}", style=f"bold {_INK_BRIGHT}")
        left.append(f" · {self._model}", style=_INK_DIM)

        # 右侧:徽标区(v3 颜色规则)
        # Trust 徽标动态颜色:L4 → $fail 红;L0–L3 → $eye-soft 暗金(README §152/§188)
        right = Text()
        for i, b in enumerate(self.badges()):
            if i:
                right.append("  ")
            style = self._badge_style(b)
            right.append(b, style=style)

        width = self.size.width or 0
        pad = max(1, width - left.cell_len - right.cell_len - 2)
        return Text.assemble(left, " " * pad, right) if right.cell_len else left

    def _badge_style(self, badge: str) -> str:
        """返回徽标对应的 Rich style 字符串(单一真源,渲染与测试共用)。

        固定徽标用字典查表;Trust 徽标(含 'L' 前缀或 '⏻' 前缀)按 level 动态着色。
        """
        _FIXED: dict[str, str] = {
            t("widget.badge_plan"): _PLAN,
            t("widget.badge_yolo"): _FAIL,
            t("widget.badge_no_key"): _UNVERIF,
            t("widget.badge_live"): _PASS,
        }
        if badge in _FIXED:
            return _FIXED[badge]
        # Trust 徽标:L4(或含 '⏻')→ $fail 红;其余 → $eye-soft 暗金
        if self._trust_level == 4:
            return _FAIL
        return _EYE_SOFT
