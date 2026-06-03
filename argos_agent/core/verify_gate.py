"""Verifier 占位(契约 §6.1 + §9 锁#1) —— loop 称"完成"时调。

【契约 §9 锁#1 canonical 签名】:
  verify(self, verify_cmd: str | None, *, attempts: int = 1) -> Verdict
篡改检测与 VERIFY_DIR 隔离由 Verifier 内部经 runtime 解决,不接受 workspace/verify_dir/tampered。
Phase 4 扩分级延迟(lint+受影响单测内联<1s,integration 异步降级)落地;本阶段最小占位版:
  跑 verify_cmd → passed/failed;先查 runtime.detect_tampering() 非空 → unverifiable。
Phase 4 落地后:本占位被 Phase 4 的真版替换(同名 Verifier.verify 签名,同 Verdict 返回值)。
"""
from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from argos_agent.core.types import VerdictStatus


@dataclass(frozen=True, slots=True)
class Verdict:
    """三态验证结果(契约 §6.1)。Phase 4 把这个搬进 types.py 并加静态工厂。
    Phase 3 先在这里定义占位版本;形状与 Phase 4 的 canonical 一致,改 import 行即可。"""
    status: VerdictStatus            # "passed" | "failed" | "unverifiable"
    detail: str                      # verify 命令输出(含 [exit_code=N])
    verify_cmd: str | None
    attempts: int
    tampered: list[str] = field(default_factory=list)

    @staticmethod
    def passed(detail: str, verify_cmd: str | None, attempts: int) -> "Verdict":
        return Verdict(status="passed", detail=detail, verify_cmd=verify_cmd, attempts=attempts)

    @staticmethod
    def failed(detail: str, verify_cmd: str | None, attempts: int) -> "Verdict":
        return Verdict(status="failed", detail=detail, verify_cmd=verify_cmd, attempts=attempts)

    @staticmethod
    def unverifiable(detail: str, tampered: list[str], attempts: int) -> "Verdict":
        return Verdict(status="unverifiable", detail=detail, verify_cmd=None,
                       attempts=attempts, tampered=tampered)


def _workspace() -> Path:
    return Path(os.environ.get("ARGOS_WORKSPACE", str(Path.home() / ".argos" / "workspace")))


def _verify_dir() -> Path:
    return Path(os.environ.get("ARGOS_VERIFY_DIR", str(Path.home() / ".argos" / "verify")))


def _run_verify(cmd: str) -> tuple[int, str]:
    """跑验证命令,返回 (退出码, 细节[exit_code=N])。在 verify_dir(agent 写不到)里跑。"""
    try:
        parts = shlex.split(cmd)
    except ValueError as e:
        return -1, f"验证命令解析失败:{e}"
    vdir = _verify_dir()
    ws = _workspace()
    vdir.mkdir(parents=True, exist_ok=True)
    ws.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ws) + os.pathsep + env.get("PYTHONPATH", "")
    try:
        r = subprocess.run(parts, cwd=vdir, capture_output=True, text=True, timeout=60, env=env)
    except Exception as e:  # noqa: BLE001
        return -1, f"验证执行失败:{e}"
    detail = f"[exit_code={r.returncode}]\n{(r.stdout or '')[-1500:]}\n{(r.stderr or '')[-1500:]}".strip()
    return r.returncode, detail


class Verifier:
    """test-oracle 硬门禁占位(契约 §6.1 + §9 锁#1)。

    Phase 4 扩分级延迟 + harness 集成;本阶段最小占位:跑 verify_cmd → 三态 Verdict。
    canonical 签名(§9 锁#1):verify(verify_cmd, *, attempts=1) -> Verdict。
    篡改检测与 VERIFY_DIR 隔离由本类内部处理,不接受外部参数(loop 不传 workspace/tampered)。
    """

    def __init__(self, *, max_rounds: int = 3) -> None:
        self.max_rounds = max_rounds

    def verify(self, verify_cmd: str | None, *, attempts: int = 1) -> Verdict:
        """返回三态 Verdict(passed/failed/unverifiable)。
        § 锁#1:篡改非空 → unverifiable,绝不蒙混(spec §12.5)。
        § 无 verify_cmd → unverifiable(诚实:无命令无法确认完成)。
        § verify_cmd 跑通 → passed;失败 → failed。
        """
        # 先查篡改(防贿赂测谎仪)。
        tampered: list[str] = []
        try:
            from argos_agent import runtime  # noqa: PLC0415
            tampered = runtime.detect_tampering()
        except Exception:  # noqa: BLE001
            tampered = []
        if tampered:
            return Verdict.unverifiable(
                detail=f"受保护文件被改:{', '.join(tampered)};通过不可信。",
                tampered=tampered, attempts=attempts,
            )
        if not verify_cmd:
            return Verdict.unverifiable(
                detail="无验证命令,无法确认完成。",
                tampered=[], attempts=attempts,
            )
        code, detail = _run_verify(verify_cmd)
        if code == 0:
            return Verdict.passed(detail=detail, verify_cmd=verify_cmd, attempts=attempts)
        return Verdict.failed(detail=detail, verify_cmd=verify_cmd, attempts=attempts)
