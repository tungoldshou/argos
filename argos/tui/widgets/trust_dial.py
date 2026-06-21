# argos/tui/widgets/trust_dial.py
"""TrustDial:信任拨盘状态展示组件(TUI v3 spec §10,黑曜石之眼)。

职责 —— BLOCK A(只读状态表)：
  以 5 行表格渲染 L0–L4 信任拨盘的当前状态，配合铁律行。
  当前档行前缀 ▸($eye gold),非当前行两空格前缀($ink-faint)。
  L4 行 hint 列显示 ⏻ 红灯($fail)。
  铁律行三处受保护类别($fail)。

非交互展示组件:can_focus=False,不处理按键。

BLOCK B(升档决策卡) —— 已在 app.py _trust_cmd 通过 InlineChoice 实现,不在此组件中。

颜色 discipline:
  DEFAULT_CSS 一律用 $token 名(Textual 能解析)。
  Rich Text 颜色用模块级 hex 常量(Rich 不解析 $token)。
  hex 常量与 theme.py token 值对齐 —— 修改 theme.py 时必须同步此文件。
"""
from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

from argos.i18n import t as t_
from argos.permissions.trust_dial import TrustLevel

# ─────────────────────────────────────────────────────────────────────────────
# Rich Text hex 颜色常量(与 theme.py token 一一对应)
# ─────────────────────────────────────────────────────────────────────────────
# DEFAULT_CSS 用 $token 名;Rich Text 渲染用以下 hex 常量(Rich 不解析 $token)

_COL_EYE        = "#D9A85C"  # $eye: 金系主强调 — 当前行 ▸ cursor
_COL_INK_BRIGHT = "#ECEEF5"  # $ink-bright: bold 强调 — 当前行标签
_COL_INK        = "#C8CCDA"  # $ink: 正文 — 当前行 hint
_COL_INK_DIM    = "#7E869C"  # $ink-dim: 次要 — 铁律行基底 / 非选中 hint
_COL_INK_FAINT  = "#525A73"  # $ink-faint: 极淡 — 非当前行文字 / footer
_COL_FAIL       = "#F7768E"  # $fail: 红色 — ⏻ 红灯 + 铁律三处类别
_COL_UNVERIF    = "#FF9E64"  # $unverif: 橙色 — (保留,用于升档警示卡)

# ─────────────────────────────────────────────────────────────────────────────
# 拨盘行静态数据(五行)
# ─────────────────────────────────────────────────────────────────────────────

# 每行: (TrustLevel, label_key, hint_key)
# 规格来源: spec §10 line 283-287
_DIAL_ROWS: list[tuple[TrustLevel, str, str]] = [
    (TrustLevel.L0_EVERY_STEP,        "trust.l0_label", "trust.l0_hint"),
    (TrustLevel.L1_DANGEROUS_ONLY,    "trust.l1_label", "trust.l1_hint"),
    (TrustLevel.L2_IRREVERSIBLE_ONLY, "trust.l2_label", "trust.l2_hint"),
    (TrustLevel.L3_SESSION_TRUSTED,   "trust.l3_label", "trust.l3_hint"),
    # L4: hint 列包含 ⏻ 红灯部分 + 余下部分($ink-faint)
    (TrustLevel.L4_AUTONOMOUS,        "trust.l4_label", "trust.l4_hint_red"),
]

# L4 hint: 红灯部分 key + 余下部分 key
_L4_HINT_RED_KEY  = "trust.l4_hint_red"
_L4_HINT_REST_KEY = "trust.l4_hint_rest"


