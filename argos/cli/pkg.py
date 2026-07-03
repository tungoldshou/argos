"""Internal documentation."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from argos.i18n import t

__all__ = ["main", "dispatch", "cmd_info", "cmd_check", "cmd_manifest"]


def main() -> int:
    """Internal documentation."""
    return dispatch(sys.argv[1:])


def dispatch(argv: list[str]) -> int:
    """Internal documentation."""
    if not argv or argv[0] in ("-h", "--help"):
        print("usage: argospkg <subcommand> [args]")
        print(t("cli.pkg.usage_info"))
        print(t("cli.pkg.usage_check"))
        print(t("cli.pkg.usage_manifest"))
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
    """Internal documentation."""
    from importlib.metadata import version as _v, metadata as _md  # noqa: PLC0415
    name = "?"
    summary = ""
    homepage = ""
    try:
        name = _v("argos-agent")
    except Exception:  # noqa: BLE001
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

    pkg_ver = Path(__file__).resolve().parents[2] / "packaging" / "VERSION"
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
    except Exception:  # noqa: BLE001
        pass
    return 0


def cmd_check(_rest: list[str]) -> int:
    """Internal documentation."""
    try:
        from argos.__main__ import main as _argos_main  # noqa: F401,PLC0415
        from argos.cli import pkg as _self_pkg  # noqa: F401,PLC0415
    except Exception as e:  # noqa: BLE001
        print(t("cli.pkg.check_import_failed", exc_type=type(e).__name__, err=e), file=sys.stderr)
        return 1
    print("argospkg check: import OK")
    return 0


def cmd_manifest(_rest: list[str]) -> int:
    """Internal documentation."""
    manifest_dir = Path("packaging/winget")
    if not manifest_dir.exists():
        print(t("cli.pkg.manifest_missing", path=manifest_dir), file=sys.stderr)
        return 1
    paths = sorted(manifest_dir.glob("tungoldshou.argos*.yaml"))
    required = {
        "tungoldshou.argos.installer.yaml",
        "tungoldshou.argos.locale.en-US.yaml",
        "tungoldshou.argos.yaml",
    }
    missing = sorted(required - {p.name for p in paths})
    if missing:
        files = ", ".join(str(manifest_dir / name) for name in missing)
        print(t("cli.pkg.manifest_missing_files", files=files), file=sys.stderr)
        return 1
    placeholder_paths: list[Path] = []
    invalid_sha_paths: list[Path] = []
    for p in paths:
        print(f"  - {p}")
        text = p.read_text(encoding="utf-8")
        if "placeholder" in text.lower():
            placeholder_paths.append(p)
        match = re.search(r"^\s*InstallerSha256:\s*(\S*)\s*$", text, re.MULTILINE)
        if match and not re.fullmatch(r"[0-9A-Fa-f]{64}", match.group(1)):
            invalid_sha_paths.append(p)
    if placeholder_paths:
        files = ", ".join(str(p) for p in placeholder_paths)
        print(t("cli.pkg.manifest_placeholder", files=files), file=sys.stderr)
        return 1
    if invalid_sha_paths:
        files = ", ".join(str(p) for p in invalid_sha_paths)
        print(t("cli.pkg.manifest_invalid_sha", files=files), file=sys.stderr)
        return 1
    print(t("cli.pkg.manifest_ready"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
