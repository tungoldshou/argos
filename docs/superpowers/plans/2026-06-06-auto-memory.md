# Auto Memory + CLAUDE.md 自动加载 — 实施计划

> Road-map #9 / spec `2026-06-06-auto-memory-design.md` 的 TDD 实施计划。
> 9 任务,1 任务 = 1 commit,合计 +44 测试,**0 新外部依赖**(stdlib only)。

## 0. 总览

| 任务 | 标题 | 估测 | 关键文件 | 测试文件 |
|---|---|---|---|---|
| T1 | memory/ 模块骨架 + 4 tier + JSONL persistence | 30 min | `argos_agent/memory/auto.py`(新) | `test_memory_tiers.py` |
| T2 | Memory loader + recency × confidence ranking | 25 min | `argos_agent/memory/auto.py` | `test_memory_ranking.py` |
| T3 | CLAUDE.md auto-walk + 合并 | 25 min | `argos_agent/memory/auto.py` | `test_claude_md_walker.py` |
| T4 | `/remember` / `/forget` slash 命令 | 30 min | `tui/commands.py` + `tui/app.py` | `test_memory_commands.py` |
| T5 | Auto-capture 触发点 | 35 min | `core/loop.py` + `core/harness.py` 接 | `test_memory_capture.py` |
| T6 | 系统提示 `<memory_context>` 注入 | 20 min | `core/loop.py` `_build_system` | `test_memory_injection.py` |
| T7 | Decay / prune / 容量 cap | 20 min | `memory/auto.py` | `test_memory_tiers.py` + `test_memory_ranking.py` 加测 |
| T8 | TUI `/memory` 视图命令 | 25 min | `tui/commands.py` + `tui/app.py` | `test_memory_commands.py` 加测 |
| T9 | 文档 + CHANGELOG + 验收 | 20 min | `docs/` + `CHANGELOG.md` | 端到端铁证 |

## 1. 任务 T1:memory/ 模块骨架 + 4 tier + JSONL persistence

### 1.1 目标
- 新文件 `argos_agent/memory/auto.py`(不污染现有 `memory/__init__.py` 任务历史)
- 单一 `MemoryEntry` dataclass(scope 字段 Literal 区分)
- 4 个路径解析函数 + `_read_jsonl` / `_append_jsonl`
- 不引入 sqlite / 任何新依赖

### 1.2 实现细节

```python
# argos_agent/memory/auto.py
from dataclasses import dataclass, asdict
from typing import Literal
import json, threading, uuid, time
from pathlib import Path

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

# 路径(全部 ~/.argos/memory/... 可被 ARGOS_MEMORY_DIR 覆盖)
def _root() -> Path: ...
def _user_path() -> Path: ...
def _project_path(project_id: str) -> Path: ...
def _skill_path(skill_name: str) -> Path: ...
def _session_path(session_id: str) -> Path: ...

# 读写
def _read_jsonl(path: Path) -> list[MemoryEntry]: ...
def _append_jsonl(path: Path, entry: MemoryEntry) -> None: ...
def project_id_for(cwd: Path | None = None) -> str: ...   # sha1(repo_root 或 cwd)
```

### 1.3 RED 测试
```python
# tests/test_memory_tiers.py
def test_user_tier_path_resolves_under_argos_home(monkeypatch, tmp_path)
def test_project_tier_path_includes_hash(monkeypatch, tmp_path)
def test_skill_tier_path_per_skill(monkeypatch, tmp_path)
def test_session_tier_path_per_session(monkeypatch, tmp_path)
def test_memory_entry_dataclass_is_frozen()
def test_read_jsonl_missing_file_returns_empty(tmp_path)
def test_read_jsonl_skips_corrupt_lines(tmp_path)
def test_append_then_read_roundtrip(tmp_path)
```

### 1.4 GREEN:写 minimal impl 全部通过

### 1.5 验证
```bash
rtk pytest tests/test_memory_tiers.py -v
```
期望 8 全绿

### 1.6 Commit
```
feat(memory): #9 T1 memory/auto.py 骨架 + 4 tier + JSONL persistence
```

## 2. 任务 T2:Memory loader + recency × confidence ranking

### 2.1 目标
- `load(scope, *, project_id=None, skill_name=None, session_id=None, limit=50) -> list[MemoryEntry]`
- ranking:`score = exp(-0.01 * days_since_last_used) * confidence`
- type 优先级:`failure > decision > convention > preference > fact`
- 过滤 `confidence < 0.3` 不入 ranking

