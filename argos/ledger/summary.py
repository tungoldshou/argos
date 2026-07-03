"""Internal documentation."""
from __future__ import annotations

import os

from argos.i18n import t


def summarize(action: str, args: dict) -> str:
    """Internal documentation."""
    a = action.lower()

    if a in ("write_file", "create_file"):
        path = _short_path(args.get("path", args.get("file_path", "")))
        lines = args.get("lines_added") or args.get("lines") or args.get("content", "")
        if isinstance(lines, str):
            lines = lines.count("\n") + 1 if lines else 0
        if lines:
            return t("ledger.summary_write_lines", path=path or t("ledger.summary_file_unknown"), lines=lines)
        return t("ledger.summary_write", path=path or t("ledger.summary_file_unknown"))

    if a in ("edit_file", "patch_file"):
        path = _short_path(args.get("path", args.get("file_path", "")))
        added = args.get("lines_added", args.get("added", 0)) or 0
        removed = args.get("lines_removed", args.get("removed", 0)) or 0
        if added or removed:
            return t("ledger.summary_edit_diff", path=path or t("ledger.summary_file_unknown"), added=added, removed=removed)
        return t("ledger.summary_edit", path=path or t("ledger.summary_file_unknown"))

    if a in ("read_file", "read"):
        path = _short_path(args.get("path", args.get("file_path", "")))
        return t("ledger.summary_read", path=path or t("ledger.summary_file_unknown"))

    if a in ("delete_file", "remove_file", "unlink"):
        path = _short_path(args.get("path", args.get("file_path", "")))
        return t("ledger.summary_delete", path=path or t("ledger.summary_file_unknown"))

    if a in ("list_dir", "listdir", "ls"):
        path = _short_path(args.get("path", args.get("dir", "")))
        return t("ledger.summary_listdir", path=path or t("ledger.summary_dir_unknown"))

    if a in ("mkdir", "makedirs"):
        path = _short_path(args.get("path", args.get("dir", "")))
        return t("ledger.summary_mkdir", path=path or t("ledger.summary_dir_unknown"))

    if a in ("run_shell", "run_command", "bash", "shell", "exec"):
        cmd = str(args.get("command", args.get("cmd", ""))).strip()
        if cmd:
            short = cmd[:60] + ("…" if len(cmd) > 60 else "")
            return t("ledger.summary_shell_cmd", cmd=short)
        return t("ledger.summary_shell")

    if a in ("web_fetch", "http_get", "fetch"):
        url = _short_url(args.get("url", ""))
        return t("ledger.summary_get", url=url or t("ledger.summary_url_unknown"))

    if a in ("web_search",):
        q = str(args.get("query", args.get("q", ""))).strip()
        if q:
            return t("ledger.summary_search_q", q=q[:50])
        return t("ledger.summary_search")

    if a in ("http_post", "post"):
        url = _short_url(args.get("url", ""))
        return t("ledger.summary_post", url=url or t("ledger.summary_url_unknown"))

    if a in ("browser_navigate", "navigate"):
        url = _short_url(args.get("url", args.get("href", "")))
        return t("ledger.summary_navigate", url=url or t("ledger.summary_url_unknown"))

    if a in ("browser_click", "click"):
        target = args.get("selector", args.get("text", args.get("element", "")))
        if target:
            return t("ledger.summary_click_target", target=str(target)[:40])
        return t("ledger.summary_click")

    if a in ("browser_fill", "fill", "type"):
        selector = args.get("selector", args.get("field", ""))
        value = args.get("value", args.get("text", ""))
        if selector:
            return t("ledger.summary_fill", selector=str(selector)[:30], value=str(value)[:30])
        return t("ledger.summary_fill_no_sel")

    if a in ("browser_screenshot", "screenshot"):
        return t("ledger.summary_screenshot")

    return t("ledger.summary_unknown", action=action)



def _short_path(path: str) -> str:
    """Internal documentation."""
    if not path:
        return ""
    return os.path.basename(str(path)) or str(path)


def _short_url(url: str) -> str:
    """Internal documentation."""
    url = str(url).strip()
    if not url:
        return ""
    return url[:60] + ("…" if len(url) > 60 else "")