class TrustDial(Static):
    """信任拨盘状态展示 Static(BLOCK A,只读)。

    构造参数:
      current (TrustLevel): 当前信任档位(由 app.py _trust_cmd 解析并传入)。

    渲染结构:
      第 1 行: 标题  "信任拨盘 · 当前 Lx"
      第 2–6 行: 五行拨盘(▸ 当前 / 两空格 非当前)
      第 7 行: 铁律行  "HARD RULES 永不降级:危险 shell · 系统路径 · secret 检测"
      (可选 footer): 淡色 provenance 注记
    """

    DEFAULT_CSS = """
    TrustDial {
        height: auto;
        margin: 0 0 1 0;
        padding: 0 2;
        background: $stream;
    }
    """

    # 展示组件:不抢焦点,不处理按键
    can_focus = False

    def __init__(self, *, current: TrustLevel, **kwargs) -> None:
        # markup=False: label_human / hint 可能含 [...](如括号),不得解析为 Rich markup
        super().__init__("", markup=False, **kwargs)
        self._current = current

    # ─────────────────────────────────────────────────────────────────────────
    # 渲染
    # ─────────────────────────────────────────────────────────────────────────

    def _compose_text(self) -> Text:
        """构建完整的 Rich Text 渲染块。

        各行颜色规则(spec §10):
          - 当前行: ▸($eye bold) + Lx($ink-bright bold) + label($ink-bright bold)
                  + hint($ink)
          - 非当前行: '  '(两空格) + Lx + label($ink-faint) + hint($ink-faint)
          - 铁律行: "HARD RULES 永不降级:"($ink-dim)
                   + "危险 shell"($fail) + " · "($ink-dim)
                   + "系统路径"($fail) + " · "($ink-dim)
                   + "secret 检测"($fail)
        """
        t = Text()

        # ── 第 1 行:标题 ──────────────────────────────────────────────────
        # 3-mode 名为主(Cautious/Trusted/Autonomous),括号内保留 Lx 短名(诚实可追溯)。
        short = self._current.name.split("_")[0]  # "L0" / "L1" / ...
        t.append(t_("trust.title_prefix"), style=_COL_INK)
        t.append(self._current.mode_name, style=f"bold {_COL_INK_BRIGHT}")
        t.append(t_("trust.title_level_suffix", short=short), style=_COL_INK)
        t.append("\n")

        # ── 第 2–6 行:五行拨盘 ────────────────────────────────────────────
        for lvl, label_key, hint_key in _DIAL_ROWS:
            is_current = (lvl == self._current)
            label = t_(label_key)

            if is_current:
                # 当前行: ▸ + Lx + space + label + gap + hint
                t.append("▸ ", style=f"bold {_COL_EYE}")
                level_short = lvl.name.split("_")[0]
                t.append(level_short + " ", style=f"bold {_COL_INK_BRIGHT}")
                t.append(label, style=f"bold {_COL_INK_BRIGHT}")
                # hint 列(右对齐用空格,简化为固定两空格间隔)
                t.append("  ")
                # L4 hint: ⏻ 红灯 用 $fail,余下 $ink
                if lvl is TrustLevel.L4_AUTONOMOUS:
                    t.append(t_(_L4_HINT_RED_KEY), style=_COL_FAIL)
                    t.append(t_(_L4_HINT_REST_KEY), style=_COL_INK)
                else:
                    t.append(t_(hint_key), style=_COL_INK)
            else:
                # 非当前行: 两空格 + Lx + space + label + gap + hint(全部 $ink-faint)
                t.append("  ", style=_COL_INK_FAINT)
                level_short = lvl.name.split("_")[0]
                t.append(level_short + " ", style=_COL_INK_FAINT)
                t.append(label, style=_COL_INK_FAINT)
                t.append("  ", style=_COL_INK_FAINT)
                # L4 hint 非当前时:⏻ 也需 $fail 颜色(per spec,⏻红灯常量语义)
                if lvl is TrustLevel.L4_AUTONOMOUS:
                    t.append(t_(_L4_HINT_RED_KEY), style=_COL_FAIL)
                    t.append(t_(_L4_HINT_REST_KEY), style=_COL_INK_FAINT)
                else:
                    t.append(t_(hint_key), style=_COL_INK_FAINT)

            t.append("\n")

        # ── 铁律行:HARD RULES 永不降级(任何档位下均渲染) ──────────────────
        # 规格 §10 line 293: "三处 $fail"
        t.append(t_("trust.hard_rules_prefix"), style=_COL_INK_DIM)
        t.append(t_("trust.hard_rules_shell"), style=_COL_FAIL)
        t.append(t_("trust.hard_rules_sep"), style=_COL_INK_DIM)
        t.append(t_("trust.hard_rules_path"), style=_COL_FAIL)
        t.append(t_("trust.hard_rules_sep"), style=_COL_INK_DIM)
        t.append(t_("trust.hard_rules_secret"), style=_COL_FAIL)
        t.append("\n")

        # ── Footer(可选 provenance,$ink-faint)──────────────────────────────
        t.append(t_("trust.footer_provenance"), style=_COL_INK_FAINT)
        t.append("  ", style=_COL_INK_FAINT)
        t.append(t_("trust.footer_module"), style=_COL_INK_FAINT)

        return t

    def render(self) -> Text:  # type: ignore[override]
        """Textual Static.render() 入口:返回 Rich Text。"""
        return self._compose_text()