### 2.2 实现
```python
def load(*, scope: Scope | None = None, project_id: str | None = None,
         skill_name: str | None = None, session_id: str | None = None,
         limit: int = 50) -> list[MemoryEntry]:
    """读 4 tier 全部,合并后按 recency×conf 排序,top N。

    scope 指定时只读该 tier;否则读全部。
    """

_TYPE_PRIORITY = {"failure": 5, "decision": 4, "convention": 3,
                  "preference": 2, "fact": 1}

def _score(entry: MemoryEntry) -> float:
    days = (time.time() - entry.last_used_at) / 86400.0
    recency = math.exp(-0.01 * days)
    return recency * entry.confidence

def _rank(entries: list[MemoryEntry], limit: int) -> list[MemoryEntry]:
    eligible = [e for e in entries if e.confidence >= 0.3]
    eligible.sort(key=lambda e: (_TYPE_PRIORITY.get(e.type, 0), _score(e)), reverse=True)
    return eligible[:limit]
```

### 2.3 RED 测试
```python
# tests/test_memory_ranking.py
def test_load_returns_recent_first(tmp_path, monkeypatch)
def test_score_decays_with_age(tmp_path, monkeypatch)  # 改 last_used_at 看分变
def test_confidence_below_threshold_excluded(tmp_path, monkeypatch)
def test_failure_type_outranks_fact(tmp_path, monkeypatch)
def test_load_filters_by_scope(tmp_path, monkeypatch)
def test_limit_truncates(tmp_path, monkeypatch)
def test_use_count_boost_confidence(tmp_path, monkeypatch)  # 单独函数 touch_entry
```

### 2.4 GREEN

### 2.5 Commit
```
feat(memory): #9 T2 loader + recency × confidence ranking
```

## 3. 任务 T3:CLAUDE.md auto-walk + 合并

### 3.1 目标
- `walk_claude_md_files(start: Path) -> list[Path]`:从 start 向上,找 CLAUDE.md / AGENTS.md
- `merge_claude_documents(paths: list[Path], *, global_path: Path | None = None) -> str`:
  合并内容,加 `<memory_context>` 包裹,secret pattern 标 `<redacted:secret>`,截断 20k
- 注入预算 ≤ 30k 字符,超出截最低优先级(本期:截全局段)

### 3.2 实现
```python
# 用 pathlib 向上走
def walk_claude_md_files(start: Path) -> list[Path]:
    """从 start 向上,到 / 停;遇 CLAUDE.md 或 AGENTS.md 收集。
    返回 [最近, ..., 最远] 顺序(子→父)。
    """
    out: list[Path] = []
    seen: set[Path] = set()
    cur = start.resolve()
    while True:
        for name in ("CLAUDE.md", "AGENTS.md"):
            p = cur / name
            if p.is_file() and p not in seen:
                out.append(p)
                seen.add(p)
        parent = cur.parent
        if parent == cur:
            break
        cur = parent
    return out

_SECRET_RE = [re.compile(...) for ...]  # 复用 security_review 9 regex

def _redact(text: str) -> str: ...

def merge_claude_documents(files: list[Path], *, global_paths: list[Path] = ()) -> str:
    """合并 [global_paths, ...files(子→父)] → <memory_context>...</...> 字符串。
    每文件 ≤ 20k,合计 ≤ 30k;超出截全局段。
    无任何文件 → ""(空态,不注入)。
    """
```

### 3.3 RED 测试
```python
# tests/test_claude_md_walker.py
def test_walk_finds_own_dir(tmp_path, monkeypatch)
def test_walk_finds_parent_chain(tmp_path, monkeypatch)  # 创建 2 层目录
def test_walk_finds_both_claude_and_agents(tmp_path, monkeypatch)
def test_walk_stops_at_filesystem_root(tmp_path, monkeypatch)
def test_walk_skips_nonexistent(tmp_path, monkeypatch)
def test_merge_returns_empty_when_no_files(tmp_path, monkeypatch)
def test_merge_truncates_per_file_to_20k(tmp_path, monkeypatch)
def test_merge_redacts_secrets_in_content(tmp_path, monkeypatch)
def test_merge_wraps_in_memory_context_tag(tmp_path, monkeypatch)
```

### 3.4 GREEN

### 3.5 Commit
```
feat(memory): #9 T3 CLAUDE.md / AGENTS.md auto-walk + 合并 + secret redact
```

## 4. 任务 T4:`/remember` / `/forget` slash 命令

