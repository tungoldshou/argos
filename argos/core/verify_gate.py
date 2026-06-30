"""verify 硬门禁 —— Argos 的核心护城河(契约 §6;spec §3.3 L2/§12.5)。

三态 fail-closed(spec §12.5):
  · passed       退出码 0 且未篡改 → 真完成
  · failed       退出码非 0 → 没过,harness 据 attempts bounce 重试/升级
  · unverifiable 篡改受保护测试 / 超时 / 命令不在白名单 → 无法确认,绝不当 passed

分级延迟(spec §3.3 L2 决策 B1):inline_timeout(默认 60s 容忍真实 pytest 启动);
调用方可调小做超时降级——超过 → unverifiable,诚实标注"未完整验证"。

安全关键(沿用旧 _run_verify):验证在 VERIFY_DIR(agent 写不到)里跑——防 agent 篡改
评判它的测试作弊。WORKSPACE 进 PYTHONPATH,使验证脚本能 import agent 写的解。
篡改检测优先于退出码:detect_tampering() 非空 → 直接 unverifiable。

Verdict canonical 归属:argos.core.types(契约 §6.1)。
此处重新导出保持旧 import 路径:from argos.core.verify_gate import Verdict。
"""
from __future__ import annotations

from argos.i18n import t

import os
import shlex
import subprocess
from pathlib import Path

from argos import runtime
from argos.tools import ALLOWED_CMDS

# 唯一 Verdict 定义在 types.py(契约 §6.1)；re-export 保持旧 import 路径绿。
# TRIVIAL_VERIFY_BINS 同源 types.py：canonical 门与 loop/workflow 共用同一份反琐碎集。
from argos.core.types import TRIVIAL_VERIFY_BINS, Verdict  # noqa: F401


# self-test feature flag(任务:opt-in 默认关闭,避免 verifier 行为隐性变化)。
# 设 env var `ARGOS_SELF_TEST=1` 开启;不设 / 设 0 = 关闭,verifier 行为 100% 与之前一致。
def _self_test_enabled() -> bool:
    return os.environ.get("ARGOS_SELF_TEST", "").strip().lower() in ("1", "true", "yes")


def is_trivial_verify(cmd: str) -> bool:
    """CONTRACT C §17:可导入的平凡验证命令谓词。

    True = cmd 的第一个 token 是 TRIVIAL_VERIFY_BINS 中永远通过、什么都不验证的命令
    (echo/true/false/:/ls/pwd/cat …),即此命令无法作为有效的验证门。

    用途:
      · Verifier.verify() 内部已经用此集拦截平凡命令 → unverifiable;
      · CLI exec 入口可在调用 Verifier 前 fail-fast 给出友好提示。
    示例::

        >>> is_trivial_verify("echo ok")
        True
        >>> is_trivial_verify("pytest -q tests/")
        False
    """
    cmd = (cmd or "").strip()
    if not cmd:
        return False
    try:
        bin_name = Path(shlex.split(cmd)[0]).name
    except (ValueError, IndexError):
        return False
    return bin_name in TRIVIAL_VERIFY_BINS


