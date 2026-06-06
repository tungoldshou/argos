"""打包产物烟测:dist/argos --selftest 端到端不连网验装配(spec §10 验产物)。

跑法:`python smoke_packaged.py`(在仓库根,需先跑 packaging/build_arm64.sh 产出 dist/argos)。
验证:产物能起、--selftest 退出码 0(整机装配在打包态仍贯通,非 stale)。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    binpath = Path(__file__).resolve().parent / "dist" / "argos"
    if not binpath.exists():
        print(f"FATAL: 产物不存在 {binpath}(先跑 packaging/build_arm64.sh)", file=sys.stderr)
        return 2
    r = subprocess.run([str(binpath), "--selftest"], capture_output=True, text=True, timeout=180)
    print(r.stdout)
    print(r.stderr, file=sys.stderr)
    if r.returncode == 0 and "OK" in r.stdout:
        print("[smoke] 打包产物自检通过 ✅")
        return 0
    print("[smoke] 打包产物自检失败 ❌", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
