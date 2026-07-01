"""StatusBar：always-on 状态条（TUI v3「黑曜石之眼」spec §4.9 + §8.4）。

渲染格式（act 阶段示例）：
    ◉ act · 动作3 · ↑12.4k ↓3.1k · $0.013 · 4.2s · ctx 34%    Esc 打断 · \\↵ 换行 · ^C 退出

渲染优先级铁律（§8.4 裁决）：
    用户阻塞（审批挂起，◓） > 告警锁色（-alert，_terminal_glow 联动） > 阶段眼

新增公开方法：
    set_blocked(active: bool)  — 审批挂起态，_handle_approval 调用
    set_alert(active: bool)    — 告警锁色，与 _terminal_glow 同源

字形铁律（§3 词典）：
    ◔plan / ◉act / ❂verify / ◕report / ◌idle / ◓blocked
    "动作N" 文字计数（⚙ 处决）

诚实：数字全来自 phase_change/cost_update 事件；无事件时显零态，不预填假数。
daemon run badges（⏵/⏸/⏹）只在 daemon 模式（set_run_summary 喂过数据）渲染——
非 daemon 不渲染 ⏵0/⏸0/⏹0 噪声。键提示右对齐（替代 stock Footer）。
"""
from __future__ import annotations

from rich.text import Text
from textual.reactive import reactive
from textual.widgets import Static

from argos.core.types import Phase
from argos.i18n import t as _t

# §3 字形词典：阶段眼映射
_PHASE_GLYPH: dict[str, str] = {
    "plan":   "◔",
    "act":    "◉",
    "verify": "❂",
    "report": "◕",
    "idle":   "◌",
}
_GLYPH_BLOCKED = "◓"

# Rich style：直接用 hex（theme token 无法在 Rich Text 层引用，仅 CSS 层可用）
# 值与 theme.py 对应 token 保持一致
_STYLE_EYE      = "#D9A85C"   # $eye：当前阶段
_STYLE_BLOCKED  = "#FF9E64"   # $unverif：用户阻塞
_STYLE_INK_DIM  = "#7E869C"   # $ink-dim：数据段
_STYLE_INK_FAINT = "#525A73"  # $ink-faint：键提示

def _hints() -> str:
    return _t("tui.statusbar.hints")


