"""VerdictBadge:四态 verify 行(TUI v3 · 黑曜石之眼 spec §4.6,契约7/10)。

四态:
  passed(强)     ◉ $pass  bold         — 用户级 verify 通过
  failed         ◉ $fail  bold         — verify 失败,⤷ 重试注解行
  unverifiable   ◔ $unverif normal     — 三重冗余:◔ + 橙 + "无法验证"文字
  self-verified  ◍ $pass-weak italic   — 弱通过,⤷ 未晋级注解行(契约10)

CSS 类名:
  verdict-passed / verdict-failed / verdict-unverifiable 三名不变(契约7)
  verdict-self 新增(v3),绝不冒充 verdict-passed
"""
from __future__ import annotations

from textual.reactive import reactive
from textual.widgets import Static

from argos.core.types import Verdict, VerdictStatus


class VerdictBadge(Static):
    """show(verdict) 后渲染对应四态行,四态互不可错认(诚实硬约束)。"""

    DEFAULT_CSS = """
    VerdictBadge { padding: 0 2; margin: 0 0 1 0; height: auto; }
    VerdictBadge.verdict-passed       { color: $pass; text-style: bold; }
    VerdictBadge.verdict-failed       { color: $fail; text-style: bold; }
    VerdictBadge.verdict-unverifiable { color: $unverif; }
    VerdictBadge.verdict-self         { color: $pass-weak; text-style: italic; }
    """

    # reactive 仅做 CSS 类切换辅助,watch_status 保持契约语义
    status: reactive[VerdictStatus | None] = reactive(None)

    # 全部 CSS 类名常量(避免散落字符串)
    _ALL_CLASSES = ("verdict-passed", "verdict-failed", "verdict-unverifiable", "verdict-self")

    def __init__(self, **kwargs) -> None:
        # markup=False:verdict.detail 含 pytest/verify 真实输出(可含 `[...]`),
        # 不得被 Rich markup 解析,否则崩 TUI。
        super().__init__("", markup=False, **kwargs)
        self.render_text: str = ""

    def watch_status(self, value: VerdictStatus | None) -> None:
        """仅处理三态 CSS 类切换(契约7语义不变)。self-verified 由 show() 直接管理。"""
        for s in ("passed", "failed", "unverifiable"):
            self.set_class(value == s, f"verdict-{s}")

    def _clear_all_classes(self) -> None:
        """清空全部四个 verdict CSS 类,避免态切换残留。"""
        for cls in self._ALL_CLASSES:
            self.set_class(False, cls)

    def show(self, verdict: Verdict) -> None:
        """渲染四态 badge。

        四态映射(spec §4.6):
          status==passed and not self_verified → ◉ $pass bold
          status==passed and self_verified     → ◍ $pass-weak (verdict-self)
          status==failed                       → ◉ $fail bold + ⤷ 重试注解行
          status==unverifiable                 → ◔ $unverif + "无法验证"三重冗余
        """
        cmd = verdict.verify_cmd or "—"

        # 先落定 status reactive(契约:status 是外部读 API —— app.py wiring / 测试据它判态)。
        # watch_status 会按三态映射设 CSS 类;self-verified 分支随后用 _clear_all_classes + verdict-self
        # 覆盖(绝不挂 verdict-passed,契约10)。assignment 须先于手动 class 操作,顺序不可换。
        self.status = verdict.status

        if verdict.status == "passed" and verdict.self_verified:
            # ── self-verified 弱通过(第四态,契约10) ──────────────────
            # ◍ 格纹瞳,去饱和绿 $pass-weak,强制第二行 ⤷ 注解
            line1 = f"◍ 自验证通过(较弱) · {cmd} → {verdict.detail}"
            line2 = f"  ⤷ 非用户级 verify,未晋级技能"
            self.render_text = f"{line1}\n{line2}"
            self._clear_all_classes()
            self.set_class(True, "verdict-self")
            # 不触发 watch_status 走 verdict-passed,直接更新
            self.update(self.render_text)
            return

        if verdict.status == "passed":
            # ── passed 强通过 ──────────────────────────────────────
            # ◉ 注视实瞳,满绿 $pass bold,展示 verify_cmd + N 次尝试 + detail
            attempts_str = f"{verdict.attempts} 次尝试"
            self.render_text = (
                f"◉ verify passed · {cmd} · {attempts_str} → {verdict.detail}"
            )
            self._clear_all_classes()
            self.set_class(True, "verdict-passed")
            self.update(self.render_text)
            return

        if verdict.status == "failed":
            # ── failed ────────────────────────────────────────────
            # ◉ 注视实瞳,红 $fail bold,FAILED 大写,追加 ⤷ 重试注解
            line1 = f"◉ verify FAILED · {cmd} → {verdict.detail}"
            line2 = f"  ⤷ 重试 {verdict.attempts} 次后仍 failed"
            self.render_text = f"{line1}\n{line2}"
            self._clear_all_classes()
            self.set_class(True, "verdict-failed")
            self.update(self.render_text)
            return

        # ── unverifiable(含 tampered)────────────────────────────
        # ◔ 扫视半瞳,橙 $unverif,三重冗余:◔ + 橙 + "无法验证"文字
        if verdict.tampered:
            tampered_str = " ".join(verdict.tampered)
            self.render_text = (
                f"◔ 无法验证 · 受保护文件被改 {tampered_str} → {verdict.detail}"
            )
        else:
            self.render_text = f"◔ 无法验证 · {cmd} · {verdict.detail}"
        self._clear_all_classes()
        self.set_class(True, "verdict-unverifiable")
        self.update(self.render_text)
