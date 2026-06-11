"""TUI v3「黑曜石之眼」截图脚本。

用法:
    uv run python scripts/tui_v3_screenshots.py

产出目录:/tmp/argos-tui-v3-shots/
产出格式:SVG(必有) + PNG(qlmanage / rsvg-convert 均可用时自动转换)

截图列表:
  splash-idle.svg      — 启动后 idle 态(StartupSplash 终态,DEMO + 无 key 提示)
  run-act.svg          — run 进行中(用户目标 + assistant token + CodeAction/Result + DiffView,右栏 act 视图)
  approval.svg         — 行内审批卡挂起(InlineChoice mount,StatusBar ◓ blocked 态)
  verdict-passed.svg   — verify 通过绿色 VerdictBadge
  verdict-failed.svg   — verify 失败红色 VerdictBadge + StatusBar -alert 告警色

幂等:每次运行先清空输出目录再重建。
"""
from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

# ── 输出目录 ───────────────────────────────────────────────────────────────
OUT_DIR = Path("/tmp/argos-tui-v3-shots")


def _ensure_outdir() -> None:
    """清空并重建输出目录(幂等)。"""
    import shutil
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir(parents=True)


def _save_svg(name: str, svg: str) -> Path:
    p = OUT_DIR / name
    p.write_text(svg, encoding="utf-8")
    print(f"  ✓ SVG  → {p}")
    return p


def _try_png(svg_path: Path) -> Path | None:
    """尝试 qlmanage(macOS) 或 rsvg-convert 把 SVG 转 PNG。
    失败时只打印警告,不抛异常。"""
    png_path = svg_path.with_suffix(".png")

    # 方法 1: qlmanage (macOS Quick Look)
    try:
        result = subprocess.run(
            ["qlmanage", "-t", "-s", "1600", "-o", str(OUT_DIR), str(svg_path)],
            capture_output=True, timeout=15,
        )
        # qlmanage 输出到 <filename>.png(带后缀名)
        candidate = OUT_DIR / (svg_path.name + ".png")
        if candidate.exists():
            candidate.rename(png_path)
            print(f"  ✓ PNG  → {png_path}  (via qlmanage)")
            return png_path
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # 方法 2: rsvg-convert
    try:
        result = subprocess.run(
            ["rsvg-convert", "-w", "1600", str(svg_path), "-o", str(png_path)],
            capture_output=True, timeout=15,
        )
        if result.returncode == 0 and png_path.exists():
            print(f"  ✓ PNG  → {png_path}  (via rsvg-convert)")
            return png_path
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    print(f"  ⚠  PNG 转换失败({svg_path.name}):qlmanage 与 rsvg-convert 均不可用,仅保留 SVG")
    return None


# ── 截图协程 ───────────────────────────────────────────────────────────────

async def shot_splash_idle() -> None:
    """截图 1:splash-idle — 启动后 idle 态,StartupSplash 已完成呈现,DEMO 模式。"""
    from argos_agent.tui.app import ArgosApp
    from argos_agent.tui.fakeloop import FakeLoop

    app = ArgosApp(loop_factory=lambda: FakeLoop(), demo=True)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.pause()  # 等 on_mount 完成 + StartupSplash 渲染完
        svg = app.export_screenshot()
    path = _save_svg("splash-idle.svg", svg)
    _try_png(path)


async def shot_run_act() -> None:
    """截图 2:run-act — act 阶段进行中(右栏 act 视图):用户行 + assistant token + CodeAction/Result + FileDiff。

    实现说明:不走 start_run(它的 finally 块会调 on_run_end → set_view("idle"),截图时右栏已回 idle)。
    改为直接逐一 await _apply_event,模拟 run 进行中状态,截图时右栏保持 act 视图。
    这是 by-design 行为:spec §4.8 规定 run 收尾自动回 idle;截图必须在 run 结束前捕获 act 视图。
    """
    from argos_agent.tui.app import ArgosApp
    from argos_agent.tui.fakeloop import FakeLoop
    from argos_agent.tui.events import PhaseChange, TokenDelta, CodeAction, CodeResult, FileDiff, CostUpdate
    import time

    t0 = time.monotonic()
    # 直接投事件而不走 start_run,避免 finally on_run_end() 把视图重置回 idle
    act_events = [
        PhaseChange(phase="plan", actions=0),
        TokenDelta(text="分析目标:修复 off-by-one 错误…\n"),
        PhaseChange(phase="act", actions=1),
        TokenDelta(text="找到问题所在,准备修复。\n"),
        CodeAction(code="files = search_files('TODO')\nprint(files)", step=0),
        CodeResult(step=0, stdout="['src/parser.py', 'src/lexer.py']", value_repr="['src/parser.py', 'src/lexer.py']", exc="", ok=True),
        FileDiff(
            path="src/parser.py", added=3, removed=1,
            unified="--- a/src/parser.py\n+++ b/src/parser.py\n@@ -42,7 +42,9 @@\n-    return idx\n+    # fix: range 应是 len(tokens)-1\n+    return idx - 1\n",
        ),
        CostUpdate(tokens_in=8200, tokens_out=2100, cost_usd=0.0087, elapsed_s=time.monotonic() - t0),
    ]

    app = ArgosApp(loop_factory=lambda: FakeLoop(), demo=True)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        # 回显用户目标行(模拟 start_run 的 user_line 调用)
        from argos_agent.tui.widgets.transcript import Transcript
        await app.query_one("#transcript", Transcript).user_line("修复 src/parser.py 的 off-by-one 错误")
        # 直接投事件:run 中间态,on_run_end 不会被调用,右栏停留在 act 视图
        for ev in act_events:
            await app._apply_event(ev)
        await pilot.pause()
        svg = app.export_screenshot()
    path = _save_svg("run-act.svg", svg)
    _try_png(path)


