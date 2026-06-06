"""`argospkg` 命令 — 打包工具 dispatcher(spec D8,plan 2026-06-07 T2)。

主 `argos` 跑 agent;`argospkg` 跑打包/发布辅助。**0 业务逻辑**:纯 CLI 工具,
只读 pyproject.toml / packaging/VERSION / git tag,导入 self 验可达。

子命令:
  info      — 打印项目元数据 + packaging/VERSION + git tag
  check     — 校验 self + argos_agent 入口 import 成功
  manifest  — 预演 winget manifest 生成(v0.2.0 真出;v0.1.0 仅占位)

不破:`__main__.py` 主 `argos` 启动 0 影响(本模块只在 `argospkg` 命令路径 import)。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

__all__ = ["main", "dispatch", "cmd_info", "cmd_check", "cmd_manifest"]


def main() -> int:
    """`argospkg` 入口。sys.argv[1:] 切子命令。无参/--help 走 usage。"""
    return dispatch(sys.argv[1:])


def dispatch(argv: list[str]) -> int:
    """分发到子命令。无参/--help 返 0(usage);未知子命令返 2。"""
    if not argv or argv[0] in ("-h", "--help"):
        print("usage: argospkg <subcommand> [args]")
        print("  info      — 打印项目元数据 + packaging/VERSION + git tag")
        print("  check     — 校验 self + argos_agent 入口 import 成功")
        print("  manifest  — 预演生成 winget manifest(v0.2.0 真出)")
        return 0 if argv else 1
    sub, *rest = argv
    handler = {
        "info": cmd_info,
        "check": cmd_check,
        "manifest": cmd_manifest,
    }.get(sub)
    if handler is None:
        print(f"argospkg: unknown subcommand (got {sub!r})", file=sys.stderr)
        print("usage: argospkg <subcommand>  (try: info | check | manifest)", file=sys.stderr)
        return 2
    return handler(rest)


def cmd_info(_rest: list[str]) -> int:
    """打印 pyproject [project] 段 + packaging/VERSION + git tag(若在 git 仓里)。

    失败不抛:任一字段拿不到就标 '?'(诚实)。
    """
    from importlib.metadata import version as _v, metadata as _md  # noqa: PLC0415
    name = "?"
    summary = ""
    homepage = ""
    try:
        name = _v("argos-agent")
    except Exception:  # noqa: BLE001 — 离线/未装时降级
        pass
    try:
        meta = _md("argos-agent")
        summary = meta.get("Summary", "") or ""
        homepage = meta.get("Home-page", "") or ""
    except Exception:  # noqa: BLE001
        pass
    print("name:        argos-agent")
    print(f"version:     {name}")
    print(f"summary:     {summary}")
    print(f"homepage:    {homepage or 'https://github.com/tungoldshou/argos'}")

    pkg_ver = Path("packaging/VERSION")
    if pkg_ver.exists():
        print(f"pkg/VERSION: {pkg_ver.read_text().strip()}")
    else:
        print("pkg/VERSION: (not found)")

    try:
        tag = subprocess.check_output(
            ["git", "describe", "--tags", "--abbrev=0"],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
        print(f"git tag:     {tag}")
    except Exception:  # noqa: BLE001 — 非 git 仓 / 无 tag
        pass
    return 0


def cmd_check(_rest: list[str]) -> int:
    """校验 argos_agent 入口 + self 导入成功。

    返回 0 = import OK,非 0 = 失败(必 stderr 报原因)。
    """
    try:
        from argos_agent.__main__ import main as _argos_main  # noqa: F401,PLC0415
        from argos_agent.cli import pkg as _self_pkg  # noqa: F401,PLC0415
    except Exception as e:  # noqa: BLE001
        print(f"argospkg check: import 失败:{type(e).__name__}: {e}", file=sys.stderr)
        return 1
    print("argospkg check: import OK")
    return 0


def cmd_manifest(_rest: list[str]) -> int:
    """预演生成 winget manifest(v0.1.0 仅占位;v0.2.0 接 wingetcreate)。

    列出 packaging/winget/ 下的 3 件文件路径,供手动 PR 审阅。
    """
    print("argospkg manifest: v0.1.0 仅占位;v0.2.0 接 wingetcreate 自动生成")
    manifest_dir = Path("packaging/winget")
    if manifest_dir.exists():
        for p in sorted(manifest_dir.glob("tungoldshou.argos.*.yaml")):
            print(f"  - {p}")
    else:
        print("  (no packaging/winget/ directory yet)")
    return 0


if __name__ == "__main__":  # 让 `python -m argos_agent.cli.pkg info` 也能跑(必须放最后,所有 def 都已定义)
    sys.exit(main())
