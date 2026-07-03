from __future__ import annotations

import os
import re
from pathlib import Path

from argos.i18n import t

WORKSPACE: Path | None = None

WRITE_APPROVED_SENTINEL = "\x00__ARGOS_WRITE_APPROVED__\x00"


def _ws() -> Path:
    try:
        from argos import runtime
        ctx = runtime.current()
        if ctx.project_mode:
            return ctx.workspace
    except Exception:  # noqa: BLE001
        pass
    if WORKSPACE is not None:
        return WORKSPACE.resolve()
    from argos import config
    root = Path(config.get("ARGOS_CONFIG_DIR") or (Path.home() / ".argos")).expanduser()
    return Path(os.environ.get("ARGOS_WORKSPACE") or (root / "workspace")).expanduser().resolve()


def _safe_path(rel: str, *, allow_extra_write_dirs: bool = False) -> Path | None:
    ws = _ws()
    ws.mkdir(parents=True, exist_ok=True)
    if rel == "/app":
        norm = ""
    elif rel.startswith("/app/"):
        norm = rel[len("/app/"):]
    else:
        norm = rel
    p = (ws / norm).resolve()

    def _within(base) -> bool:
        try:
            p.relative_to(base)
            return True
        except ValueError:
            return False

    if _within(ws):
        return p
    if not allow_extra_write_dirs:
        return None
    from argos.config import extra_write_dirs
    if any(_within(extra) for extra in extra_write_dirs()):
        return p
    return None


def read_file(path: str, offset: int = 0, limit: int | None = None) -> str:
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
    if total == 0:
        return t("tools.files.read.header", path=path, start=0, end=0, total=0, chunk="")
    if offset >= total:
        return t("tools.files.read.offset_oob", total=total, offset=offset)
    end = offset + limit if limit is not None else total
    chunk = "".join(lines[offset:end])
    start_line = offset + 1
    end_line = min(end, total)
    return t("tools.files.read.header", path=path, start=start_line, end=end_line, total=total, chunk=chunk)


def write_file(path: str, content: str) -> str:
    p = _safe_path(path, allow_extra_write_dirs=True)
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


_OCCURRENCES_CAP = 1000


def edit_file(path: str, old: str, new: str, all_occurrences: bool = False) -> str:
    p = _safe_path(path, allow_extra_write_dirs=True)
    if p is None:
        return t("tools.files.edit.outside_workspace", path=path)
    if not p.exists():
        return t("tools.files.edit.not_found", path=path)
    try:
        text = p.read_text(encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        return t("tools.files.edit.failed", exc=e)

    def _write_text(new_text: str) -> str | None:
        try:
            p.write_text(new_text, encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            return t("tools.files.edit.failed", exc=e)
        return None

    count = text.count(old)
    if count >= 2 and not all_occurrences:
        return t("tools.files.edit.ambiguous", count=count)
    if count >= 2 and all_occurrences:
        if count > _OCCURRENCES_CAP:
            return t("tools.files.edit.too_many", count=count, cap=_OCCURRENCES_CAP)
        new_text = text.replace(old, new)
        if err := _write_text(new_text):
            return err
        return t("tools.files.edit.ok_n", path=path, count=count)
    if count == 1:
        if all_occurrences:
            if err := _write_text(text.replace(old, new)):
                return err
            return t("tools.files.edit.ok_1_all", path=path)
        if err := _write_text(text.replace(old, new)):
            return err
        return t("tools.files.edit.ok_unique", path=path)
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
        if err := _write_text("".join(new_lines)):
            return err
        return t("tools.files.edit.ok_n_fuzzy", path=path, count=len(matches))
    i, j = matches[0]
    new_segment = new if new.endswith("\n") or j + 1 >= len(lines) else new + "\n"
    new_lines = lines[:i] + [new_segment] + lines[j + 1:]
    if err := _write_text("".join(new_lines)):
        return err
    return t("tools.files.edit.ok_1_fuzzy", path=path)


_SEARCH_DEADLINE_S = 20.0
_SEARCH_SKIP_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".argos",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build",
    ".next", "target", ".idea", ".vscode", ".tox", ".cache",
}
_SEARCH_MAX_FILE_BYTES = 2_000_000


def search_files(pattern: str, target: str = "content", file_glob: str = "", limit: int = 50) -> str:
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
            if file_glob and not (fnmatch.fnmatch(fn, file_glob) or fnmatch.fnmatch(rel, file_glob)):
                continue
            try:
                if os.path.getsize(fp) > _SEARCH_MAX_FILE_BYTES:
                    continue
                with open(fp, "r", encoding="utf-8") as f:
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