class Verifier:
    """称'完成'必过 verify_cmd；三态裁决；篡改优先；超时降级(契约 §6 Verifier)。

    canonical 签名(契约 §9 锁#1):
      verify(self, verify_cmd: str | None, *, attempts: int = 1) -> Verdict
    篡改检测与 VERIFY_DIR 隔离由本类内部经 runtime 解决，不接受外部 workspace/verify_dir/tampered。

    self-test 旁路(任务):verify_cmd is None + ARGOS_SELF_TEST=1 开启时,
    TestGenerator 会拿 goal 走 reviewer 角色的 LLM 提议一个候选测试;经
    canary(空 ws 上必非 0)+ 白名单 + detect_tampering 守卫后,真跑;真过了
    → Verdict.passed_self(detail, verify_cmd, attempts)(self_verified=True);
    任一守卫败 → Verdict.unverifiable。**绝不**在没有守卫的情况下把 None
    任务当 passed。
    """

    def __init__(
        self, *, max_rounds: int = 3, inline_timeout: float = 60.0,
        test_generator: "object | None" = None, goal: str | None = None,
    ) -> None:
        self.max_rounds = max_rounds
        # inline_timeout: 内联快路径上限。真实 pytest 启动 2-5s，默认给 60s 容忍；
        # 调用方可调小做"分级"(超过 → 降级 unverifiable，而非伪 passed)。
        self.inline_timeout = inline_timeout
        # self-test 注入点:默认 None(走默认 proposer,目前 None → 永不提议,保留接口);
        # 真模式可注入 reviewer LLM proposer。goal 是任务目标(给 proposer 看)。
        self._test_generator = test_generator
        self._goal = goal

    def set_goal(self, goal: str) -> None:
        """Update the current run goal (called by loop before each verify phase)."""
        self._goal = goal

    def verify(self, verify_cmd: str | None, *, attempts: int = 1) -> Verdict:
        """返回三态 Verdict(passed/failed/unverifiable)。

        优先级：篡改检测 > 命令执行 > 无命令。
        · 篡改非空 → unverifiable(spec §12.5 — 绝不蒙混)。
        · 无 verify_cmd → unverifiable(HONESTY CORRECTION:没有机检命令真的跑过，就绝不
          声称 passed —— 违反 HONESTY_SYSTEM 规则 1。无测任务能否完成由 Harness 据
          "verify_cmd is None" 判定为诚实非阻塞完成,不在此处当 passed 蒙混)。
          例外(任务):ARGOS_SELF_TEST 开启 + 注入了 test_generator → 走 self-test 旁路
          (详见 _try_self_test);任一守卫败 → 仍返 unverifiable,绝不假装通过。
        · verify_cmd 在白名单 → 跑命令;通过 → passed,失败 → failed,超时 → unverifiable。
        · verify_cmd 不在白名单 → failed(明确拒绝,不静默跳过)。
        """
        # 篡改优先(防贿赂测谎仪):先查受保护文件,非空 → 直接 unverifiable。
        tampered = runtime.detect_tampering()
        if tampered:
            return Verdict.unverifiable(
                detail=t("core2.verify_gate.tampered", files=', '.join(tampered)),
                tampered=tampered, attempts=attempts,
            )

        # 无 verify_cmd:无 self-test 旁路 → 诚实无测完成(CONTRACT A §5:no_check)。
        if not verify_cmd:
            # self-test 旁路:opt-in + 注入 generator → 试造测试。
            if _self_test_enabled() and self._test_generator is not None:
                verdict = self._try_self_test(attempts=attempts)
                if verdict is not None:
                    return verdict
            # 关闭 / 没 generator / 旁路失败 → 诚实无测标记(no_test=True)。
            # status 仍 'unverifiable',升级/诚实路径不变;UI 据 no_test 渲染中性色。
            return Verdict.no_check(
                detail=t("core2.verify_gate.no_cmd"), attempts=attempts,
            )

        # P0 防假绿(canonical 门):trivial 命令(echo/true/cat/ls/pwd...)什么都不验证。
        # echo/cat/ls/pwd 既在 ALLOWED_CMDS 又恒退出 0,过去经 _run_verify 直接当 passed = 假绿。
        # propose_verify 路径早设此门,但 config/setup/bridge/workflow 直接设 verify_cmd 的入口
        # 只经此 canonical Verifier → 必须统一拒。落 unverifiable(命令无效、非代码没过),不蒙混。
        try:
            _bin = Path(shlex.split(verify_cmd)[0]).name
        except (ValueError, IndexError):
            _bin = ""
        if _bin in TRIVIAL_VERIFY_BINS:
            return Verdict.unverifiable(
                detail=t("core2.verify_gate.trivial", cmd=verify_cmd),
                tampered=[], attempts=attempts,
            )

        ok, detail, timed_out = self._run_verify(verify_cmd)
        if timed_out:
            return Verdict.unverifiable(detail=detail, tampered=[], attempts=attempts)
        if ok:
            return Verdict.passed(detail=detail, verify_cmd=verify_cmd, attempts=attempts)
        return Verdict.failed(detail=detail, verify_cmd=verify_cmd, attempts=attempts)

    def _try_self_test(self, *, attempts: int) -> Verdict | None:
        """self-test 旁路:goal + workspace 经 TestGenerator 提议 + canary 守卫。

        返回:Verdict(若整套走通且 self-test 真跑了且通过了)或 None(caller 回退 unverifiable)。

        铁律(模块级 + 调用方层):
          · 任一守卫(propose / 白名单 / canary / 还原 / 真跑)失败 → 返 None,绝不假 passed。
          · 真跑过 → Verdict.passed_self(self_verified=True)。调用方(UI/report/统计)必须
            按 self_verified 区分"强 / 弱",不让 self_verified=True 冒充用户级 passed。
        """
        from argos.verify.self_test import TestGenerator
        ctx = runtime.current()
        workspace = ctx.workspace
        if workspace is None:
            return None
        gen: TestGenerator = self._test_generator  # type: ignore[assignment]
        proposal = gen.propose_and_validate(
            goal=self._goal or "(no goal provided)", workspace=workspace,
        )
        if proposal is None:
            return None
        # 真跑生成出的 verify_cmd(走原有 _run_verify,白名单 + verify_dir 隔离全保留)
        ok, detail, timed_out = self._run_verify(proposal.cmd)
        if timed_out:
            return Verdict.unverifiable(
                detail=f"[self_verified timeout] {detail}", tampered=[], attempts=attempts,
            )
        if ok:
            return Verdict.passed_self(
                detail=t("core2.verify_gate.self_verified_weak", detail=detail),
                verify_cmd=proposal.cmd, attempts=attempts,
            )
        return Verdict.failed(
            detail=t("core2.verify_gate.self_verified_failed", detail=detail),
            verify_cmd=proposal.cmd, attempts=attempts,
        )

    def _run_verify(self, cmd: str) -> tuple[bool, str, bool]:
        """跑验证命令，返回 (是否通过, 细节, 是否超时)。退出码是 ground truth。"""
        try:
            parts = shlex.split(cmd)
        except ValueError as e:
            return False, t("core2.verify_gate.parse_failed", error=e), False

        if not parts or Path(parts[0]).name not in ALLOWED_CMDS:
            return False, t("core2.verify_gate.not_allowlisted", cmd=cmd), False

        ctx = runtime.current()
        verify_dir, workspace = ctx.verify_dir, ctx.workspace
        verify_dir.mkdir(parents=True, exist_ok=True)
        workspace.mkdir(parents=True, exist_ok=True)

        env = dict(os.environ)
        env["PYTHONPATH"] = str(workspace) + os.pathsep + env.get("PYTHONPATH", "")
        # 护城河可靠性:禁写 .pyc。agent 改源后重跑 verify 必须验证【当前源码】——
        # 同尺寸改动(如 'a - b'→'a + b')若赶在同一秒(mtime 秒级分辨率),陈旧 .pyc 会被
        # 复用导致 verify 对【旧字节码】下判,模型修好了却仍报 failed → 假 bounce/假升级。
        # 禁写字节码 → 每个 verify 子进程都从源码现导,verdict 永远反映当前代码。
        env["PYTHONDONTWRITEBYTECODE"] = "1"

        try:
            r = subprocess.run(
                parts, cwd=verify_dir, capture_output=True, text=True,
                timeout=self.inline_timeout, env=env,
            )
        except subprocess.TimeoutExpired:
            return False, t("core2.verify_gate.timeout", cmd=cmd, timeout=self.inline_timeout), True
        except Exception as e:  # noqa: BLE001
            return False, t("core2.verify_gate.exec_failed", error=e), False

        out = (r.stdout or "")[-1500:]
        err = (r.stderr or "")[-1500:]
        detail = f"[exit_code={r.returncode}]\n{out}\n{err}".strip()
        return r.returncode == 0, detail, False