### 4.1 目标
- 解析 `/remember <text>` → `MemoryEntry(scope="user"|"project", confidence=1.0, ...)`
- 解析 `/forget <id|key|text>` → 软删(confidence=0)
- 解析 `/memory` → 单独 command(name="memory",no arg,看 T8 渲染)
- 在 `tui/commands.py` `COMMAND_HELP` **不增**(避免 18→19 列表过宽;
  `/memory` 是 meta 操作,slash menu 不列,但 parse_slash 仍能解析)
- TUI `app.py` `_dispatch_slash` 加 3 个分支

### 4.2 实现
```python
# tui/commands.py
def parse_remember(text: str) -> RememberCmd | None: ...
def parse_forget(text: str) -> ForgetCmd | None: ...

# argos_agent/memory/auto.py
def remember(text: str, *, scope: Scope | None = None,
             key: str | None = None, type: Type = "preference",
             evidence: tuple[str, ...] = ("user explicit /remember command",),
             project_id: str | None = None) -> MemoryEntry:
    """追加一条 user/project 记忆。scope 缺省:检测文本关键词自动判(项目/build/test → project)。"""

def forget(query: str, *, project_id: str | None = None,
           session_id: str | None = None) -> list[MemoryEntry]:
    """按 id / key / text 软删。返被软删条目列表(空 → 没找到)。"""
```

### 4.3 RED 测试
```python
# tests/test_memory_commands.py
def test_parse_remember_text_only()
def test_parse_remember_with_scope_key()
def test_parse_remember_empty_returns_none()
def test_remember_writes_to_user_tier(tmp_path, monkeypatch)
def test_remember_detects_project_keyword(tmp_path, monkeypatch)
def test_forget_by_id(tmp_path, monkeypatch)
def test_forget_by_key_fuzzy(tmp_path, monkeypatch)
```

### 4.4 GREEN

### 4.5 Commit
```
feat(tui): #9 T4 /remember + /forget slash 命令 + 记忆写入接口
```

## 5. 任务 T5:Auto-capture 触发点

### 5.1 目标
- 5 个事件触发点,在 `core/loop.py` 和 `core/harness.py` 已有的事件 emit 处旁路挂上
- 全部走单一入口 `memory.auto.capture_event(event_kind, **payload) -> None`
- 24h 同 (scope,key,value) 去重
- secret redaction 前置

### 5.2 触发点(挂载位置)

| 事件 | 挂载位置 | 捕获什么 |
|---|---|---|
| Escalation 决策 | `core/loop.py` Escalation event 旁 | 用户回复 + reason(若有) |
| Verify failed | `core/loop.py` VerifyVerdict 旁 (status=failed) | 失败命令 + 错误 hash+200 字 |
| 重复 tool fail | `core/loop.py` tool 错误收集器(新加 `_tool_fail_count` dict) | 失败 tool + 错误模式 |
| Run 成功且 ≥5 步 | `core/loop.py` run 结束(verdict=passed) | goal + 关键命令(从 verify_cmd 取) |
| `/undo` | TUI `app.py` | 撤销原因(若有) |

### 5.3 实现
```python
# argos_agent/memory/auto.py
def capture_event(kind: str, *, project_id: str | None = None,
                  session_id: str | None = None,
                  **payload) -> MemoryEntry | None:
    """单入口:kind ∈ {escalation_decision, verify_fail, tool_repeat_fail,
    run_success, undo}. 返回写入的 entry(去重命中或 redact 失败返 None)。
    """

_TYPE_MAP = {
    "escalation_decision": "decision",
    "verify_fail": "failure",
    "tool_repeat_fail": "failure",
    "run_success": "fact",
    "undo": "convention",
}
_DEFAULT_CONFIDENCE = {
    "escalation_decision": 0.9,
    "verify_fail": 0.8,
    "tool_repeat_fail": 0.7,
    "run_success": 0.6,
    "undo": 0.7,
}

def _dedup(scope: Scope, key: str, value: str, *, hours: int = 24) -> bool:
    """24h 内同 (scope,key,value) 已有 → True(应跳过)。"""
```

### 5.4 RED 测试
```python
# tests/test_memory_capture.py
def test_capture_escalation_decision_writes_to_project(tmp_path, monkeypatch)
def test_capture_verify_fail_includes_cmd(tmp_path, monkeypatch)
def test_capture_tool_repeat_fail_requires_3(tmp_path, monkeypatch)
def test_capture_run_success_writes_only_over_5_steps(tmp_path, monkeypatch)
def test_capture_undo(tmp_path, monkeypatch)
def test_capture_redacts_secrets_before_write(tmp_path, monkeypatch)
def test_capture_dedups_24h_same_key_value(tmp_path, monkeypatch)
def test_capture_updates_value_when_changed(tmp_path, monkeypatch)
def test_capture_returns_none_when_redacted_to_empty(tmp_path, monkeypatch)
```