class StatusBar(Static):
    """状态眼条：最左永远一只眼，优先级状态机控制眼形与整条色调。"""

    DEFAULT_CSS = """
    StatusBar { dock: bottom; height: 1; background: $abyss; color: $ink-faint; padding: 0 2; }
    StatusBar.-plan-mode { color: $plan; }
    StatusBar.-ctx-warn { color: $unverif; text-style: bold; }
    StatusBar.-ctx-crit { color: $fail; text-style: bold; }
    StatusBar.-blocked { color: $unverif; }
    StatusBar.-alert { color: $fail; text-style: bold; }
    StatusBar.-alert-warn { color: $unverif; text-style: bold; }
    """

    # ── reactives ────────────────────────────────────────────────────────────
    phase:      reactive[str]        = reactive("idle")
    actions:    reactive[int]        = reactive(0)
    max_steps:  reactive[int | None] = reactive(None)
    tokens_in:  reactive[int]        = reactive(0)
    tokens_out: reactive[int]        = reactive(0)
    cost_usd:   reactive[float | None] = reactive(0.0)
    elapsed_s:  reactive[float]      = reactive(0.0)
    plan_mode:  reactive[bool]       = reactive(False)
    ctx_pct:    reactive[float]      = reactive(0.0)

    def __init__(self, **kwargs) -> None:
        # render() 自绘（Rich Text 分段着色 + 右对齐键提示），不走 markup 解析（防崩）。
        super().__init__("", markup=False, **kwargs)
        self._blocked: bool = False   # 审批挂起态
        self._alert: bool   = False   # 告警锁色（_terminal_glow 联动）
        self._alert_kind: str = "fail"  # 告警语义:fail=红(failed/error) / warn=橙(unverifiable/escalation)
        self._run_summary: list[tuple[str, str]] = []
        # v6 P3b §2：内核模式标注（诚实：绝不假装）。
        # "argosd" = 走 daemon 协议；"inline" = 单进程直跑；"" = 未初始化（DEMO 等）。
        self._kernel_mode: str = ""

    # ── 优先级状态机（§8.4）─────────────────────────────────────────────────
    def _phase_eye(self) -> str:
        """当前阶段对应眼字形（§3 词典）。"""
        return _PHASE_GLYPH.get(self.phase, "◌")

    def _resolve_render_state(self) -> tuple[str, str]:
        """返回 (左眼 glyph, css_class_suffix)。

        优先级：用户阻塞 > 告警锁色 > 阶段。
        css_class_suffix 为空串表示使用 ctx 压力类（见 _ctx_class）。
        """
        if self._blocked:
            # 用户阻塞——永远赢，即便 phase==verify
            return _GLYPH_BLOCKED, "-blocked"
        if self._alert:
            # 告警锁色：眼仍随阶段，整条锁语义色（陷阱2：阶段色不覆盖告警）
            # fail=红(failed/error);warn=橙(unverifiable/escalation)——三态语义纯度
            return self._phase_eye(), ("-alert-warn" if self._alert_kind == "warn" else "-alert")
        # 其次阶段眼 + ctx 压力
        return self._phase_eye(), ""

    def _ctx_class(self) -> str:
        """ctx 压力对应 CSS 类（≥95% crit；≥80% warn；其余空）。"""
        if self.ctx_pct >= 0.95:
            return "-ctx-crit"
        if self.ctx_pct >= 0.80:
            return "-ctx-warn"
        return ""

    # ── 公开 API（新增，§4.9 c）─────────────────────────────────────────────
    def set_blocked(self, active: bool) -> None:
        """设置审批挂起态（用户阻塞）。

        _handle_approval mount 审批卡时置 True，决策后置 False。
        blocked 时左眼强制显示 ◓，优先级最高。
        """
        self._blocked = bool(active)
        self._refresh()

    def set_alert(self, active: bool, kind: str = "fail") -> None:
        """设置告警锁色态（与 _terminal_glow 同源）。

        failed/unverifiable/escalation/error 时置 True；
        新 run 或 phase=plan 时清（由调用方负责）。
        kind="fail" 整条锁红（failed/error）；kind="warn" 整条锁橙
        （unverifiable/escalation——「真相不确定」的橙语义不被红泛化）。眼仍随阶段。
        """
        self._alert = bool(active)
        self._alert_kind = "warn" if kind == "warn" else "fail"
        self._refresh()

    # ── 不变 API（契约保持）──────────────────────────────────────────────────
    @property
    def render_text(self) -> str:
        """左侧数据段纯文本（/status 回显与测试断言的单一真源）。"""
        eye, _ = self._resolve_render_state()

        # §4.9 a："动作N"文字格式（⚙ 处决）。N/M 已知预算时显示,否则只 N(不出 "N/None")。
        # 去重(2026-07-01):token 流 / 耗时 / ctx% / run 徽标都由右侧 ActivityPanel 独占,底栏只留
        # "一眼态"——阶段 + 步数(+ 审批阻塞 / plan / 内核标注)。花费($)已整体移除(不再配价格)。
        _action_str = (
            _t("tui.statusbar.action", n=self.actions) + f"/{self.max_steps}"
            if self.max_steps is not None
            else _t("tui.statusbar.action", n=self.actions)
        )
        parts = [
            f"{eye} {self.phase}",
            _action_str,
        ]
        # blocked 模式插入提示段
        if self._blocked:
            parts.insert(1, _t("tui.statusbar.blocked_label"))
        if self.plan_mode:
            parts.append(_t("tui.statusbar.plan_mode"))
        # v6 P3b §2 诚实标注：argosd=走协议;inline=单进程 fallback;""=不显示
        if self._kernel_mode:
            parts.append(self._kernel_mode)
        return " · ".join(parts)

    def set_run_summary(self, runs: list[tuple[str, str]]) -> None:
        """runs: [(run_id, state), ...]；空列表 = 非 daemon，徽标整段消失（去噪）。"""
        self._run_summary = list(runs)
        self._refresh()

    def render_count_badges(self, runs: list[tuple[str, str]]) -> str:
        """run 列表 → 紧凑 count badges：⏵1 / ⏸0 / ⏹3；无 run（非 daemon）→ 空串。

        active=running；paused=paused；history=suspended+completed+failed+cancelled。
        """
        if not runs:
            return ""
        active  = sum(1 for _, s in runs if s == "running")
        paused  = sum(1 for _, s in runs if s == "paused")
        history = sum(
            1 for _, s in runs
            if s in ("suspended", "completed", "failed", "cancelled")
        )
        return f"⏵{active} / ⏸{paused} / ⏹{history}"

    def set_phase(self, phase: Phase, actions: int, max_steps: int | None = None) -> None:
        """更新阶段与动作计数。max_steps=None 时保留现有值（兼容旧调用）。"""
        self.phase   = phase
        self.actions = actions
        if max_steps is not None:
            self.max_steps = max_steps

    def mark_run_end(self) -> None:
        """run 收尾:phase 复位 idle(与 ActivityPanel.on_run_end 对称)。
        否则 phase 粘在最后的 'report' 不动,而右栏头已回 idle → 两处自相矛盾
        (2026-06-22 真机:run 结束后底栏仍显 'report · action5')。告警色(_alert_kind)不在此清,
        由下一轮 plan 解锁——失败裁决的红/橙不被收尾抹掉(陷阱2)。"""
        self.phase     = "idle"
        self.actions   = 0
        self.max_steps = None

    def set_cost(
        self,
        *,
        tokens_in: int,
        tokens_out: int,
        cost_usd: float | None,
        elapsed_s: float,
    ) -> None:
        """更新 token/成本/耗时。"""
        self.tokens_in  = tokens_in
        self.tokens_out = tokens_out
        self.cost_usd   = cost_usd
        self.elapsed_s  = elapsed_s

    def set_plan_mode(self, active: bool) -> None:
        """host 切 plan mode 时调：加 [plan mode] 段 + 切色。"""
        self.plan_mode = bool(active)

    def set_kernel_mode(self, mode: str) -> None:
        """v6 P3b §2：诚实标注内核模式。

        mode="argosd"  → 走 daemon 协议（argosd 进程）
        mode="inline"  → 单进程直跑（fallback）
        mode=""        → 未知 / DEMO（不显示段）
        诚实铁律：只传真实状态，绝不把 inline 标注为 argosd。
        """
        self._kernel_mode = mode
        self._refresh()

    def update_ctx_pressure(self, pct: float) -> None:
        """Context 可视化：≥80% 整条切 -ctx-warn，≥95% 切 -ctx-crit；pct=0 → 移除。"""
        self.ctx_pct = max(0.0, min(1.0, float(pct or 0.0)))

    # ── 渲染（Rich Text 自绘）────────────────────────────────────────────────
    def render(self) -> Text:
        """渲染一行：左眼着色 + 数据段 + 右对齐键提示。"""
        left_str = self.render_text
        left = Text(left_str, no_wrap=True, overflow="ellipsis")

        # 左眼着色（仅首字形）
        eye, _ = self._resolve_render_state()
        eye_style = _STYLE_EYE
        if left.plain.startswith(eye):
            left.stylize(eye_style, 0, len(eye))

        width = self.size.width or 0
        hints = Text(_hints(), style=_STYLE_INK_FAINT)
        pad = width - left.cell_len - hints.cell_len - 2
        if pad >= 1:
            return Text.assemble(left, " " * pad, hints)
        # 窄屏（§7.2 <80 列）：键提示裁掉，只保留左侧眼+阶段+成本+ctx%
        return left

    def _refresh(self) -> None:
        """同步 CSS 类 + 触发重绘。"""
        self.refresh()
        # plan mode 类
        self.set_class(self.plan_mode, "-plan-mode")
        # 优先级状态机决定 CSS 类
        _, css_suffix = self._resolve_render_state()
        # 互斥：先清干净，再加对应类
        for cls in ("-blocked", "-alert", "-alert-warn", "-ctx-warn", "-ctx-crit"):
            self.remove_class(cls)
        if css_suffix:
            self.add_class(css_suffix)
        else:
            # 无 blocked/alert → ctx 压力类
            ctx_cls = self._ctx_class()
            if ctx_cls:
                self.add_class(ctx_cls)

    # ── reactive watchers──────────────────────────────────────────────────────
    def watch_phase(self, _: str) -> None:
        self._refresh()

    def watch_actions(self, _: int) -> None:
        self._refresh()

    def watch_tokens_in(self, _: int) -> None:
        self._refresh()

    def watch_tokens_out(self, _: int) -> None:
        self._refresh()

    def watch_cost_usd(self, _: float | None) -> None:
        self._refresh()

    def watch_elapsed_s(self, _: float) -> None:
        self._refresh()

    def watch_plan_mode(self, _: bool) -> None:
        self._refresh()

    def watch_ctx_pct(self, _: float) -> None:
        self._refresh()