async def shot_approval() -> None:
    """截图 3:approval — InlineChoice 行内审批卡挂起,StatusBar ◓ blocked 态。"""
    from argos_agent.tui.app import ArgosApp
    from argos_agent.tui.fakeloop import FakeLoop
    from argos_agent.tui.events import PhaseChange, TokenDelta, ApprovalRequest
    from argos_agent.tui.widgets.inline_choice import InlineChoice
    from argos_agent.tui.widgets.status_bar import StatusBar

    script = [
        PhaseChange(phase="act", actions=1),
        TokenDelta(text="准备推送到远端仓库…\n"),
        ApprovalRequest(
            call_id="ab12cd34ef56",
            action="run_command",
            args={"cmd": "git push origin main"},
            description="执行 git push origin main",
            risk="medium",
            trigger="soft rule: ask git push",
        ),
    ]

    app = ArgosApp(loop_factory=lambda: FakeLoop(script=script), demo=True)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        app.run_worker(app.start_run("把当前改动推送到 GitHub"), exclusive=False)
        # 等 InlineChoice mount(loop 投 ApprovalRequest 后挂起等用户决策)
        for _ in range(60):
            await pilot.pause()
            if list(app.query(InlineChoice)):
                break
        await pilot.pause()
        svg = app.export_screenshot()
    path = _save_svg("approval.svg", svg)
    _try_png(path)


async def shot_verdict_passed() -> None:
    """截图 4a:verdict-passed — verify 通过,VerdictBadge 绿色 passed 态。"""
    from argos_agent.tui.app import ArgosApp
    from argos_agent.tui.fakeloop import FakeLoop
    from argos_agent.core.types import Verdict
    from argos_agent.tui.events import PhaseChange, VerifyVerdict, TokenDelta, CostUpdate
    import time

    t0 = time.monotonic()
    script = [
        PhaseChange(phase="plan", actions=0),
        TokenDelta(text="规划完成,开始执行。\n"),
        PhaseChange(phase="act", actions=1),
        TokenDelta(text="已完成所有修改。\n"),
        CostUpdate(tokens_in=12400, tokens_out=3100, cost_usd=0.013, elapsed_s=time.monotonic() - t0),
        PhaseChange(phase="verify", actions=2),
        VerifyVerdict(verdict=Verdict.passed(detail="42 passed, 0 failed (1.2s)", verify_cmd="pytest tests/", attempts=1)),
        PhaseChange(phase="report", actions=2),
        TokenDelta(text="所有测试通过,任务完成。\n"),
    ]

    app = ArgosApp(loop_factory=lambda: FakeLoop(script=script), demo=True)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await app.start_run("修复并通过全套测试")
        await app.workers.wait_for_complete()
        await pilot.pause()
        svg = app.export_screenshot()
    path = _save_svg("verdict-passed.svg", svg)
    _try_png(path)


async def shot_verdict_failed() -> None:
    """截图 4b:verdict-failed — verify 失败,VerdictBadge 红色 failed 态 + StatusBar -alert。"""
    from argos_agent.tui.app import ArgosApp
    from argos_agent.tui.fakeloop import FakeLoop
    from argos_agent.core.types import Verdict
    from argos_agent.tui.events import PhaseChange, VerifyVerdict, Escalation, TokenDelta

    script = [
        PhaseChange(phase="act", actions=1),
        TokenDelta(text="尝试修复,但回归了其他用例…\n"),
        PhaseChange(phase="verify", actions=1),
        VerifyVerdict(verdict=Verdict.failed(detail="3 failed, 39 passed", verify_cmd="pytest tests/", attempts=3)),
        Escalation(reason="连续 3 轮 verify 未过,无法自行收敛", attempts=3, last_failure="3 failed"),
        TokenDelta(text="诚实上报:无法在允许步数内使测试全绿,请人工介入。\n"),
    ]

    app = ArgosApp(loop_factory=lambda: FakeLoop(script=script), demo=True)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await app.start_run("修复测试失败")
        await app.workers.wait_for_complete()
        await pilot.pause()
        svg = app.export_screenshot()
    path = _save_svg("verdict-failed.svg", svg)
    _try_png(path)


# ── 主入口 ─────────────────────────────────────────────────────────────────

async def main() -> None:
    """依次产出全部截图。每张独立 App 实例,互不污染。"""
    _ensure_outdir()
    print(f"\n产出目录:{OUT_DIR}\n")

    shots = [
        ("splash-idle  ", shot_splash_idle),
        ("run-act      ", shot_run_act),
        ("approval     ", shot_approval),
        ("verdict-passed", shot_verdict_passed),
        ("verdict-failed", shot_verdict_failed),
    ]

    for label, fn in shots:
        print(f"── {label} ──────────────────────────────────")
        try:
            await fn()
        except Exception as e:  # noqa: BLE001
            import traceback
            print(f"  ✗ 失败:{e}")
            traceback.print_exc()

    print(f"\n完成。产出文件:")
    for f in sorted(OUT_DIR.iterdir()):
        print(f"  {f}")


if __name__ == "__main__":
    asyncio.run(main())