### 5.5 GREEN

### 5.6 Commit
```
feat(core): #9 T5 auto-capture escalation/verify_fail/repeat_fail/run_success/undo
```

## 6. 任务 T6:系统提示 `<memory_context>` 注入

### 6.1 目标
- `core/loop.py` `_build_system` 在 `_env_context` 之后、`_tool_signatures_block` 之前
  插入 `_memory_context_block(workspace, project_id) -> str`
- 段格式:
  ```
  <memory_context>
  [Project: <name>]
  ...CLAUDE.md / AGENTS.md merged...

  [Recalled memories]
  - <type>: <key> = <value> (conf=0.95, used 3x)
  ...
  </memory_context>
  ```
- `ARGOS_NO_MEMORY=1` → 返 ""
- 加载 4 tier 默认 top 50/50/20/20 = 140

### 6.2 实现
```python
# argos_agent/memory/auto.py
def _memory_context_block(*, workspace: Path, project_id: str,
                         session_id: str | None = None) -> str:
    """构造注入到系统提示的 <memory_context> 段。
    空态(无 CLAUDE.md 且无记忆)→ ""。
    """
    if os.environ.get("ARGOS_NO_MEMORY") == "1":
        return ""
    files = walk_claude_md_files(workspace)
    global_paths = [_global_claude(), _global_agents()]  # ~/.argos/CLAUDE.md & AGENTS.md
    docs = merge_claude_documents(files, global_paths=global_paths)
    user_mems = load(scope="user", limit=50)
    proj_mems = load(scope="project", project_id=project_id, limit=50)
    skill_mems = load(scope="skill", limit=20)
    sess_mems = load(scope="session", session_id=session_id, limit=20) if session_id else []
    recalled = _format_recalled(user_mems + proj_mems + skill_mems + sess_mems)
    if not docs and not recalled:
        return ""
    parts = ["<memory_context>"]
    if docs:
        parts.append(docs)
    if recalled:
        parts.append("[Recalled memories]")
        parts.extend(recalled)
    parts.append("</memory_context>")
    return "\n".join(parts)
```

### 6.3 RED 测试
```python
# tests/test_memory_injection.py
def test_block_returns_empty_when_no_files_no_mems(tmp_path, monkeypatch)
def test_block_includes_claude_md_content(tmp_path, monkeypatch)
def test_block_includes_recalled_memories(tmp_path, monkeypatch)
def test_block_honors_no_memory_env(tmp_path, monkeypatch)
def test_block_is_injected_in_build_system(tmp_path, monkeypatch)  # 集成:用现有 _build_system
```

### 6.4 GREEN

### 6.5 Commit
```
feat(core): #9 T6 系统提示 <memory_context> 段注入 (_build_system)
```

## 7. 任务 T7:Decay / prune / 容量 cap

### 7.1 目标
- `decay_pass()`:全 4 tier 扫一遍,`confidence -= 0.01 * days_since_last_used`
  (物理改写文件,不是 in-memory)
- `prune()`:物理删 `confidence == 0` 的 + 触发容量 cap
- `touch(entry)`:被注入后调,`use_count += 1`,`confidence += 0.02`,`last_used_at = now`
- cap 触发策略:写前检查 → 超 → 按 `last_used_at` 升序删到 < cap

### 7.2 实现
```python
def decay_pass() -> int:
    """扫所有 tier,应用 decay;返更新条目数。"""

def prune(scope: Scope | None = None, *, project_id: str | None = None,
          skill_name: str | None = None, session_id: str | None = None) -> int:
    """物理删 confidence==0 条目 + 触发 cap;返删除数。"""

def touch(entry: MemoryEntry) -> None:
    """更新 use_count / confidence / last_used_at,原地改写 JSONL。"""

def _enforce_cap(path: Path, max_bytes: int) -> int:
    """超 cap 按 last_used_at 升序删;返删条数。"""
```

### 7.3 RED 测试(增到 test_memory_tiers / test_memory_ranking)
```python
def test_decay_reduces_confidence_for_old_entries(tmp_path, monkeypatch)
def test_decay_does_not_apply_to_recently_used(tmp_path, monkeypatch)
def test_touch_boosts_confidence_and_increments_use_count(tmp_path, monkeypatch)
def test_prune_removes_zero_confidence(tmp_path, monkeypatch)
def test_cap_enforced_on_write(tmp_path, monkeypatch)
def test_session_tier_purged_after_30_days(tmp_path, monkeypatch)
```

