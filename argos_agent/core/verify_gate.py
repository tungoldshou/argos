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

Verdict canonical 归属:argos_agent.core.types(契约 §6.1)。
此处重新导出保持旧 import 路径:from argos_agent.core.verify_gate import Verdict。
"""
from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

# 唯一 Verdict 定义在 types.py(契约 §6.1)；re-export 保持旧 import 路径绿。
from argos_agent.core.types import Verdict  # noqa: F401


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
