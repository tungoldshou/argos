"""人话 summary 生成器(spec §6 信任面)。

从 Receipt.action + args 的确定性模板生成人话一句 —— 不调模型,0 成本,幂等。
模板覆盖常见动作类型;未知动作退化诚实描述(不编造)。

动作分类:
  文件系统  write_file / read_file / delete_file / edit_file / list_dir
  Shell     run_shell / run_command / bash
  网络      web_fetch / web_search / http_get / http_post
  浏览器    browser_navigate / browser_click / browser_fill / browser_screenshot
  工具      任何其他注册动作 → 通用格式
"""
from __future__ import annotations

import os


def summarize(action: str, args: dict) -> str:
    """从 action + args 生成人话一句(确定性模板)。

    Args:
        action: Receipt.action 字段(如 "write_file")
        args:   Receipt 对应的原始 args dict(由调用方从回执中拿)
                若无原始 args 信息传空 dict({})

    Returns:
        人话字符串,如 "写入了 report.md(+120 行)"
    """
    a = action.lower()

    # ── 文件系统动作 ──────────────────────────────────────────────────
    if a in ("write_file", "create_file"):
        path = _short_path(args.get("path", args.get("file_path", "")))
        lines = args.get("lines_added") or args.get("lines") or args.get("content", "")
        if isinstance(lines, str):
            lines = lines.count("\n") + 1 if lines else 0
        if lines:
            return f"写入了 {path or '文件'}(+{lines} 行)"
        return f"写入了 {path or '文件'}"

    if a in ("edit_file", "patch_file"):
        path = _short_path(args.get("path", args.get("file_path", "")))
        added = args.get("lines_added", args.get("added", 0)) or 0
        removed = args.get("lines_removed", args.get("removed", 0)) or 0
        if added or removed:
            return f"编辑了 {path or '文件'}(+{added}/-{removed} 行)"
        return f"编辑了 {path or '文件'}"

    if a in ("read_file", "read"):
        path = _short_path(args.get("path", args.get("file_path", "")))
        return f"读取了 {path or '文件'}"

    if a in ("delete_file", "remove_file", "unlink"):
        path = _short_path(args.get("path", args.get("file_path", "")))
        return f"删除了 {path or '文件'}"

    if a in ("list_dir", "listdir", "ls"):
        path = _short_path(args.get("path", args.get("dir", "")))
        return f"列出了目录 {path or '.'}"

    if a in ("mkdir", "makedirs"):
        path = _short_path(args.get("path", args.get("dir", "")))
        return f"创建了目录 {path or '.'}"

    # ── Shell / 命令 ──────────────────────────────────────────────────
    if a in ("run_shell", "run_command", "bash", "shell", "exec"):
        cmd = str(args.get("command", args.get("cmd", ""))).strip()
        if cmd:
            short = cmd[:60] + ("…" if len(cmd) > 60 else "")
            return f"跑了命令: {short}"
        return "跑了 shell 命令"

    # ── 网络请求 ──────────────────────────────────────────────────────
    if a in ("web_fetch", "http_get", "fetch"):
        url = _short_url(args.get("url", ""))
        return f"发出了 GET 请求: {url or '(url 未知)'}"

    if a in ("web_search",):
        q = str(args.get("query", args.get("q", ""))).strip()
        if q:
            return f"搜索了: {q[:50]}"
        return "发出了网络搜索"

    if a in ("http_post", "post"):
        url = _short_url(args.get("url", ""))
        return f"发出了 POST 请求: {url or '(url 未知)'}"

    # ── 浏览器动作 ────────────────────────────────────────────────────
    if a in ("browser_navigate", "navigate"):
        url = _short_url(args.get("url", args.get("href", "")))
        return f"浏览器导航至: {url or '(url 未知)'}"

    if a in ("browser_click", "click"):
        target = args.get("selector", args.get("text", args.get("element", "")))
        if target:
            return f"点击了: {str(target)[:40]}"
        return "浏览器点击操作"

    if a in ("browser_fill", "fill", "type"):
        selector = args.get("selector", args.get("field", ""))
        value = args.get("value", args.get("text", ""))
        if selector:
            return f"填写了 {str(selector)[:30]}: {str(value)[:30]}"
        return "浏览器输入操作"

    if a in ("browser_screenshot", "screenshot"):
        return "截取了浏览器截图"

    # ── 通用兜底 ──────────────────────────────────────────────────────
    # 未知动作:诚实格式(不编造)
    return f"执行了 {action}"


# ── 内部工具 ──────────────────────────────────────────────────────────

def _short_path(path: str) -> str:
    """取路径 basename,避免泄漏完整绝对路径。空串原样返回。"""
    if not path:
        return ""
    return os.path.basename(str(path)) or str(path)


def _short_url(url: str) -> str:
    """截断 URL 到 60 字符,避免账本条目过长。"""
    url = str(url).strip()
    if not url:
        return ""
    return url[:60] + ("…" if len(url) > 60 else "")
