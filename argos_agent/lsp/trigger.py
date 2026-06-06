"""LSP 触发辅助:从 code 块抽 write_file/edit_file 调用。

host loop 唯一接入位(spec §2.8):沙箱内 files.py 不动;host 在 sandbox.exec_code
成功后调本模块抽 → 调 lsp_manager.sync_file 触发 didChange。

`extract_file_writes`:
- 正则 r"\\bwrite_file\\(['\"]path['\"]\\s*,\\s*(['\"])content\\1)"
- 抽 (path, content) tuple list
- edit_file 不抽(path 抽得到,old/new 字符串匹配 + content 反推不可靠;用"读 workspace 最新内容"路径)

`extract_file_paths`:
- 抓 write_file / edit_file 涉及的 path 列表(去重)
"""
from __future__ import annotations

import re

# match write_file('path', 'content') or write_file("path", "content")
# content 支持转义(双引号 / 单引号视 \1 而定)
_WRITE_FILE_RE = re.compile(
    r"""\bwrite_file\(\s*(['"])([^'"]+)\1\s*,\s*((['"])((?:\\.|(?!\4).)*)\4)""",
    re.DOTALL,
)
_EDIT_FILE_PATH_RE = re.compile(
    r"""\bedit_file\(\s*(['"])([^'"]+)\1\s*,""",
)


def extract_file_writes(code: str) -> list[tuple[str, str]]:
    """抽 write_file 调用 → [(path, content), ...] 列表(按出现顺序)。

    实现:正则抓 write_file('path', 'content') 或 write_file("path", "content")。
    content 处理 unicode_escape 转义(简化:re 直接抓 raw body,不细化转义语义)。
    edit_file **不**抽(content 不可靠;call site 应走"读 workspace 最新内容"路径)。
    """
    if not code:
        return []
    writes: list[tuple[str, str]] = []
    for m in _WRITE_FILE_RE.finditer(code):
        path = m.group(2)
        raw_body = m.group(5)
        # 处理转义(\\n / \\t / \\\\) Python-style;errors="replace" 兜底防坏字
        content = raw_body.encode("utf-8").decode("unicode_escape", errors="replace")
        writes.append((path, content))
    return writes


def extract_file_paths(code: str) -> list[str]:
    """抽 write_file / edit_file 涉及的 path(给 edit_file 后读最新内容用)。去重,保序。"""
    if not code:
        return []
    paths: list[str] = []
    for m in _WRITE_FILE_RE.finditer(code):
        p = m.group(2)
        if p not in paths:
            paths.append(p)
    for m in _EDIT_FILE_PATH_RE.finditer(code):
        p = m.group(2)
        if p not in paths:
            paths.append(p)
    return paths
