"""`argos exec` —— 非交互 headless 执行(可脚本化 / CI)。对标 `claude -p` / `codex exec`。

单 prompt → 跑一轮四阶段(plan→act→verify→report)→ 打印结果 + 三态 verdict + 成本 → 按退出码裁决。
无 TUI,所以审批走非交互 gate:
  · 默认 ACCEPT_EDITS(等价 Trusted):自动批工作区内编辑 / 沙箱命令;牢笼墙处的越界 / 出网
    询问会被【自动 deny】(失败闭合,诚实 —— 报告里说明哪步因需审批被拒,绝不静默放过)。
  · `--auto`:用 AUTO 放手批准一切副作用(含出网 / 越界),给信任的 CI 环境。

退出码(对标 codex exec / claude -p 的 0=成功 / 非0=失败 约定):
  0  = verdict passed,或无声明验证而正常完成(诚实未验证 = 完成)。
  1  = verdict failed / unverifiable(声明了验证但没过 / 跑不出)、escalation(诚实喊停)、运行错误。
  2  = 参数错误(缺 prompt、无 key 无法装配)。
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid

from argos.i18n import t

# 延迟导入:config 模块在 headless 路径之外也能独立运行;延迟导入防循环。
# ConfigError 用于捕获无效 --model profile 时的精确错误,避免裸 traceback。
try:
    from argos.config import ConfigError as _ConfigError
except ImportError:  # 离线 / 打包裁剪场景
    _ConfigError = RuntimeError  # type: ignore[assignment,misc]


def add_subparser(sub) -> None:
    """注册 `argos exec` 子命令(由 __main__._build_parser 调用)。"""
    p = sub.add_parser(
        "exec",
        help=t("cli.exec.help"),
    )
    p.add_argument("prompt", nargs="?", help=t("cli.exec.prompt.help"))
    p.add_argument("--json", action="store_true", dest="as_json",
                   help=t("cli.exec.json.help"))
    p.add_argument("--auto", action="store_true",
                   help=t("cli.exec.auto.help"))
    p.add_argument("--verify", metavar="CMD", dest="verify_cmd",
                   help=t("cli.exec.verify.help"))
    p.add_argument("--project", metavar="PATH", help=t("cli.exec.project.help"))
    p.add_argument("--model", metavar="NAME", help=t("cli.exec.model.help"))
    p.add_argument("--quiet", action="store_true",
                   help=t("cli.exec.quiet.help"))
    p.set_defaults(func=run_exec)


def _read_prompt(args) -> str:
    prompt = getattr(args, "prompt", None)
    if not prompt or prompt == "-":
        try:
            prompt = sys.stdin.read().strip()
        except Exception:  # noqa: BLE001 — stdin 不可读时按空处理
            prompt = ""
    return (prompt or "").strip()


def run_exec(args) -> int:
    """执行一次 headless run,返回进程退出码。"""
    prompt = _read_prompt(args)
    if not prompt:
        print(t("cli.exec.missing_prompt"), file=sys.stderr)
        return 2

    # CONTRACT C (#17):在进入 build_components 之前,提前拒绝 trivial verify 命令,
    # 节省 4 轮模型往返 —— 用户会立刻得到明确的错误,而非等 N 分钟后看 unverifiable。
    _verify_cmd_arg = getattr(args, "verify_cmd", None)
    if _verify_cmd_arg:
        try:
            from argos.core.types import TRIVIAL_VERIFY_BINS
            import shlex as _shlex
            from pathlib import Path as _Path
            _bin = _Path(_shlex.split(_verify_cmd_arg)[0]).name
            if _bin in TRIVIAL_VERIFY_BINS:
                print(
                    t("cli.exec.trivial_verify", cmd=_verify_cmd_arg),
                    file=sys.stderr,
                )
                return 2
        except Exception:  # noqa: BLE001 — 预检失败不阻断执行;让 Verifier 自行处理
            pass

    from argos.app_factory import build_components, build_loop_factory
    # 惰性导入真正的 ConfigError:模块级 `from argos.config import ConfigError`(line 25)在
    # 全量套件的循环导入时序下可能拿到半初始化的 argos.config 而 fallback 成 RuntimeError,
    # 导致 `except (RuntimeError, _ConfigError)` 退化成接不住 ConfigError。run_exec 被调用时
    # 所有模块已完整加载,此处导入必拿到真类 → 无效 --model 稳定走 exit 2 而非裸 traceback。
    from argos.config import ConfigError
    from argos.approval import ApprovalLevel
    from argos.protocol.events import (
        CostUpdate, Error, Escalation, PhaseChange, TokenDelta, VerifyVerdict,
    )
    from argos.routing.effort import EffortLevel

    quiet = bool(getattr(args, "quiet", False))

    def _progress(msg: str) -> None:
        """向 stderr 打印进度行(--quiet 时静默)。stdout 始终保持干净。"""
        if not quiet:
            print(msg, file=sys.stderr, flush=True)

    effective_ws = getattr(args, "project", None) or os.getcwd()
    level = ApprovalLevel.AUTO if getattr(args, "auto", False) else ApprovalLevel.ACCEPT_EDITS

    # effort 从全局 --effort 透传(`argos --effort high exec ...`);缺省 medium。此前硬编 MEDIUM → 被忽略。
    try:
        _effort = EffortLevel(getattr(args, "effort", None) or EffortLevel.MEDIUM.value)
    except ValueError:
        _effort = EffortLevel.MEDIUM
    try:
        components = build_components(
            workspace=effective_ws,
            model_override=getattr(args, "model", None),
            approval_level=level,
            verify_cmd=_verify_cmd_arg,
            effort=_effort,
        )
    except (RuntimeError, ConfigError) as e:  # 无 key / 无效 profile → 诚实退出,不假装能跑
        print(t("cli.exec.no_key", err=e), file=sys.stderr)
        print(t("cli.exec.run_setup_hint"), file=sys.stderr)
        return 2

    # 非交互审批:非 --auto 时,任何"挂起询问"(牢笼墙 / 出网 / 越界)立即自动 deny —— 失败闭合,
    # 绝不挂死等一个不存在的 TUI 应答。--auto 时用 AUTO 档(request 直接 approve,不产生 ask)。
    if level is not ApprovalLevel.AUTO:
        gate = components.gate
        gate.set_ask_listener(lambda call_id, _payload: gate.respond(call_id, "deny"))

    loop = build_loop_factory(components)()
    session_id = "exec-" + uuid.uuid4().hex[:8]

    _progress(t("cli.exec.progress_start", prompt=prompt[:80] + ("…" if len(prompt) > 80 else "")))

    state: dict = {
        "phase_text": [], "all_text": [], "verdict": None, "cost": None,
        "escalation": None, "error": None,
        "step": 0,
    }

    # 阶段名称中→英映射(进度行给 CI 用户看,英文更通用)
    _PHASE_LABEL: dict[str, str] = {
        "plan": "plan", "act": "act", "verify": "verify", "report": "report",
    }

    async def _drive() -> None:
        async for ev in loop.run(prompt, session_id):
            if isinstance(ev, TokenDelta):
                state["phase_text"].append(ev.text)
                state["all_text"].append(ev.text)
            elif isinstance(ev, PhaseChange):
                state["phase_text"] = []   # 新阶段重置 → 末尾留下最后阶段(report)的文本作 result
                label = _PHASE_LABEL.get(getattr(ev, "phase", ""), getattr(ev, "phase", "?"))
                _progress(t("cli.exec.progress_phase", label=label))
            elif isinstance(ev, VerifyVerdict):
                state["verdict"] = ev.verdict.status
                # 诚实:区分用户级 passed 与"自验证(较弱)"passed —— 绝不让 self_verified 的弱通过
                # 在 CI/脚本表面冒充强验证(Verdict.is_user_verified 的同一防火墙语义)。
                state["self_verified"] = bool(getattr(ev.verdict, "self_verified", False))
                _progress(t("cli.exec.progress_verify", status=ev.verdict.status))
            elif isinstance(ev, CostUpdate):
                if ev.cost_usd is not None:
                    state["cost"] = ev.cost_usd   # CostUpdate 是会话累计 → 取最后一个
            elif isinstance(ev, Escalation):
                state["escalation"] = getattr(ev, "message", None) or getattr(ev, "reason", "") or "agent escalated"
                _progress(t("cli.exec.progress_escalation", msg=state["escalation"]))
            elif isinstance(ev, Error):
                state["error"] = ev.message
                _progress(t("cli.exec.progress_error", msg=state["error"]))

    try:
        asyncio.run(_drive())
    except Exception as e:  # noqa: BLE001 — 顶层兜底:任何未处理异常 → 诚实 error,不假装成功
        state["error"] = state["error"] or f"{type(e).__name__}: {e}"
    finally:
        try:
            components.close()
        except Exception:  # noqa: BLE001
            pass

    result_text = "".join(state["phase_text"]).strip() or "".join(state["all_text"]).strip()
    verdict = state["verdict"]
    self_verified = bool(state.get("self_verified", False))
    is_error = bool(state["error"]) or bool(state["escalation"]) or verdict in ("failed", "unverifiable")

    if state["error"]:
        code = 1
    elif verdict == "passed":
        code = 0   # self_verified 的弱通过也算通过(它真跑过),但下方 out_verdict 标注区分
    elif verdict in ("failed", "unverifiable"):
        code = 1
    elif state["escalation"]:
        code = 1
    else:
        code = 0   # 无声明验证而完成(NO_TEST)= 诚实完成

    # 对外暴露的 verdict 标签:self_verified 的 passed 标成 'passed_self',不冒充用户级强 passed。
    out_verdict = "passed_self" if (verdict == "passed" and self_verified) else verdict

    if getattr(args, "as_json", False):
        print(json.dumps({
            "result": result_text,
            "verdict": out_verdict,
            "self_verified": self_verified,
            "session_id": session_id,
            "cost_usd": state["cost"],
            "is_error": is_error,
            "escalation": state["escalation"],
            "error": state["error"],
        }, ensure_ascii=False))
    else:
        if result_text:
            print(result_text)
        if state["escalation"]:
            print(f"\n[escalation] {state['escalation']}", file=sys.stderr)
        if state["error"]:
            print(f"\n[error] {state['error']}", file=sys.stderr)
        _label = {
            "passed": t("cli.exec.verdict_passed"),
            "passed_self": t("cli.exec.verdict_passed_self"),
            "failed": t("cli.exec.verdict_failed"),
            "unverifiable": t("cli.exec.verdict_unverifiable"),
        }.get(out_verdict or "", t("cli.exec.verdict_no_test"))
        print(f"[verify] {_label}", file=sys.stderr)

    return code
