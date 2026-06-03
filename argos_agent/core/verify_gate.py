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

from argos_agent import runtime
from argos_agent.tools import ALLOWED_CMDS

# 唯一 Verdict 定义在 types.py(契约 §6.1)；re-export 保持旧 import 路径绿。
from argos_agent.core.types import Verdict  # noqa: F401


class Verifier:
    """称'完成'必过 verify_cmd；三态裁决；篡改优先；超时降级(契约 §6 Verifier)。

    canonical 签名(契约 §9 锁#1):
      verify(self, verify_cmd: str | None, *, attempts: int = 1) -> Verdict
    篡改检测与 VERIFY_DIR 隔离由本类内部经 runtime 解决，不接受外部 workspace/verify_dir/tampered。
    """

    def __init__(self, *, max_rounds: int = 3, inline_timeout: float = 60.0) -> None:
        self.max_rounds = max_rounds
        # inline_timeout: 内联快路径上限。真实 pytest 启动 2-5s，默认给 60s 容忍；
        # 调用方可调小做"分级"(超过 → 降级 unverifiable，而非伪 passed)。
        self.inline_timeout = inline_timeout

    def verify(self, verify_cmd: str | None, *, attempts: int = 1) -> Verdict:
        """返回三态 Verdict(passed/failed/unverifiable)。

        优先级：篡改检测 > 命令执行 > 无命令。
        · 篡改非空 → unverifiable(spec §12.5 — 绝不蒙混)。
        · 无 verify_cmd → unverifiable(HONESTY CORRECTION：没有机检命令真的跑过，就绝不
          声称 passed —— 违反 HONESTY_SYSTEM 规则 1。无测任务能否完成由 Harness 据
          "verify_cmd is None" 判定为诚实非阻塞完成，不在此处当 passed 蒙混)。
        · verify_cmd 在白名单 → 跑命令；通过 → passed，失败 → failed，超时 → unverifiable。
        · verify_cmd 不在白名单 → failed(明确拒绝，不静默跳过)。
        """
        # 篡改优先(防贿赂测谎仪)：先查受保护文件，非空 → 直接 unverifiable。
        tampered = runtime.detect_tampering()
        if tampered:
            return Verdict.unverifiable(
                detail=f"验证依赖的受保护文件被改动：{', '.join(tampered)} —— 通过不可信。",
                tampered=tampered, attempts=attempts,
            )

        # 无可机检命令 → 没有任何验证命令真的跑过 → 诚实判 unverifiable(绝不当 passed)。
        # Harness.run_verify_gate 见 verify_cmd is None 时把它当"诚实非阻塞完成"放行(不 bounce)。
        if not verify_cmd:
            return Verdict.unverifiable(
                detail="(无 verify_cmd，未做机检验证)", tampered=[], attempts=attempts,
            )

        ok, detail, timed_out = self._run_verify(verify_cmd)
        if timed_out:
            return Verdict.unverifiable(detail=detail, tampered=[], attempts=attempts)
        if ok:
            return Verdict.passed(detail=detail, verify_cmd=verify_cmd, attempts=attempts)
        return Verdict.failed(detail=detail, verify_cmd=verify_cmd, attempts=attempts)

    def _run_verify(self, cmd: str) -> tuple[bool, str, bool]:
        """跑验证命令，返回 (是否通过, 细节, 是否超时)。退出码是 ground truth。"""
        try:
            parts = shlex.split(cmd)
        except ValueError as e:
            return False, f"验证命令解析失败：{e}", False

        if not parts or Path(parts[0]).name not in ALLOWED_CMDS:
            return False, f"验证命令不在白名单：{cmd}", False

        ctx = runtime.current()
        verify_dir, workspace = ctx.verify_dir, ctx.workspace
        verify_dir.mkdir(parents=True, exist_ok=True)
        workspace.mkdir(parents=True, exist_ok=True)

        env = dict(os.environ)
        env["PYTHONPATH"] = str(workspace) + os.pathsep + env.get("PYTHONPATH", "")

        try:
            r = subprocess.run(
                parts, cwd=verify_dir, capture_output=True, text=True,
                timeout=self.inline_timeout, env=env,
            )
        except subprocess.TimeoutExpired:
            return False, (
                f"[超时] 验证命令 `{cmd}` 超过 {self.inline_timeout}s 未完成 —— "
                f"降级为'无法验证'(不会假装通过)。"
            ), True
        except Exception as e:  # noqa: BLE001
            return False, f"验证执行失败：{e}", False

        out = (r.stdout or "")[-1500:]
        err = (r.stderr or "")[-1500:]
        detail = f"[exit_code={r.returncode}]\n{out}\n{err}".strip()
        return r.returncode == 0, detail, False
