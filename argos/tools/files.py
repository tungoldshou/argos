"""纯沙箱 file 工具(契约 §4):read_file/write_file/edit_file/search_files。

裸 Python 函数(注入沙箱命名空间,变量跨 code-action 存活)。安全沿用旧 tools.py:
  · 路径牢笼在 workspace 内,越界返错误串(不抛异常,模型自纠 —— ReAct)。
  · 写在沙箱内额外受 Seatbelt OS 牢笼(纵深);越界写双重挡(路径解析 + OS)。
工作目录:project 模式用 runtime 覆盖,否则用模块级默认(测试 monkeypatch WORKSPACE)。
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from argos.i18n import t

WORKSPACE = Path(os.environ.get("ARGOS_WORKSPACE", Path.home() / ".argos" / "workspace")).resolve()

# host→child 放行哨兵:broker 对一次文件写做完 gate-only 治理(hard-path/密钥)并签回执后,
# 把它回灌给沙箱子进程;子进程内的 write_file/edit_file 包装识别到它才真正落盘(写留在 Seatbelt 内,
# Codex 式 workspace-write 自动应用)。含 NUL,绝不与正常工具返回串/文件内容碰撞。
WRITE_APPROVED_SENTINEL = "\x00__ARGOS_WRITE_APPROVED__\x00"


def _ws() -> Path:
    """当前生效 workspace:project 模式用 runtime,否则用模块默认(沿用旧 tools._ws)。"""
    try:
        from argos import runtime
        ctx = runtime.current()
        return ctx.workspace if ctx.project_mode else WORKSPACE
    except Exception:  # noqa: BLE001 —— runtime 未就位(早期阶段)退回模块默认
        return WORKSPACE


def _safe_path(rel: str) -> Path | None:
    """把传入的 path 解析为 workspace 内的安全路径,越界返 None。

    路径约定(适配 TB 任务):TB 任务 agent 看到的"工作区"是容器内 /app(worktree 在
    host),agent 用 `/app/...` 写文件是**预期**的。适配器把 /app/... 视作 worktree 根
    下的相对路径(`/app/foo` → `<ws>/foo`),让 agent 不用知道底层 worktree 在 host
    的实际位置。

    安全:仅翻译 `/app/` 前缀(不是任何前导 `/`)。`/etc/passwd` 这类仍是工作区
    之外的越界,仍拒。`../../../etc/...` 走相对路径解析后越界,也仍拒。
    """
    ws = _ws()
    ws.mkdir(parents=True, exist_ok=True)
    # 仅翻译 /app/ 前缀(适配器契约:agent 在容器里看到的工作区是 /app)。
    if rel == "/app":
        norm = ""  # /app → ws 根
    elif rel.startswith("/app/"):
        norm = rel[len("/app/"):]  # 剥 /app/ 前缀
    else:
        norm = rel  # 其他路径原样(后续 _ws / norm + relative_to 仍做越界检查)
    p = (ws / norm).resolve()
    try:
        p.relative_to(ws)
    except ValueError:
        return None
    return p


def read_file(path: str, offset: int = 0, limit: int | None = None) -> str:
    """读取 workspace 内某个文件。offset=起始行号(0-based,默认 0=从头);
    limit=读多少行(默认 None=读到 EOF)。
    越界 / 不存在 / offset 负数 / limit<=0 → 错误串(不抛异常)。"""
    p = _safe_path(path)
    if p is None:
        return t("tools.files.read.outside_workspace", path=path)
    if not p.exists():
        return t("tools.files.read.not_found", path=path)
    if offset < 0:
        return t("tools.files.read.offset_negative", offset=offset)
    if limit is not None and limit <= 0:
        return t("tools.files.read.limit_invalid", limit=limit)
    try:
        text = p.read_text(encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        return t("tools.files.read.failed", exc=e)
    lines = text.splitlines(keepends=True)
    total = len(lines)
    if offset >= total:
        return t("tools.files.read.offset_oob", total=total, offset=offset)
    end = offset + limit if limit is not None else total
    chunk = "".join(lines[offset:end])
    start_line = offset + 1
    end_line = min(end, total)
    return t("tools.files.read.header", path=path, start=start_line, end=end_line, total=total, chunk=chunk)


def write_file(path: str, content: str) -> str:
    """把内容写入 workspace 内某个文件(覆盖)。path 是相对 workspace 的路径。"""
    p = _safe_path(path)
    if p is None:
        return t("tools.files.write.outside_workspace", path=path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        return t("tools.files.write.failed", exc=e)
    return t("tools.files.write.ok", path=path, nbytes=len(content))


def _normalize_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


_OCCURRENCES_CAP = 1000  # 防爆:超过此数报"匹配过多"


def edit_file(path: str, old: str, new: str, all_occurrences: bool = False) -> str:
    """在 workspace 内某文件里把 old 串替换成 new。
    all_occurrences=False(默认)=唯一匹配,多处命中报错(同旧);
    all_occurrences=True = 替换全部出现,返回 '已编辑 path(N 处)';
    上限 _OCCURRENCES_CAP=1000(防爆)。"""
    p = _safe_path(path)
    if p is None:
        return t("tools.files.edit.outside_workspace", path=path)
    if not p.exists():
        return t("tools.files.edit.not_found", path=path)
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count >= 2 and not all_occurrences:
        return t("tools.files.edit.ambiguous", count=count)
    if count >= 2 and all_occurrences:
        if count > _OCCURRENCES_CAP:
            return t("tools.files.edit.too_many", count=count, cap=_OCCURRENCES_CAP)
        new_text = text.replace(old, new)
        p.write_text(new_text, encoding="utf-8")
        return t("tools.files.edit.ok_n", path=path, count=count)
    if count == 1:
        if all_occurrences:
            p.write_text(text.replace(old, new), encoding="utf-8")
            return t("tools.files.edit.ok_1_all", path=path)
        p.write_text(text.replace(old, new), encoding="utf-8")
        return t("tools.files.edit.ok_unique", path=path)
    # count == 0:走模糊匹配兜底(同旧)
    target = _normalize_ws(old)
    lines = text.splitlines(keepends=True)
    matches: list[tuple[int, int]] = []
    for i in range(len(lines)):
        acc = ""
        for j in range(i, len(lines)):
            acc += lines[j]
            norm = _normalize_ws(acc)
            if norm == target:
                matches.append((i, j))
                break
            if len(norm) > len(target):
                break
    if len(matches) == 0:
        return t("tools.files.edit.not_found_fuzzy")
    if len(matches) > 1:
        if not all_occurrences:
            return t("tools.files.edit.ambiguous_fuzzy", count=len(matches))
        if len(matches) > _OCCURRENCES_CAP:
            return t("tools.files.edit.too_many_fuzzy", count=len(matches), cap=_OCCURRENCES_CAP)
        new_lines: list[str] = []
        covered = 0
        for i, j in matches:
            new_lines.extend(lines[covered:i])
            seg = new if new.endswith("\n") or j + 1 >= len(lines) else new + "\n"
            new_lines.append(seg)
            covered = j + 1
        new_lines.extend(lines[covered:])
        p.write_text("".join(new_lines), encoding="utf-8")
        return t("tools.files.edit.ok_n_fuzzy", path=path, count=len(matches))
    # 模糊唯一
    i, j = matches[0]
    new_segment = new if new.endswith("\n") or j + 1 >= len(lines) else new + "\n"
    new_lines = lines[:i] + [new_segment] + lines[j + 1:]
    p.write_text("".join(new_lines), encoding="utf-8")
    return t("tools.files.edit.ok_1_fuzzy", path=path)


# 搜索改纯 Python(os.walk + re),不再 shell 出 rg —— rg 在 Seatbelt 沙箱里会挂死,且
# profile 的 (allow signal (target self)) 让子进程杀不掉它,subprocess.run 的超时也兜不住 →
# 整个 exec 永久卡死(2026-06-20 真机:search_files 卡 30+ 分钟)。纯 Python 终止可控,
# 再加内部 deadline 自兜底(不依赖 smolagents 中断 —— 它的 shutdown(wait=True) 会被卡住的线程拖死)。
_SEARCH_DEADLINE_S = 20.0
# 原地剪枝的重目录(性能 + 噪声;与 rg 默认忽略 .gitignore/隐藏一致的精简版)。
_SEARCH_SKIP_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".argos",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build",
    ".next", "target", ".idea", ".vscode", ".tox", ".cache",
}
_SEARCH_MAX_FILE_BYTES = 2_000_000   # 跳过 >2MB 的大/二进制文件


def search_files(pattern: str, target: str = "content", file_glob: str = "", limit: int = 50) -> str:
    """在 workspace 内搜索(纯 Python,沙箱内不挂、带内部时限):
    target='content' 用正则搜文件正文(带行号);target='files' 按 glob(如 '*.py')找文件名。"""
    import fnmatch
    import time
    ws = _ws()
    ws.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + _SEARCH_DEADLINE_S
    results: list[str] = []
    truncated = timed_out = False

    rx = None
    if target != "files":
        try:
            rx = re.compile(pattern)
        except re.error as e:
            return t("tools.files.search.regex_error", exc=e)

    for root, dirs, names in os.walk(ws):
        # 原地剪枝:跳过重目录 + 隐藏目录(与 rg 默认一致),性能 + 降噪。
        dirs[:] = [d for d in dirs if d not in _SEARCH_SKIP_DIRS and not d.startswith(".")]
        if time.time() > deadline:
            timed_out = True
            break
        for fn in names:
            fp = os.path.join(root, fn)
            rel = os.path.relpath(fp, ws)
            if target == "files":
                pat = pattern or "*"
                if fnmatch.fnmatch(fn, pat) or fnmatch.fnmatch(rel, pat):
                    results.append(rel)
                    if len(results) >= limit:
                        truncated = True
                        break
                continue
            # content 搜索:file_glob 过滤(空=全搜)
            if file_glob and not (fnmatch.fnmatch(fn, file_glob) or fnmatch.fnmatch(rel, file_glob)):
                continue
            try:
                if os.path.getsize(fp) > _SEARCH_MAX_FILE_BYTES:
                    continue
                with open(fp, "r", encoding="utf-8") as f:   # 二进制 → UnicodeDecodeError → 跳过
                    for i, line in enumerate(f, 1):
                        if rx.search(line):
                            results.append(f"{rel}:{i}:{line.rstrip()}")
                            if len(results) >= limit:
                                truncated = True
                                break
            except (OSError, UnicodeDecodeError):
                continue
            if truncated:
                break
            if time.time() > deadline:
                timed_out = True
                break
        if truncated or timed_out:
            break

    if not results:
        return (
            t("tools.files.search.no_match_timeout") if timed_out
            else t("tools.files.search.no_match")
        )
    out = "\n".join(results)
    tail = []
    if truncated:
        tail.append(t("tools.files.search.truncated_suffix", limit=limit))
    if timed_out:
        tail.append(t("tools.files.search.timeout_suffix", deadline=int(_SEARCH_DEADLINE_S)))
    if tail:
        out += "\n…(" + ";".join(tail) + ")"
    return out