### 7.4 GREEN

### 7.5 Commit
```
feat(memory): #9 T7 decay + prune + 容量 cap
```

## 8. 任务 T8:TUI `/memory` 视图命令

### 8.1 目标
- `app.py` `_dispatch_slash` 加 `cmd.name == "memory"` 分支
- 调 `memory.auto.view_all()` 拿 4 tier 摘要 → 推 `ActivityPanel` "Memory" 段
- `/memory` 不进 `COMMAND_HELP`(`parse_slash` 仍识别为 known)
- 真实渲染用 `Transcript` widget append 一段 markdown 风格 list

### 8.2 实现
```python
# argos_agent/memory/auto.py
def view_all(*, project_id: str | None = None,
             session_id: str | None = None,
             limit_per_tier: int = 20) -> str:
    """拼 4 tier 摘要 → markdown list 字符串,空 tier 标 "(空)"。"""
    return f"""
[Project memories] ({len(proj)})
- failure: build_cmd = pytest -q (conf=0.95, used 3x)
...

[User memories] ({len(user)})
- preference: indent_style = tabs (conf=1.0, used 7x)
...
""".strip()

# tui/app.py _dispatch_slash
elif cmd.name == "memory":
    from argos_agent.memory import auto
    text = auto.view_all(...)
    # 推 transcript(模拟现有 add_transcript_line)
```

### 8.3 RED 测试
```python
# tests/test_memory_commands.py (新增)
def test_view_all_lists_all_tiers(tmp_path, monkeypatch)
def test_view_all_marks_empty_tier(tmp_path, monkeypatch)
def test_memory_command_renders_to_transcript(tmp_path, monkeypatch)
def test_memory_command_not_in_command_help()
def test_memory_command_known_in_parse_slash()
```

### 8.4 GREEN

### 8.5 Commit
```
feat(tui): #9 T8 /memory 视图命令(只读 4 tier 列表)
```

## 9. 任务 T9:文档 + CHANGELOG + 验收

### 9.1 目标
- `CHANGELOG.md` `[Unreleased]` 增 1 段
- `docs/auto-memory.md` 用户文档(简明,例子为主)
- README 命令清单更新(若 `/memory`/`/remember`/`/forget` 涉及)
- 跑全 pytest,确认 +44 测试绿
- 端到端铁证:写 tmp CLAUDE.md → 模拟 session start → `_build_system` 输出含
  `<memory_context>` 段 + 文本

### 9.2 实现
- 文档照 `docs/skills.md` 风格(若有)或新写,300-500 行
- 端到端铁证:`tests/test_memory_e2e.py`(1 个集成测试)或并入
  `test_memory_injection.py`

### 9.3 验收
- [ ] `rtk pytest tests/ -q` 全绿,测试数 1154 → ~1198
- [ ] `rtk pytest tests/test_memory*.py tests/test_claude_md_walker.py -v` 全绿
- [ ] tmp CLAUDE.md → system prompt 含 → 截屏(或 Transcript 截图)留底
- [ ] CHANGELOG 段已加
- [ ] git log 含 9 个新 commit

### 9.4 Commit
```
docs: #9 T9 auto-memory 文档 + CHANGELOG + 验收铁证
```

## 10. 风险与回退

- 任何任务失败(测试不绿、loop 集成炸)→ **该任务 commit revert**,不进 T+1
- 护栏:`_build_system` 改动若让现有 loop 集成测试回归 → 立即 revert T6
- 不在 spec/plan 允许范围外的文件(除 `tui/commands.py` `tui/app.py` `core/loop.py`
  `core/harness.py` 接捕获)做任何改动

## 11. 时间线与并行

- 9 任务串行(每任务内部全 TDD 闭环)
- T7 的 decay 写物理文件与 T1-T6 的 append-only 兼容,无冲突
- T8 改 `tui/commands.py` 解析 `/memory` 但不进 COMMAND_HELP,需新增一处解析旁路
- 全部完成后,跑全量 pytest 一次

## 12. 完成判据

- [ ] 9 commit 全推本地(不 push remote)
- [ ] 测试数 1154 → 1198+(+44,含 1 e2e)
- [ ] CHANGELOG Unreleased 含 #9 段
- [ ] `docs/auto-memory.md` 用户文档存在
- [ ] 端到端铁证 1 份(test 输出)
- [ ] `_build_system` 输出含 `<memory_context>` 段(在 unittest 中断言)
