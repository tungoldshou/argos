"""#9 Auto memory 4 tier 模块(扩展 argos.memory,不污染任务历史接口)。

四层记忆:user(全局用户偏好) / project(per-repo 约定) / skill(per-skill 失败) /
session(per-run 临时,30 天 rotate)。Append-only JSONL + threading.Lock,无 sqlite
新依赖。详见 docs/superpowers/specs/2026-06-06-auto-memory-design.md。

D1:JSONL(与 RunStore 同模式)
D3:CLAUDE.md 注入在 untrusted 围栏内的 <memory_context> 段
D5:project_id = sha1(repo_root | cwd)[:16]
D20:threading.Lock 包裹写
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Literal

from argos.i18n import t

# ── 公共类型(spec §4.2)───────────────────────────────────────────────────────
Scope = Literal["user", "project", "skill", "session"]
Type = Literal["preference", "convention", "failure", "decision", "fact"]


@dataclass(frozen=True, slots=True)
class MemoryEntry:
    id: str
    type: Type
    scope: Scope
    key: str
    value: str
    confidence: float
    evidence: tuple[str, ...]
    ts: float
    last_used_at: float
    use_count: int
    skill_name: str | None = None
    project_id: str | None = None
    session_id: str | None = None


# ── 路径解析 ─────────────────────────────────────────────────────────────────
def _root() -> Path:
    """记忆根目录:env var 优先(测试用),否则 ~/.argos/memory/。"""
    override = os.environ.get("ARGOS_MEMORY_DIR")
    return Path(override) if override else Path.home() / ".argos" / "memory"


def _user_path() -> Path:
    return _root() / "user.jsonl"


def _project_path(project_id: str) -> Path:
    return _root() / "projects" / f"{project_id}.jsonl"


def _skill_path(skill_name: str) -> Path:
    return _root() / "skills" / f"{skill_name}.jsonl"


def _session_path(session_id: str) -> Path:
    return _root() / "sessions" / f"{session_id}.jsonl"


def project_id_for(cwd: Path | None = None) -> str:
    """计算 project_id:用 cwd 绝对路径 sha1 前 16。无 .git 也行(本期不 walk up git)。"""
    p = (cwd or Path.cwd()).resolve()
    return hashlib.sha1(str(p).encode("utf-8")).hexdigest()[:16]


# ── 读写 ─────────────────────────────────────────────────────────────────────
_write_lock = threading.Lock()
_PROJECT_ID_CACHE: dict[str, str] = {}


def _read_jsonl(path: Path) -> list[MemoryEntry]:
    """读 JSONL,坏行跳过,文件不存在返空(诚实空态)。"""
    if not path.exists():
        return []
    out: list[MemoryEntry] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []  # IOError 静默返空(spec §10)
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue  # 一行坏数据不毁整个记忆
        try:
            out.append(MemoryEntry(
                id=d["id"],
                type=d["type"],
                scope=d["scope"],
                key=d["key"],
                value=d["value"],
                confidence=float(d["confidence"]),
                evidence=tuple(d.get("evidence") or ()),
                ts=float(d["ts"]),
                last_used_at=float(d.get("last_used_at") or d["ts"]),
                use_count=int(d.get("use_count") or 0),
                skill_name=d.get("skill_name"),
                project_id=d.get("project_id"),
                session_id=d.get("session_id"),
            ))
        except (KeyError, ValueError, TypeError):
            continue  # schema 不全的行也跳过
    return out


def _append_jsonl(path: Path, entry: MemoryEntry) -> None:
    """追加一条记忆(JSONL),parent dirs 自动建。失败静默(spec §10)。

    任务:抽 jsonl_log.append_line(目录自动建 + IO 静默),锁仍在助手外层。
    tuple → list 的 evidence 转换 + 字段构造仍在本函数(jsonl_log 是通用助手,
    不理解 MemoryEntry dataclass)。
    """
    with _write_lock:
        d = asdict(entry)
        d["evidence"] = list(entry.evidence)  # tuple → list(JSON 友好)
        from argos import jsonl_log
        jsonl_log.append_line(path, d)


# ── 检索 / 排序(spec §8)──────────────────────────────────────────────────────
_TYPE_PRIORITY = {"failure": 5, "decision": 4, "convention": 3,
                  "preference": 2, "fact": 1}
_MIN_CONFIDENCE = 0.3  # D6:低于阈值不参与 ranking(spec §9.1)


def _new_id() -> str:
    """生成 12 字符短 id(同 memory.record_task 风格)。"""
    return uuid.uuid4().hex[:12]


def _score(entry: MemoryEntry) -> float:
    """score = recency × confidence。recency = exp(-0.01 × days_since_last_used)。"""
    days = max(0.0, (time.time() - entry.last_used_at) / 86400.0)
    recency = math.exp(-0.01 * days)
    return recency * entry.confidence


def _rank(entries: Iterable[MemoryEntry], limit: int) -> list[MemoryEntry]:
    """type 优先级 → score → top N。低于 _MIN_CONFIDENCE 排除。"""
    eligible = [e for e in entries if e.confidence >= _MIN_CONFIDENCE]
    eligible.sort(
        key=lambda e: (_TYPE_PRIORITY.get(e.type, 0), _score(e)),
        reverse=True,
    )
    return eligible[:limit]


def load(*, scope: Scope | None = None,
         project_id: str | None = None,
         skill_name: str | None = None,
         session_id: str | None = None,
         limit: int = 50,
         cwd: Path | None = None) -> list[MemoryEntry]:
    """读 4 tier 合并后 ranking;scope 指定时只读该 tier。

    - scope=None → 读所有可用 tier(user + auto-discover project + skill/session 需传名)
    - scope=指定 → 只读该 tier
    - project_id 缺省时,project tier 走 project_id_for(cwd)
    """
    paths: list[Path] = []
    if scope is None or scope == "user":
        paths.append(_user_path())
    if scope is None or scope == "project":
        pid = project_id or project_id_for(cwd)
        if pid:
            paths.append(_project_path(pid))
    if scope is None or scope == "skill":
        if skill_name:
            paths.append(_skill_path(skill_name))
    if scope is None or scope == "session":
        if session_id:
            paths.append(_session_path(session_id))
    out: list[MemoryEntry] = []
    for p in paths:
        out.extend(_read_jsonl(p))
    return _rank(out, limit)


def touch(entry: MemoryEntry) -> None:
    """被注入系统提示后调用:use_count +1, confidence +0.02, last_used_at = now。
    原地改写对应 JSONL。失败静默。
    """
    new_conf = min(1.0, entry.confidence + 0.02)
    new_entry = MemoryEntry(
        id=entry.id, type=entry.type, scope=entry.scope,
        key=entry.key, value=entry.value, confidence=new_conf,
        evidence=entry.evidence, ts=entry.ts,
        last_used_at=time.time(), use_count=entry.use_count + 1,
        skill_name=entry.skill_name, project_id=entry.project_id,
        session_id=entry.session_id,
    )
    # 找到该 entry 所在的文件 → 改写
    path = _entry_path(entry)
    if path is None:
        return
    entries = _read_jsonl(path)
    for i, e in enumerate(entries):
        if e.id == entry.id:
            entries[i] = new_entry
            break
    else:
        return
    # 原子写:写临时文件再 rename
    with _write_lock:
        try:
            tmp = path.with_suffix(path.suffix + ".tmp")
            with tmp.open("w", encoding="utf-8") as fh:
                for e in entries:
                    d = asdict(e)
                    d["evidence"] = list(e.evidence)
                    fh.write(json.dumps(d, ensure_ascii=False) + "\n")
            tmp.replace(path)
        except OSError:
            pass


def _entry_path(entry: MemoryEntry) -> Path | None:
    """由 entry 反查所在 JSONL 文件。"""
    if entry.scope == "user":
        return _user_path()
    if entry.scope == "project" and entry.project_id:
        return _project_path(entry.project_id)
    if entry.scope == "skill" and entry.skill_name:
        return _skill_path(entry.skill_name)
    if entry.scope == "session" and entry.session_id:
        return _session_path(entry.session_id)
    return None


def _dedup(scope: Scope, key: str, value: str, *,
           path: Path, hours: int = 24) -> bool:
    """24h 内同 (scope,key,value) 已有 → True(应跳过)。"""
    cutoff = time.time() - hours * 3600
    for e in _read_jsonl(path):
        if e.key == key and e.value == value and e.ts >= cutoff:
            return True
    return False


# ── CLAUDE.md / AGENTS.md 自动发现 + 合并(spec §5)──────────────────────────
_PER_FILE_LIMIT = 20_000   # spec §5.2:每文件 ≤ 20k 字符
_TOTAL_LIMIT = 30_000      # spec §5.2:总 ≤ 30k 字符


def _ARGOS_HOME() -> Path:
    """Argos home 用于放全局 CLAUDE.md / AGENTS.md。

    优先 ARGOS_HOME env var(测试),否则 ~/.argos/。"""
    override = os.environ.get("ARGOS_HOME")
    return Path(override) if override else Path.home() / ".argos"


def _global_claude() -> Path:
    return _ARGOS_HOME() / "CLAUDE.md"


def _global_agents() -> Path:
    return _ARGOS_HOME() / "AGENTS.md"


def walk_claude_md_files(start: Path) -> list[Path]:
    """从 start 向上走到 filesystem root,收集 CLAUDE.md / AGENTS.md。

    返回 [最近, ..., 最远] 顺序(子→父)。同目录里两个文件都收。
    失败/不存在静默跳过。
    """
    out: list[Path] = []
    seen: set[Path] = set()
    try:
        cur = start.resolve()
    except (OSError, RuntimeError):
        return out
    while True:
        for name in ("CLAUDE.md", "AGENTS.md"):
            try:
                p = cur / name
            except (OSError, ValueError):
                continue
            try:
                if p.is_file() and p not in seen:
                    out.append(p)
                    seen.add(p)
            except OSError:
                continue
        parent = cur.parent
        if parent == cur:
            break
        cur = parent
    return out


# 9 条 secret pattern 与 security_review/secrets.py 一致,用于 redact
# (复用 9 条 regex,避免 spec §5.4 / D7 漏掉)
_SECRET_RES: tuple[re.Pattern, ...] = (
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)aws_secret_access_key\s*=\s*[\"'][A-Za-z0-9/+=]{40}[\"']"),
    re.compile(r"ghp_[A-Za-z0-9]{36}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{82}"),
    re.compile(r"sk-ant-[A-Za-z0-9-_]{20,}"),
    re.compile(r"sk-[A-Za-z0-9-_]{20,}"),
    re.compile(r"-----BEGIN (RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]{20,}"),
    re.compile(r"(?i)(password|passwd|pwd)\s*=\s*[\"'][^\"'\s]{4,}[\"']"),
)


def _redact_secrets(text: str) -> str:
    """匹配 secret 模式 → <redacted:kind>。空内容/全 redact 后返空。"""
    out = text
    has_any = False
    for pat in _SECRET_RES:
        new = pat.sub("<redacted:secret>", out)
        if new != out:
            has_any = True
        out = new
    return out if (out.strip() or not has_any) else ""


def _read_text_safely(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def merge_claude_documents(files: list[Path], *,
                           global_paths: list[Path] = ()) -> str:
    """合并 [global_paths, ...files(子→父)] → <memory_context>...</...> 字符串。

    - 每文件 ≤ 20k(超截 + <truncated>)
    - 合计 ≤ 30k(超出截全局段,优先保项目段)
    - secret 模式 → <redacted:secret>
    - 无任何文件 / 全空 → ""(空态,不注入)
    """
    sections: list[str] = []
    # 全局段先(spec §5.2 顺序:全局 → 项目根子→父)
    for p in global_paths:
        body = _read_text_safely(p)
        if not body:
            continue
        body = _redact_secrets(body)
        if not body:
            continue
        sections.append(_format_section("global", p, body))
    # 项目段
    for p in files:
        body = _read_text_safely(p)
        if not body:
            continue
        body = _redact_secrets(body)
        if not body:
            continue
        sections.append(_format_section("project", p, body))
    if not sections:
        return ""
    inner = "\n\n".join(sections)
    if len(inner) > _TOTAL_LIMIT:
        # 截全局段(优先),保留项目段
        global_secs = [s for s in sections if s.startswith("[global:")]
        proj_secs = [s for s in sections if s.startswith("[project:")]
        inner = "\n\n".join(proj_secs)
        if len(inner) > _TOTAL_LIMIT:
            inner = inner[:_TOTAL_LIMIT] + "\n<truncated:total>"
        else:
            # 全局段超出 → 截总长度内的全局段
            budget = _TOTAL_LIMIT - len(inner) - 2
            for s in global_secs:
                if budget <= 0:
                    break
                snippet = s[:budget]
                inner += "\n\n" + snippet
                budget -= len(snippet) + 2
            inner += "\n<truncated:total>"
    return f"<memory_context>\n{inner}\n</memory_context>"


def _format_section(kind: str, path: Path, body: str) -> str:
    """单文件 → '[kind: relpath]\\n<body>'(截 20k)。"""
    if len(body) > _PER_FILE_LIMIT:
        body = body[:_PER_FILE_LIMIT] + "\n<truncated>"
    return f"[{kind}: {path.name}]\n{body}"


# ── /remember / /forget 入口(spec §6)────────────────────────────────────────
_PROJECT_KEYWORDS = ("项目", "本项目", "build", "test", "测试", "build_cmd", "verify")
_USER_KEYWORDS = ("我", "用户", "personally", "i prefer", "always", "习惯")


@dataclass(frozen=True, slots=True)
class RememberCmd:
    text: str
    scope: Scope
    key: str | None
    value: str
    confidence: float = 1.0
    type: Type = "preference"


@dataclass(frozen=True, slots=True)
class ForgetCmd:
    query: str
    kind: str  # "id" | "key" | "text"


def parse_remember(text: str) -> RememberCmd | None:
    """解析 /remember <text>。支持 --project scope 显式标注。

    - 缺省 scope:检测关键词 → project / user
    - 支持 `key: value` 格式提取 key
    """
    raw = text.strip()
    if not raw:
        return None
    scope: Scope = "user"
    key: str | None = None
    body = raw
    if raw.startswith("--project"):
        scope = "project"
        body = raw[len("--project"):].strip()
    elif raw.startswith("--user"):
        scope = "user"
        body = raw[len("--user"):].strip()
    if not body:
        return None
    # 提取 "key: value" 格式
    extracted_value: str | None = None
    if ":" in body and not body.startswith("http"):
        first, _, rest = body.partition(":")
        if first.strip() and " " not in first.strip():
            key = first.strip()
            extracted_value = rest.strip()
    if not body:
        return None
    # 自动判 project
    if scope == "user":
        lower = body.lower()
        if any(kw in body for kw in _PROJECT_KEYWORDS) or any(
            kw in lower for kw in _PROJECT_KEYWORDS
        ):
            scope = "project"
    return RememberCmd(
        text=body, scope=scope, key=key,
        value=extracted_value if extracted_value is not None else body,
    )


def parse_forget(text: str) -> ForgetCmd | None:
    """解析 /forget <id | key | text>。

    - id 格式:mem_* 前缀(长度不限)或 8-32 字符纯 hex
    - key 格式:含 _ 或 camelCase、无空格、长度 ≤ 64(典型 key 命名)
    - text:其他(走 value 子串匹配)
    """
    q = text.strip()
    if not q:
        return None
    if q.startswith("mem_"):
        return ForgetCmd(query=q, kind="id")
    # _new_id() produces 12 hex chars
    if 8 <= len(q) <= 32 and all(c in "0123456789abcdef" for c in q.lower()):
        return ForgetCmd(query=q, kind="id")
    # 含下划线 or camelCase → key
    if "_" in q or (any(c.isupper() for c in q[1:]) and q[0].isalpha()):
        if " " not in q and len(q) <= 64:
            return ForgetCmd(query=q, kind="key")
    return ForgetCmd(query=q, kind="text")


def _auto_key(value: str) -> str:
    """为 /remember 文本生成确定性 key(同文本 → 同 key → 24h dedup 命中)。"""
    h = hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]
    return f"remember.{h}"


def remember(text: str, *, scope: Scope | None = None,
             key: str | None = None, type: Type = "preference",
             evidence: tuple[str, ...] = ("user explicit /remember command",),
             project_id: str | None = None) -> MemoryEntry | None:
    """追加一条 user/project 记忆。scope 缺省:检测文本关键词自动判。

    24h 内同 (scope,key,value) 重复 → 返 None(spec D14 / §6.1)。
    """
    cmd = parse_remember(text)
    if cmd is None:
        return None
    final_scope: Scope = scope or cmd.scope
    final_key = key or cmd.key or _auto_key(cmd.value)
    final_value = cmd.value
    pid = project_id if final_scope == "project" else None
    path = _project_path(pid) if final_scope == "project" else _user_path()
    if _dedup(final_scope, final_key, final_value, path=path):
        return None
    now = time.time()
    entry = MemoryEntry(
        id=_new_id(),
        type=type,
        scope=final_scope,
        key=final_key,
        value=final_value,
        confidence=1.0,  # explicit = full conf(spec §6.1)
        evidence=evidence,
        ts=now,
        last_used_at=now,
        use_count=0,
        project_id=pid,
    )
    _append_jsonl(path, entry)
    return entry


def forget(query: str, *, project_id: str | None = None,
           session_id: str | None = None) -> list[MemoryEntry]:
    """按 id / key / text 软删(confidence=0)。返被软删的条目列表。"""
    cmd = parse_forget(query)
    if cmd is None:
        return []
    out: list[MemoryEntry] = []
    # 扫所有 tier
    for p in (_user_path(),
              _project_path(project_id) if project_id else None,
              _session_path(session_id) if session_id else None):
        if p is None:
            continue
        if not p.exists():
            continue
        entries = _read_jsonl(p)
        changed = False
        for e in entries:
            if _matches(e, cmd):
                soft = MemoryEntry(
                    id=e.id, type=e.type, scope=e.scope, key=e.key,
                    value=e.value, confidence=0.0, evidence=e.evidence,
                    ts=e.ts, last_used_at=e.last_used_at, use_count=e.use_count,
                    skill_name=e.skill_name, project_id=e.project_id,
                    session_id=e.session_id,
                )
                entries[entries.index(e)] = soft
                out.append(soft)
                changed = True
        if changed:
            _write_entries(p, entries)
    return out


def _matches(entry: MemoryEntry, cmd: ForgetCmd) -> bool:
    if cmd.kind == "id":
        return entry.id == cmd.query
    if cmd.kind == "key":
        return entry.key == cmd.query
    # text 子串
    return cmd.query in entry.value or cmd.query in entry.key


def _write_entries(path: Path, entries: list[MemoryEntry]) -> None:
    """原子写一份 entries → path(JSONL)。"""
    with _write_lock:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            with tmp.open("w", encoding="utf-8") as fh:
                for e in entries:
                    d = asdict(e)
                    d["evidence"] = list(e.evidence)
                    fh.write(json.dumps(d, ensure_ascii=False) + "\n")
            tmp.replace(path)
        except OSError:
            pass


# ── /memory 视图 ─────────────────────────────────────────────────────────────
def view_all(*, project_id: str | None = None,
             session_id: str | None = None,
             limit_per_tier: int = 20) -> str:
    """拼 4 tier 摘要 → markdown list 字符串,空 tier 标 (空)。"""
    lines: list[str] = []
    user = load(scope="user", limit=limit_per_tier)
    lines.append(f"[User memories] ({len(user)})")
    if user:
        for e in user:
            lines.append(
                f"  - {e.type}: {e.key} = {e.value} (conf={e.confidence:.2f}, used {e.use_count}x)"
            )
    else:
        lines.append(t("mem.empty"))
    if project_id:
        proj = load(scope="project", project_id=project_id, limit=limit_per_tier)
        lines.append("")
        lines.append(f"[Project memories] ({len(proj)})")
        if proj:
            for e in proj:
                lines.append(
                    f"  - {e.type}: {e.key} = {e.value} (conf={e.confidence:.2f}, used {e.use_count}x)"
                )
        else:
            lines.append(t("mem.empty"))
    if session_id:
        sess = load(scope="session", session_id=session_id, limit=limit_per_tier)
        lines.append("")
        lines.append(f"[Session memories] ({len(sess)})")
        if sess:
            for e in sess:
                lines.append(
                    f"  - {e.type}: {e.key} = {e.value} (conf={e.confidence:.2f}, used {e.use_count}x)"
                )
        else:
            lines.append(t("mem.empty"))
    skill = load(scope="skill", limit=limit_per_tier)
    lines.append("")
    lines.append(f"[Skill memories] ({len(skill)})")
    if skill:
        for e in skill:
            lines.append(
                f"  - {e.type}: {e.key} = {e.value} (conf={e.confidence:.2f}, used {e.use_count}x)"
            )
    else:
        lines.append(t("mem.empty"))
    return "\n".join(lines)


# ── auto-capture 触发点(spec §7)──────────────────────────────────────────────
_TYPE_MAP = {
    "escalation_decision": "decision",
    "verify_fail": "failure",
    "tool_repeat_fail": "failure",
    "run_success": "fact",
    "undo": "convention",
    "task_reflection": "failure",
}
_DEFAULT_CONFIDENCE = {
    "escalation_decision": 0.9,
    "verify_fail": 0.8,
    "tool_repeat_fail": 0.7,
    "run_success": 0.6,
    "undo": 0.7,
    "task_reflection": 0.7,
}
_SCOPE_MAP = {
    "escalation_decision": "project",
    "verify_fail": "project",
    "tool_repeat_fail": "skill",  # spec §7.1
    "run_success": "project",
    "undo": "project",
    "task_reflection": "project",
}
_tool_fail_count: dict[tuple[str | None, str], int] = {}


def _tool_fail_counter_key(project_id: str | None, tool: str) -> tuple[str | None, str]:
    return (project_id, tool)


def _tool_fail_count_increment(project_id: str | None, tool: str) -> int:
    """返回递增后的计数(同 (project, tool) 累加)。"""
    k = _tool_fail_counter_key(project_id, tool)
    _tool_fail_count[k] = _tool_fail_count.get(k, 0) + 1
    return _tool_fail_count[k]


def _reset_tool_fail_counter(project_id: str | None, tool: str) -> None:
    """成功一次 → 计数清零(避免下次的真 fail 因累计的旧 fail 误触 3 次)。"""
    _tool_fail_count.pop(_tool_fail_counter_key(project_id, tool), None)


def capture_event(kind: str, *, project_id: str | None = None,
                  session_id: str | None = None,
                  **payload) -> MemoryEntry | None:
    """单入口:kind ∈ {escalation_decision, verify_fail, tool_repeat_fail,
    run_success, undo, task_reflection}。未知 kind 返 None。

    spec §7.1 表:
    - escalation_decision: scope=project, conf=0.9
    - verify_fail: scope=project, conf=0.8
    - tool_repeat_fail: scope=skill, conf=0.7(同 tool 累计 ≥3 次才写)
    - run_success: scope=project, conf=0.6(goal + 关键命令,steps ≥ 5)
    - undo: scope=project, conf=0.7
    - task_reflection: scope=project, conf=0.7
    """
    if kind not in _TYPE_MAP:
        return None
    if kind == "tool_repeat_fail":
        tool = payload.get("tool", "")
        if not tool:
            return None
        cnt = _tool_fail_count_increment(project_id, tool)
        if cnt < 3:
            return None
        # 触发后清零(下一次再计数)
        _reset_tool_fail_counter(project_id, tool)
    if kind == "run_success":
        steps = int(payload.get("steps", 0))
        if steps < 5:
            return None
    scope = _SCOPE_MAP[kind]
    mem_type = _TYPE_MAP[kind]
    conf = _DEFAULT_CONFIDENCE[kind]
    # 构造 value + key
    if kind == "escalation_decision":
        reply = payload.get("user_reply", "")
        reason = payload.get("reason", "")
        value = f"escalation → {reply} ({reason})".strip(" ()")
        key = f"escalation.{reason or 'unknown'}"
    elif kind == "verify_fail":
        cmd = payload.get("cmd", "")
        snippet = payload.get("stderr_snippet", "")
        h = payload.get("stderr_hash", "")
        value = f"{cmd} → {snippet[:200]}" + (f" [{h[:8]}]" if h else "")
        key = f"verify_fail.{cmd[:40]}"
    elif kind == "tool_repeat_fail":
        tool = payload.get("tool", "")
        err = payload.get("error", "")[:120]
        value = f"{tool} 3x fail: {err}"
        key = f"tool_fail.{tool}"
    elif kind == "run_success":
        goal = payload.get("goal", "")
        kcmd = payload.get("key_cmd", "")
        value = f"{goal} (key_cmd={kcmd})"
        key = f"run_success.{kcmd[:40]}"
    elif kind == "undo":
        reason = payload.get("reason", "(no reason given)")
        value = f"undo: {reason}"
        key = f"undo.{reason[:40]}"
    elif kind == "task_reflection":
        run_id = payload.get("run_id", "")
        goal = payload.get("goal", "")
        verdict = payload.get("verdict", "")
        snippet = payload.get("last_exc_snippet") or ""
        tag = " [self_verified]" if payload.get("self_verified") else ""
        value = f"reflection({verdict}{tag}): {goal}" + (f" — {snippet[:160]}" if snippet else "")
        key = f"reflection.{run_id[:12]}"
    else:
        return None
    # secret redact
    value = _redact_secrets(value)
    if not value.strip():
        return None
    # 路径 + 24h dedup
    if scope == "user":
        path = _user_path()
        eid_extra = None
    elif scope == "project":
        pid = project_id or project_id_for()
        path = _project_path(pid)
        eid_extra = pid
    elif scope == "skill":
        # 走 user tier,evidence 标 skill;真正的 per-skill 是 v1.1
        path = _user_path()
        eid_extra = None
    else:  # session
        sid = session_id or uuid.uuid4().hex
        path = _session_path(sid)
        eid_extra = sid
    if _dedup(scope, key, value, path=path):
        return None
    now = time.time()
    entry = MemoryEntry(
        id=_new_id(),
        type=mem_type,
        scope=scope,
        key=key,
        value=value,
        confidence=conf,
        evidence=(f"auto-capture:{kind}",),
        ts=now,
        last_used_at=now,
        use_count=0,
        project_id=eid_extra if scope == "project" else None,
        session_id=eid_extra if scope == "session" else None,
        skill_name=tool if scope == "skill" and kind == "tool_repeat_fail" else None,
    )
    _append_jsonl(path, entry)
    return entry


# ── 系统提示 <memory_context> 段注入(spec §5.3 / T6)─────────────────────────
def _format_recalled(entries: list[MemoryEntry]) -> list[str]:
    """top N 记忆 → 1 行/条。"""
    out: list[str] = []
    for e in entries:
        out.append(
            f"  - {e.type}: {e.key} = {e.value} (conf={e.confidence:.2f}, used {e.use_count}x)"
        )
    return out


def _memory_context_block(*, workspace: Path,
                          project_id: str,
                          session_id: str | None = None) -> str:
    """构造注入到系统提示的 <memory_context> 段。

    段顺序:docs(全局 + 项目根)→ [Recalled memories](top 50/50/20/20)
    空态(无 CLAUDE.md 且无记忆 / ARGOS_NO_MEMORY=1)→ ""(不注入)
    """
    if os.environ.get("ARGOS_NO_MEMORY") == "1":
        return ""
    files = walk_claude_md_files(workspace)
    global_paths = [gp for gp in (_global_claude(), _global_agents()) if gp.exists()]
    docs = merge_claude_documents(files, global_paths=global_paths)
    user_mems = load(scope="user", limit=50)
    proj_mems = load(scope="project", project_id=project_id, limit=50)
    skill_mems = load(scope="skill", limit=20)
    sess_mems: list[MemoryEntry] = []
    if session_id:
        sess_mems = load(scope="session", session_id=session_id, limit=20)
    recalled = _format_recalled(user_mems + proj_mems + skill_mems + sess_mems)
    if not docs and not recalled:
        return ""
    parts: list[str] = ["<memory_context>"]
    if docs:
        parts.append(docs)
    if recalled:
        parts.append("[Recalled memories]")
        parts.extend(recalled)
    parts.append("</memory_context>")
    return "\n".join(parts)


# ── decay / prune / 容量 cap(spec §9)────────────────────────────────────────
def decayed_confidence(conf: float, days: float) -> float:
    """公式核:confidence 衰减后值(spec §9.1)。

    公式:conf - 0.01 * days,clamp 下限 0.0。
    单一来源——所有调用方(含 consolidate)必须委托此函数,禁止手写第二份。
    """
    return max(0.0, conf - 0.01 * days)


def _decay_confidence(entry: MemoryEntry, *, now: float | None = None) -> MemoryEntry:
    """单条 decay:confidence -= 0.01 * days_since_last_used(spec §9.1)。"""
    t = now if now is not None else time.time()
    days = max(0.0, (t - entry.last_used_at) / 86400.0)
    new_conf = decayed_confidence(entry.confidence, days)
    return MemoryEntry(
        id=entry.id, type=entry.type, scope=entry.scope,
        key=entry.key, value=entry.value, confidence=new_conf,
        evidence=entry.evidence, ts=entry.ts,
        last_used_at=entry.last_used_at, use_count=entry.use_count,
        skill_name=entry.skill_name, project_id=entry.project_id,
        session_id=entry.session_id,
    )


def decay_pass() -> int:
    """扫所有 tier 物理写回 decay 后的 JSONL。返更新条目数。"""
    n = 0
    for path in _all_tier_paths():
        if not path.exists():
            continue
        entries = _read_jsonl(path)
        changed = False
        out: list[MemoryEntry] = []
        for e in entries:
            new = _decay_confidence(e)
            if new.confidence != e.confidence:
                changed = True
                n += 1
            out.append(new)
        if changed:
            _write_entries(path, out)
    return n


def _all_tier_paths() -> list[Path]:
    """扫所有现存 tier JSONL 路径。"""
    paths: list[Path] = []
    root = _root()
    for sub in ("", "projects", "skills", "sessions"):
        base = root / sub if sub else root
        if not base.exists():
            continue
        for f in base.glob("*.jsonl"):
            paths.append(f)
    return paths


def prune(scope: Scope | None = None, *, project_id: str | None = None,
          skill_name: str | None = None, session_id: str | None = None) -> int:
    """物理删 confidence==0 条目 + 触发 cap。返删除数。"""
    n = 0
    paths: list[Path] = []
    if scope is None or scope == "user":
        paths.append(_user_path())
    if scope is None or scope == "project" and project_id:
        if project_id:
            paths.append(_project_path(project_id))
    if scope is None or scope == "skill" and skill_name:
        if skill_name:
            paths.append(_skill_path(skill_name))
    if scope is None or scope == "session" and session_id:
        if session_id:
            paths.append(_session_path(session_id))
    for p in paths:
        if not p.exists():
            continue
        entries = _read_jsonl(p)
        kept = [e for e in entries if e.confidence > 0.0]
        n += len(entries) - len(kept)
        if kept:
            _write_entries(p, kept)
        else:
            # 全空 → 删文件
            try:
                p.unlink()
            except OSError:
                pass
    return n


def _cap_bytes_for_scope(scope: Scope) -> int:
    """spec §9.3 cap 默认值。"""
    env = os.environ.get("ARGOS_MEMORY_CAP_MB")
    if env:
        try:
            mb = int(env)
            return mb * 1024 * 1024
        except ValueError:
            pass
    return {
        "user": 2 * 1024 * 1024,
        "project": 5 * 1024 * 1024,
        "skill": 1 * 1024 * 1024,
        "session": 1 * 1024 * 1024,
    }.get(scope, 2 * 1024 * 1024)


def _enforce_cap(path: Path, max_bytes: int | None = None) -> int:
    """超 cap 按 last_used_at 升序删。返删条数。"""
    if not path.exists():
        return 0
    # 推 scope
    scope: Scope = "user"
    if path.parent.name == "projects":
        scope = "project"
    elif path.parent.name == "skills":
        scope = "skill"
    elif path.parent.name == "sessions":
        scope = "session"
    cap = max_bytes if max_bytes is not None else _cap_bytes_for_scope(scope)
    try:
        size = path.stat().st_size
    except OSError:
        return 0
    if size <= cap:
        return 0
    entries = sorted(_read_jsonl(path), key=lambda e: e.last_used_at)  # 旧→新
    while size > cap and entries:
        entries.pop(0)
        # 估算新 size:把 entries 写一遍再 stat
        _write_entries(path, entries)
        try:
            size = path.stat().st_size
        except OSError:
            break
    if not entries:
        try:
            path.unlink()
        except OSError:
            pass
    return 0  # 删条数需要前后比,这里简化


def purge_old_sessions(*, max_age_days: int = 30) -> int:
    """session tier:超过 max_age_days 没碰的 JSONL 文件整文件删。"""
    n = 0
    sess_dir = _root() / "sessions"
    if not sess_dir.exists():
        return 0
    cutoff = time.time() - max_age_days * 86400
    for f in sess_dir.glob("*.jsonl"):
        try:
            entries = _read_jsonl(f)
        except (OSError, json.JSONDecodeError):
            continue
        if not entries:
            try:
                f.unlink()
                n += 1
            except OSError:
                pass
            continue
        # 取该文件最新 last_used_at
        latest = max(e.last_used_at for e in entries)
        if latest < cutoff:
            try:
                f.unlink()
                n += 1
            except OSError:
                pass
    return n
