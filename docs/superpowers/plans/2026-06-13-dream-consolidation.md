# Dream 夜间整合 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 Argos 加验证门控的夜间自进化：跨 run 综合蒸馏泛化 skill + 记忆整理，并顺带修通生产路径上学习闭环的两处断电（候选丢弃、反思丢弃）。

**Architecture:** host 侧管道（daemon 进程内，`learning/dream.py`），不是 agent run。Conductor 夜间 builtin order 产 ProactiveSuggestion（恒需确认）→ confirm 按 `action="dream"` 路由到 DreamPipeline：聚类 → 综合（模型只写叙述层，可执行内容逐字来自已验证材料）→ `promotion_gate` A/B 晋升 → 记忆整理 → 报告。

**Tech Stack:** Python 3.12 / dataclasses / asyncio / pytest。零新第三方依赖。

**Spec:** `docs/superpowers/specs/2026-06-13-dream-consolidation-design.md`

---

## 全局约定（每个任务开工前读一遍）

- 工作目录：worktree `/Users/zc/Projects/argos-dream`（分支 `feat/dream-consolidation`）。
- 命令前缀 `rtk`（如 `rtk git add`）；测试跑 `uv run pytest <目标文件> -q`。
- **基线已知红**（环境性，与本功能无关，不要去修）：`tests/desktop_smoke/test_shell_runtime_smoke.py` 2 个 + `tests/eval/test_terminal_bench_docker.py` 1 个。
- 每任务只跑**定向**测试；全量（`uv run pytest -n auto --dist loadgroup`）只在最终门跑。子集覆盖率低于 80% 是正常的，覆盖率只看全量。
- 代码风格：PEP 8、签名带类型注解、**中文 docstring/注释**（house norm）、frozen dataclass、绝不让学习路径异常拖挂主流程（log + 降级）。
- 与 spec 的一个**有意命名偏离**：spec 写的新字段名 `kind`，但 `StandingOrder.kind` 已被占用（schedule|file_trigger），故统一改名 **`action`**（"run" | "dream"），语义不变。

---

### Task 1: memory 注册 `task_reflection`（修断电：反思静默丢弃）`[standard]`

**背景：** `learning/reflection.py:46` 调 `capture_event("task_reflection", ...)`，但 `argos_agent/memory/auto.py:635` 的 `_TYPE_MAP` 只认 5 种 kind，未知 kind 直接 `return None` —— 生产里失败反思从未落盘。

**Files:**
- Modify: `argos_agent/memory/auto.py`（`_TYPE_MAP` / `_SCOPE_MAP` / `_DEFAULT_CONFIDENCE` 三表 + `capture_event` 的 value/key 分支）
- Test: `tests/test_memory_capture.py`（追加）

- [ ] **Step 1: 写失败测试**

在 `tests/test_memory_capture.py` 追加（沿用该文件现有 fixture 风格，`ARGOS_MEMORY_DIR` 指向 tmp_path）：

```python
def test_capture_task_reflection_persists(tmp_path, monkeypatch):
    """task_reflection 必须落盘(修复:未注册 kind 被静默丢弃)。"""
    monkeypatch.setenv("ARGOS_MEMORY_DIR", str(tmp_path))
    from argos_agent.memory import auto
    entry = auto.capture_event(
        "task_reflection",
        project_id="proj1",
        run_id="run123",
        goal="fix the login bug",
        verify_cmd="pytest -q",
        verdict="failed",
        self_verified=False,
        last_exc_snippet="AssertionError: boom",
    )
    assert entry is not None
    assert entry.type == "failure"
    assert entry.scope == "project"
    assert entry.key == "reflection.run123"
    assert "fix the login bug" in entry.value
    assert "failed" in entry.value


def test_capture_task_reflection_self_verified_tagged(tmp_path, monkeypatch):
    """self_verified=True 的反思要带防火墙标记(可统计'自验证降级')。"""
    monkeypatch.setenv("ARGOS_MEMORY_DIR", str(tmp_path))
    from argos_agent.memory import auto
    entry = auto.capture_event(
        "task_reflection", run_id="run456", goal="g",
        verdict="passed", self_verified=True,
    )
    assert entry is not None
    assert "[self_verified]" in entry.value
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_memory_capture.py -k task_reflection -q --no-cov`
Expected: FAIL（`entry is None`）

- [ ] **Step 3: 实现**

`argos_agent/memory/auto.py` 三张表各加一行：

```python
_TYPE_MAP = {
    ...,
    "task_reflection": "failure",
}
_SCOPE_MAP = {
    ...,
    "task_reflection": "project",
}
_DEFAULT_CONFIDENCE = {
    ...,
    "task_reflection": 0.7,
}
```

`capture_event` 的 value/key 构造 elif 链加分支（放在 `undo` 分支前后皆可）：

```python
    elif kind == "task_reflection":
        run_id = payload.get("run_id", "")
        goal = payload.get("goal", "")
        verdict = payload.get("verdict", "")
        snippet = payload.get("last_exc_snippet") or ""
        tag = " [self_verified]" if payload.get("self_verified") else ""
        value = f"reflection({verdict}{tag}): {goal}" + (f" — {snippet[:160]}" if snippet else "")
        key = f"reflection.{run_id[:12]}"
```

- [ ] **Step 4: 跑测试确认通过 + 反思链路回归**

Run: `uv run pytest tests/test_memory_capture.py tests/learning/test_reflection.py -q --no-cov`
Expected: PASS（全部）

- [ ] **Step 5: Commit**

```bash
rtk git add argos_agent/memory/auto.py tests/test_memory_capture.py
rtk git commit -m "fix(memory): 注册 task_reflection kind — 修生产反思静默丢弃"
```

---

### Task 2: `learning/candidates.py` 候选落盘存储层 `[standard]`

**Files:**
- Create: `argos_agent/learning/candidates.py`
- Test: `tests/learning/test_candidates.py`

候选目录布局：`<root>/<name>-<run_id前12位>/{SKILL.md, meta.json}`；root 默认 `~/.argos/learning/candidates`，一律参数注入（测试传 tmp_path，模式同 `skills_root`）。

- [ ] **Step 1: 写失败测试**

创建 `tests/learning/test_candidates.py`：

```python
"""candidates:候选落盘/读取/消费标记。"""
from pathlib import Path

from argos_agent.learning.candidates import (
    StoredCandidate, save_candidate, list_unconsumed, mark_consumed,
)
from argos_agent.learning.distiller import SkillCandidate


def _cand(name: str = "fix-login") -> SkillCandidate:
    return SkillCandidate(
        name=name, body_markdown=f"# {name}\nbody",
        verify_cmd="pytest -q", skill_md_path=Path("unused"),
    )


def test_save_then_list_roundtrip(tmp_path: Path):
    p = save_candidate(
        _cand(), root=tmp_path, source_run="abc123def45678",
        workspace="/tmp/proj", goal="fix login",
    )
    assert (p / "SKILL.md").exists() and (p / "meta.json").exists()
    got = list_unconsumed(tmp_path)
    assert len(got) == 1
    sc = got[0]
    assert sc.name == "fix-login"
    assert sc.source_run == "abc123def45678"
    assert sc.verify_cmd == "pytest -q"
    assert sc.workspace == "/tmp/proj"
    assert sc.goal == "fix login"
    assert "body" in sc.body_markdown


def test_mark_consumed_excludes_from_list(tmp_path: Path):
    p = save_candidate(_cand(), root=tmp_path, source_run="abc123def45678",
                       workspace=None, goal="g")
    mark_consumed(p, reason="promoted")
    assert list_unconsumed(tmp_path) == []
    # 标记是写 meta,不是删目录(审计可见)
    assert (p / "meta.json").exists()


def test_list_skips_corrupt_meta(tmp_path: Path):
    d = tmp_path / "bad-run"
    d.mkdir()
    (d / "SKILL.md").write_text("x", encoding="utf-8")
    (d / "meta.json").write_text("{not json", encoding="utf-8")
    assert list_unconsumed(tmp_path) == []  # 坏目录跳过,不抛


def test_save_is_idempotent_per_run(tmp_path: Path):
    save_candidate(_cand(), root=tmp_path, source_run="abc123def45678",
                   workspace=None, goal="g")
    save_candidate(_cand(), root=tmp_path, source_run="abc123def45678",
                   workspace=None, goal="g")
    assert len(list_unconsumed(tmp_path)) == 1  # 同 run 同名只存一份
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/learning/test_candidates.py -q --no-cov`
Expected: FAIL（ImportError: No module named candidates）

- [ ] **Step 3: 实现 `argos_agent/learning/candidates.py`**

```python
"""candidates:distill 产物的落盘存储层(晋升前的候选区)。

设计:
- 候选区 != skills_root —— skills 加载器不读这里,未晋升绝不生效。
- 目录:<root>/<name>-<run12>/{SKILL.md, meta.json};root 参数注入(默认 ~/.argos/learning/candidates)。
- 消费标记写 meta.json(consumed/consumed_reason),不删目录 —— 审计可见。
- 一切 IO 失败诚实降级:log + 返回空/None,绝不抛(学习路径不挂主任务)。
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_ROOT = Path.home() / ".argos" / "learning" / "candidates"


@dataclass(frozen=True, slots=True)
class StoredCandidate:
    """候选区里的一条已落盘候选。"""
    name: str
    body_markdown: str
    verify_cmd: str | None
    source_run: str
    workspace: str | None
    goal: str
    path: Path


def _dir_for(root: Path, name: str, source_run: str) -> Path:
    return root / f"{name}-{source_run[:12]}"


def save_candidate(cand: Any, *, root: Path, source_run: str,
                   workspace: str | None, goal: str) -> Path | None:
    """落盘一个 SkillCandidate。同 (name, run) 幂等覆盖。失败返 None。"""
    try:
        d = _dir_for(root, getattr(cand, "name", "learned"), source_run)
        d.mkdir(parents=True, exist_ok=True)
        # 原子写(同 promotion_gate._atomic_write_skill 约定)
        for fname, content in (
            ("SKILL.md", getattr(cand, "body_markdown", "")),
            ("meta.json", json.dumps({
                "name": getattr(cand, "name", "learned"),
                "source_run": source_run,
                "verify_cmd": getattr(cand, "verify_cmd", None),
                "workspace": workspace,
                "goal": goal,
                "created_at": time.time(),
                "consumed": False,
                "consumed_reason": None,
            }, ensure_ascii=False, indent=2)),
        ):
            tmp = d / (fname + ".tmp")
            tmp.write_text(content, encoding="utf-8")
            tmp.replace(d / fname)
        return d
    except Exception as e:  # noqa: BLE001 — 学习路径不挂主任务
        log.warning("candidates: save 失败(%s): %s", source_run, e)
        return None


def list_unconsumed(root: Path) -> list[StoredCandidate]:
    """扫描候选区,返回未消费候选。坏目录跳过。"""
    out: list[StoredCandidate] = []
    if not root.exists():
        return out
    for meta_path in sorted(root.glob("*/meta.json")):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("consumed"):
                continue
            body = (meta_path.parent / "SKILL.md").read_text(encoding="utf-8")
            out.append(StoredCandidate(
                name=str(meta.get("name", "")),
                body_markdown=body,
                verify_cmd=meta.get("verify_cmd"),
                source_run=str(meta.get("source_run", "")),
                workspace=meta.get("workspace"),
                goal=str(meta.get("goal", "")),
                path=meta_path.parent,
            ))
        except Exception as e:  # noqa: BLE001
            log.warning("candidates: 跳过坏候选 %s: %s", meta_path.parent, e)
    return out


def mark_consumed(cand_dir: Path, *, reason: str) -> bool:
    """标记候选已消费(promoted / rejected / workspace_gone)。失败返 False。"""
    meta_path = cand_dir / "meta.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["consumed"] = True
        meta["consumed_reason"] = reason
        meta["consumed_at"] = time.time()
        tmp = meta_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(meta_path)
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("candidates: mark_consumed 失败 %s: %s", cand_dir, e)
        return False
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/learning/test_candidates.py -q --no-cov`
Expected: PASS（4 个）

- [ ] **Step 5: Commit**

```bash
rtk git add argos_agent/learning/candidates.py tests/learning/test_candidates.py
rtk git commit -m "feat(learning): 候选落盘存储层 candidates.py — 晋升前候选区"
```

---

### Task 3: hook 落盘候选 + worker 透传 workspace（修断电：候选丢弃）`[standard]`

**背景：** `learning/hook.py:131` 无 runner/tasks 时直接 `return`，distill 产物被丢弃；`daemon/worker.py:654` 调 hook 时传 `runner_factory=None, tasks=[]` 且不传 workspace。

**Files:**
- Modify: `argos_agent/learning/hook.py`（`on_run_completed` 加 `workspace` kwarg；`_on_passed` 落盘分支）
- Modify: `argos_agent/daemon/worker.py:654`（透传 workspace）
- Test: `tests/learning/test_hook.py`（追加）

- [ ] **Step 1: 写失败测试**

在 `tests/learning/test_hook.py` 追加（沿用该文件现有的 store_dir/JSONL fixture 写法——先读一遍现有测试再写，保持同风格）：

```python
import asyncio
import json

from argos_agent.learning.candidates import list_unconsumed


def test_passed_without_runner_persists_candidate(tmp_path):
    """无 runner 时候选必须落盘(修复:当场丢弃)。"""
    store_dir = tmp_path / "runs"
    store_dir.mkdir()
    run_id = "abc123def456"
    events = [
        {"kind": "run_meta", "run_id": run_id},
        {"kind": "code_action", "code": "print('hello')"},
    ]
    (store_dir / f"{run_id}.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events), encoding="utf-8")

    from argos_agent.learning.hook import on_run_completed
    asyncio.run(on_run_completed(
        run_id=run_id, store_dir=store_dir, goal="say hello",
        verify_cmd="pytest -q", verdict_status="passed",
        skills_root=tmp_path / "skills",
        candidates_root=tmp_path / "candidates",
        workspace="/tmp/proj",
        runner_factory=None, tasks=[],
    ))
    got = list_unconsumed(tmp_path / "candidates")
    assert len(got) == 1
    assert got[0].workspace == "/tmp/proj"
    assert got[0].verify_cmd == "pytest -q"


def test_self_verified_passed_never_persists_candidate(tmp_path):
    """E4 防火墙:self_verified 的 passed 走 reflection,候选区必须为空。"""
    store_dir = tmp_path / "runs"
    store_dir.mkdir()
    run_id = "abc123def456"
    (store_dir / f"{run_id}.jsonl").write_text(
        json.dumps({"kind": "code_action", "code": "x=1"}), encoding="utf-8")

    from argos_agent.learning.hook import on_run_completed
    asyncio.run(on_run_completed(
        run_id=run_id, store_dir=store_dir, goal="g",
        verify_cmd="pytest -q", verdict_status="passed", self_verified=True,
        skills_root=tmp_path / "skills",
        candidates_root=tmp_path / "candidates",
        runner_factory=None, tasks=[],
    ))
    assert list_unconsumed(tmp_path / "candidates") == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/learning/test_hook.py -k candidate -q --no-cov`
Expected: FAIL（unexpected keyword `candidates_root`）

- [ ] **Step 3: 实现**

`argos_agent/learning/hook.py`：

1. `on_run_completed` 签名追加两个 kwarg（带默认值，向后兼容）：

```python
async def on_run_completed(
    *,
    run_id: str,
    store_dir: Path,
    goal: str,
    verify_cmd: str | None,
    verdict_status: str,
    self_verified: bool = False,
    skills_root: Path,
    candidates_root: Path | None = None,   # 候选落盘区;None = 不落盘(兼容旧 caller)
    workspace: str | None = None,          # 源 run 的项目目录(A/B 取证用)
    runner_factory: Callable[[], Any] | None = None,
    tasks: list | None = None,
) -> None:
```

2. 两个参数透传给 `_on_passed`（`_on_failed` 不需要）；`_on_passed` 的"无 runner"分支从丢弃改为落盘：

```python
    if not tasks or runner_factory is None:
        # 无语料 / 无 runner → 不晋升,但候选落盘进候选区(Dream 夜间整合的材料;
        # 修复:此前直接丢弃,生产路径学习闭环断电)
        if candidates_root is not None:
            from argos_agent.learning import candidates as _cands
            _cands.save_candidate(
                cand, root=candidates_root, source_run=run_id,
                workspace=workspace, goal=goal,
            )
        return
```

`argos_agent/daemon/worker.py` `_maybe_run_learning_hook` 的调用处追加：

```python
            await on_run_completed(
                run_id=self.run_id,
                store_dir=store_dir,
                goal=getattr(entry, "goal", "") or "",
                verify_cmd=verify_cmd,
                verdict_status=verdict_status,
                self_verified=self_verified,
                skills_root=skills_root,
                candidates_root=Path(os.path.expanduser("~/.argos/learning/candidates")),
                workspace=(getattr(entry, "workspace", "") or None),
                runner_factory=None,
                tasks=[],
            )
```

（`entry` 是 registry 的 run 条目；先 `grep -n "workspace" argos_agent/daemon/registry.py` 确认字段名，若 entry 无 workspace 字段则从 `self._manager` 侧拿——以实际代码为准，测试只钉 hook 层。）

- [ ] **Step 4: 跑测试确认通过 + hook 回归**

Run: `uv run pytest tests/learning/test_hook.py tests/learning/test_self_verified_firewall.py -q --no-cov`
Expected: PASS（全部）

- [ ] **Step 5: Commit**

```bash
rtk git add argos_agent/learning/hook.py argos_agent/daemon/worker.py tests/learning/test_hook.py
rtk git commit -m "fix(learning): 无 runner 时候选落盘候选区 — 修生产候选丢弃断电"
```

---

### Task 4: `action` 字段贯通 StandingOrder / ProactiveSuggestion / Event `[standard]`

**Files:**
- Modify: `argos_agent/conductor/orders.py`（StandingOrder + to_dict/from_dict + __post_init__ 校验）
- Modify: `argos_agent/conductor/proposals.py`（ProactiveSuggestion + propose 透传）
- Modify: `argos_agent/protocol/events.py:285`（ProactiveSuggestionEvent）
- Modify: `argos_agent/daemon/conductor_supervisor.py:120`（_emit_suggestion 透传）
- Test: `tests/conductor/test_orders.py`、`tests/conductor/test_proposals.py`、`tests/protocol/test_event_golden.py`（均追加/更新）

- [ ] **Step 1: 写失败测试**

`tests/conductor/test_orders.py` 追加：

```python
def test_order_action_default_run_and_roundtrip():
    """action 默认 'run';to_dict/from_dict 往返;旧落盘数据(无 action 键)兼容。"""
    import time
    from argos_agent.conductor.orders import StandingOrder
    o = StandingOrder(
        id="x1", utterance="u", kind="schedule", schedule="03:00",
        trigger_glob=None, goal_template="g", enabled=True,
        created_at=time.time(), last_fired_at=None,
    )
    assert o.action == "run"
    d = o.to_dict()
    assert d["action"] == "run"
    d.pop("action")  # 模拟旧数据
    assert StandingOrder.from_dict(d).action == "run"


def test_order_action_dream_roundtrip():
    import time
    from argos_agent.conductor.orders import StandingOrder
    o = StandingOrder(
        id="x2", utterance="夜间整合", kind="schedule", schedule="03:00",
        trigger_glob=None, goal_template="__dream__", enabled=True,
        created_at=time.time(), last_fired_at=None, action="dream",
    )
    assert StandingOrder.from_dict(o.to_dict()).action == "dream"


def test_order_action_invalid_rejected():
    import time
    import pytest
    from argos_agent.conductor.orders import StandingOrder
    with pytest.raises(ValueError):
        StandingOrder(
            id="x3", utterance="u", kind="schedule", schedule="03:00",
            trigger_glob=None, goal_template="g", enabled=True,
            created_at=time.time(), last_fired_at=None, action="hack",
        )
```

`tests/conductor/test_proposals.py` 追加：

```python
def test_propose_carries_order_action():
    import time
    from argos_agent.conductor.orders import StandingOrder
    from argos_agent.conductor.proposals import propose
    o = StandingOrder(
        id="x1", utterance="夜间整合", kind="schedule", schedule="03:00",
        trigger_glob=None, goal_template="__dream__", enabled=True,
        created_at=time.time(), last_fired_at=None, action="dream",
    )
    s = propose(o, {})
    assert s.action == "dream"
    assert s.requires_confirmation is True
```

`tests/protocol/test_event_golden.py`：找到现有 `ProactiveSuggestionEvent` 的 golden 测试，期望 dict 追加 `"action": "run"`；并加一条 `action="dream"` 的 roundtrip。

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/conductor/test_orders.py tests/conductor/test_proposals.py tests/protocol/test_event_golden.py -q --no-cov`
Expected: 新增用例 FAIL（unexpected keyword / golden 不含 action）

- [ ] **Step 3: 实现**

`orders.py`：`StandingOrder` 末尾加字段 `action: str = "run"`；`__post_init__` 追加：

```python
        if self.action not in ("run", "dream"):
            raise ValueError(
                f"StandingOrder.action 必须是 'run' 或 'dream'，收到 {self.action!r} (id={self.id!r})"
            )
```

`to_dict` 加 `"action": self.action`；`from_dict` 加 `action=str(d.get("action", "run"))`。
注意 `with_last_fired` / `with_enabled`（orders.py:100/105）若是手工重建 dataclass，要补 `action=self.action`；若用 `dataclasses.replace` 则无需改——**先读这两个方法**。

`proposals.py`：`ProactiveSuggestion` 末尾加 `action: str = "run"`；`propose()` 构造时传 `action=order.action`。

`protocol/events.py` `ProactiveSuggestionEvent` 末尾加：

```python
    action: str = "run"   # "run" = confirm 后 create_run;"dream" = confirm 后跑 DreamPipeline
```

`conductor_supervisor.py` `_emit_suggestion` 构造事件时加 `action=getattr(s, "action", "run")`。

- [ ] **Step 4: 跑测试确认通过 + conductor/protocol 回归**

Run: `uv run pytest tests/conductor/ tests/protocol/ -q --no-cov`
Expected: PASS（全部）

- [ ] **Step 5: Commit**

```bash
rtk git add argos_agent/conductor/orders.py argos_agent/conductor/proposals.py argos_agent/protocol/events.py argos_agent/daemon/conductor_supervisor.py tests/conductor/test_orders.py tests/conductor/test_proposals.py tests/protocol/test_event_golden.py
rtk git commit -m "feat(conductor): action 字段贯通 order/suggestion/event — dream 路由地基"
```

---

### Task 5: `learning/dream.py` 聚类 + 综合（铁律：模型只写叙述层）`[complex]`

**Files:**
- Create: `argos_agent/learning/dream.py`（本任务只做 scan/cluster/synthesize 三个纯函数；管道编排在 Task 7）
- Test: `tests/learning/test_dream.py`

核心数据结构与铁律：

- `DreamUnit`：一个整合单元 = 1 个或多个同簇 `StoredCandidate`。
- 聚类相似度 v1 = goal+verify_cmd 的 token Jaccard（阈值 0.35，常量 `SIM_THRESHOLD`）；不引第三方库。
- `synthesize(unit, narrate=None)`：代码/verify 段逐字来自源候选（带 `source_run` 标注）；`narrate` 是可选 `Callable[[str], str]`（Task 9 接模型）；**`_strip_code_blocks()` 剥掉 narrate 输出里一切 fenced code block**；narrate 为 None 或抛异常 → 模板叙述兜底。

- [ ] **Step 1: 写失败测试**

创建 `tests/learning/test_dream.py`：

```python
"""dream:聚类 + 综合的铁律测试。"""
from pathlib import Path

from argos_agent.learning.candidates import StoredCandidate
from argos_agent.learning.dream import (
    SIM_THRESHOLD, cluster_candidates, synthesize, _token_sim, _strip_code_blocks,
)


def _sc(name: str, goal: str, verify: str = "pytest -q",
        run: str = "run000000000000", body: str = "# s\n```python\nx = 1\n```",
        workspace: str | None = "/tmp/p") -> StoredCandidate:
    return StoredCandidate(
        name=name, body_markdown=body, verify_cmd=verify,
        source_run=run, workspace=workspace, goal=goal, path=Path("/dev/null"),
    )


def test_token_sim_basics():
    assert _token_sim("fix login bug pytest", "fix login bug pytest") == 1.0
    assert _token_sim("alpha beta", "gamma delta") == 0.0


def test_cluster_groups_similar_goals():
    a = _sc("a", "fix login auth bug", run="run1aaaaaaaaaaaa")
    b = _sc("b", "fix login auth timeout bug", run="run2bbbbbbbbbbbb")
    c = _sc("c", "generate sales report csv", run="run3cccccccccccc")
    units = cluster_candidates([a, b, c])
    sizes = sorted(len(u.sources) for u in units)
    assert sizes == [1, 2]  # a+b 同簇,c 单例


def test_cluster_cap_limits_units():
    cands = [_sc(f"s{i}", f"totally unique goal {i} {'x'*i}",
                 run=f"run{i:013d}") for i in range(6)]
    units = cluster_candidates(cands, max_units=3)
    assert len(units) == 3


def test_strip_code_blocks_removes_all_fences():
    txt = "前文\n```python\nevil()\n```\n中文\n```\nrm -rf /\n```\n尾"
    out = _strip_code_blocks(txt)
    assert "evil" not in out and "rm -rf" not in out
    assert "前文" in out and "尾" in out


def test_synthesize_code_only_from_sources_model_only_narrative():
    """铁律:模型输出的代码块绝不进产物;源代码段逐字保留并标注 source_run。"""
    a = _sc("a", "fix login bug", run="run1aaaaaaaaaaaa",
            body="# a\n```python\nlogin_fix_alpha()\n```")
    b = _sc("b", "fix login auth bug", run="run2bbbbbbbbbbbb",
            body="# b\n```python\nlogin_fix_beta()\n```")
    units = cluster_candidates([a, b])
    unit = next(u for u in units if len(u.sources) == 2)

    def evil_narrate(prompt: str) -> str:
        return "适用于登录类修复。\n```python\nfabricated_by_model()\n```"

    cand = synthesize(unit, narrate=evil_narrate)
    assert cand is not None
    md = cand.body_markdown
    assert "login_fix_alpha()" in md and "login_fix_beta()" in md  # 源逐字保留
    assert "run1aaaaaaaa" in md and "run2bbbbbbbb" in md           # source_run 标注
    assert "fabricated_by_model" not in md                          # 模型代码被剥
    assert "适用于登录类修复" in md                                  # 叙述层保留
    assert "enabled: false" in md                                   # 晋升前不生效


def test_synthesize_narrate_failure_degrades_to_template():
    a = _sc("a", "fix login bug", run="run1aaaaaaaaaaaa")
    b = _sc("b", "fix login auth bug", run="run2bbbbbbbbbbbb")
    unit = next(u for u in cluster_candidates([a, b]) if len(u.sources) == 2)

    def boom(prompt: str) -> str:
        raise RuntimeError("model down")

    cand = synthesize(unit, narrate=boom)
    assert cand is not None  # 叙述层降级,功能不死
    assert "本技能综合自" in cand.body_markdown
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/learning/test_dream.py -q --no-cov`
Expected: FAIL（ImportError）

- [ ] **Step 3: 实现 `argos_agent/learning/dream.py`（本任务部分）**

```python
"""dream:夜间整合 —— 跨 run 聚类 + 综合蒸馏(spec: 2026-06-13-dream-consolidation-design)。

铁律(与 distiller 同源):
- 可执行内容(代码段/verify 命令)逐字来自已验证源材料,绝不出自模型;
- narrate(模型)只写"何时适用/教训"叙述层,输出中的 fenced code block 一律剥除;
- narrate 失败 → 模板叙述兜底,功能不死。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Callable

from argos_agent.learning.candidates import StoredCandidate

log = logging.getLogger(__name__)

SIM_THRESHOLD = 0.35       # goal+verify token Jaccard 阈值(宁可不合并)
DEFAULT_MAX_UNITS = 3      # 每晚整合单元上限(防失控烧 token)

_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_CODE_BLOCK_RE = re.compile(r"```python\n(.*?)```", re.DOTALL)


@dataclass(frozen=True, slots=True)
class DreamUnit:
    """一个整合单元:同簇候选(≥2 = 综合;1 = 单例直接走 A/B)。"""
    sources: tuple[StoredCandidate, ...]


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9一-鿿]+", (text or "").lower()))


def _token_sim(a: str, b: str) -> float:
    """token Jaccard;空集对 → 0.0。"""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _sig(c: StoredCandidate) -> str:
    return f"{c.goal} {c.verify_cmd or ''}"


def cluster_candidates(
    cands: list[StoredCandidate], *, max_units: int = DEFAULT_MAX_UNITS,
) -> list[DreamUnit]:
    """贪心单链聚类:依次归入首个相似度 ≥ SIM_THRESHOLD 的簇,否则开新簇。

    确定性:输入顺序决定输出顺序(caller 已按目录名 sorted)。
    上限裁剪:多簇优先(综合价值高),再按出现顺序补单例。
    """
    clusters: list[list[StoredCandidate]] = []
    for c in cands:
        for cl in clusters:
            if _token_sim(_sig(c), _sig(cl[0])) >= SIM_THRESHOLD:
                cl.append(c)
                break
        else:
            clusters.append([c])
    multi = [cl for cl in clusters if len(cl) >= 2]
    single = [cl for cl in clusters if len(cl) == 1]
    picked = (multi + single)[:max_units]
    return [DreamUnit(sources=tuple(cl)) for cl in picked]


def _strip_code_blocks(text: str) -> str:
    """剥掉一切 fenced code block —— 模型输出永远不许携带可执行内容。"""
    return _FENCE_RE.sub("", text or "").strip()


def _extract_code(body_markdown: str) -> str:
    """从源候选 SKILL.md 抽 python 代码块原文(distiller 产物格式)。"""
    return "\n\n".join(m.strip() for m in _CODE_BLOCK_RE.findall(body_markdown or ""))


def _merged_name(unit: DreamUnit) -> str:
    from argos_agent.learning.distiller import _slugify_goal
    return ("dream-" + _slugify_goal(unit.sources[0].goal))[:40]


def synthesize(
    unit: DreamUnit, *, narrate: Callable[[str], str] | None = None,
) -> "object | None":
    """把一个 DreamUnit 综合成 SkillCandidate(不落盘,晋升由 promotion_gate 决定)。

    单例 unit 直接返回其源候选转成的 SkillCandidate(代码原样);
    多源 unit 产综合 SKILL.md。
    """
    from argos_agent.learning.distiller import SkillCandidate
    from pathlib import Path

    if not unit.sources:
        return None
    name = _merged_name(unit)
    runs = [s.source_run for s in unit.sources]

    # 叙述层:模型(剥代码) or 模板兜底
    narrative = ""
    if narrate is not None:
        try:
            prompt = (
                "以下是多次已验证成功的任务经验,请用 2-4 句中文总结"
                "「何时适用」与「注意事项」。只写文字,不要代码:\n"
                + "\n".join(f"- {s.goal}" for s in unit.sources)
            )
            narrative = _strip_code_blocks(narrate(prompt))
        except Exception as e:  # noqa: BLE001 — 叙述层降级,功能不死
            log.warning("dream: narrate 失败(模板兜底): %s", e)
    if not narrative:
        narrative = "本技能综合自 %d 次已验证通过的 run(目标见下),适用于同类任务。" % len(unit.sources)

    lines = [
        "---",
        f"name: {name}",
        "capabilities: []",
        "enabled: false",
        f"source_runs: [{', '.join(runs)}]",
        "---",
        "",
        f"# {name}",
        "",
        "## When to use",
        "",
        narrative,
        "",
        "## Verified sources",
        "",
    ]
    for s in unit.sources:
        lines += [f"### source_run {s.source_run}", "", f"**Goal**: {s.goal}", ""]
        code = _extract_code(s.body_markdown)
        if code:
            lines += ["```python", code, "```", ""]
        if s.verify_cmd:
            lines += ["Verify:", "", "```bash", s.verify_cmd, "```", ""]
    return SkillCandidate(
        name=name,
        body_markdown="\n".join(lines),
        verify_cmd=unit.sources[0].verify_cmd,
        skill_md_path=Path("unpromoted"),
    )
```

（`_slugify_goal` 是 distiller 的私有函数——跨模块复用前先确认无下划线导出惯例冲突；若 review 嫌弃，把 slugify 提为 distiller 公开函数 `slugify_goal` 并双处调用。）

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/learning/test_dream.py -q --no-cov`
Expected: PASS（6 个）

- [ ] **Step 5: Commit**

```bash
rtk git add argos_agent/learning/dream.py tests/learning/test_dream.py
rtk git commit -m "feat(learning): dream 聚类+综合 — 模型只写叙述层,可执行内容逐字来自已验证源"
```

---

### Task 6: A/B 晋升接线 — `promote(runner_b=)` + HintedRunner + 消费规则 `[standard]`

**Files:**
- Modify: `argos_agent/learning/promotion_gate.py`（`promote` 加可选 `runner_b`）
- Modify: `argos_agent/learning/dream.py`（追加 `build_eval_tasks` / `HintedRunner` / `promote_unit`）
- Test: `tests/learning/test_promotion_gate.py`（追加）、`tests/learning/test_dream.py`（追加）

- [ ] **Step 1: 写失败测试**

`tests/learning/test_promotion_gate.py` 追加（沿用该文件现有 FakeRunner/FakeTask 风格——先读现有测试）：

```python
def test_promote_runner_b_used_for_b_side(tmp_path):
    """runner_b 注入时:A 用 runner,B 用 runner_b(B 全过 A 全挂 → 晋升)。"""
    from argos_agent.learning.promotion_gate import promote

    class _R:
        def __init__(self, status):
            self._status = status
        def run(self, task, *, model_tier):
            class _Res:
                pass
            r = _Res()
            r.pass_status = self._status
            return r

    class _Cand:
        name = "dream-x"
        body_markdown = "# x"
        verify_cmd = "pytest -q"

    res = promote(
        candidate=_Cand(), tasks=[object(), object()],
        runner=_R("failed"), runner_b=_R("passed"),
        skills_root=tmp_path,
    )
    assert res.promoted is True
    assert res.a_passed == 0 and res.b_passed == 2
```

`tests/learning/test_dream.py` 追加：

```python
def test_build_eval_tasks_skips_missing_workspace(tmp_path):
    from argos_agent.learning.dream import build_eval_tasks, cluster_candidates
    ws = tmp_path / "proj"
    ws.mkdir()
    a = _sc("a", "fix login bug", run="run1aaaaaaaaaaaa", workspace=str(ws))
    b = _sc("b", "fix login auth bug", run="run2bbbbbbbbbbbb",
            workspace=str(tmp_path / "gone"))
    unit = next(u for u in cluster_candidates([a, b]) if len(u.sources) == 2)
    tasks, gone = build_eval_tasks(unit)
    assert len(tasks) == 1 and tasks[0].working_dir == ws
    assert [s.source_run for s in gone] == ["run2bbbbbbbbbbbb"]


def test_hinted_runner_prepends_hint_to_goal(tmp_path):
    from argos_agent.learning.dream import HintedRunner

    captured = {}

    class _Inner:
        def run(self, task, *, model_tier):
            captured["goal"] = task.goal
            class _Res:
                pass
            r = _Res()
            r.pass_status = "passed"
            return r

    from argos_agent.eval.corpus import EvalTask
    t = EvalTask(id="t", category="dream", difficulty="n/a", title="t",
                 goal="fix it", verify_cmd="true", setup_cmd=None,
                 expected_files=(), working_dir=tmp_path, corpus_version=0)
    HintedRunner(_Inner(), hint="经验提示文本").run(t, model_tier="default")
    assert captured["goal"].startswith("可参考以下已验证经验")
    assert "经验提示文本" in captured["goal"] and "fix it" in captured["goal"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/learning/test_promotion_gate.py tests/learning/test_dream.py -q --no-cov`
Expected: 新增用例 FAIL

- [ ] **Step 3: 实现**

`promotion_gate.py`：`promote` 签名加 `runner_b: Any = None`；A/B 循环改为：

```python
            try:
                a = runner.run(task, model_tier="default")
            except Exception:  # noqa: BLE001
                a = None
            rb = runner_b if runner_b is not None else runner
            try:
                b = rb.run(task, model_tier="default")
            except Exception:  # noqa: BLE001
                b = None
```

（其余判定/落盘/builtin 硬拒一行不动。）

`dream.py` 追加：

```python
@dataclass(frozen=True, slots=True)
class HintedRunner:
    """B 侧 runner:把综合 skill 的叙述+源经验作为 hint 前置到 task.goal。

    promotion_gate 不感知 hint(契约注释言明是 runner 的事);A 侧用裸 runner。
    """
    inner: object
    hint: str

    def run(self, task, *, model_tier: str):
        import dataclasses
        hinted = dataclasses.replace(
            task, goal=f"可参考以下已验证经验:\n{self.hint}\n\n---\n\n{task.goal}")
        return self.inner.run(hinted, model_tier=model_tier)


def build_eval_tasks(unit: DreamUnit) -> tuple[list, list]:
    """从 unit 源构造 A/B 语料。返回 (tasks, workspace_gone_sources)。

    workspace 不存在的源进 gone 列表(消费规则:证据永远拿不到 → 标记 consumed)。
    """
    from pathlib import Path
    from argos_agent.eval.corpus import EvalTask

    tasks: list = []
    gone: list[StoredCandidate] = []
    for s in unit.sources:
        ws = Path(s.workspace) if s.workspace else None
        if ws is None or not ws.exists():
            gone.append(s)
            continue
        if not s.verify_cmd:
            gone.append(s)
            continue
        tasks.append(EvalTask(
            id=f"dream-{s.source_run[:12]}", category="dream", difficulty="n/a",
            title=s.goal[:60], goal=s.goal, verify_cmd=s.verify_cmd,
            setup_cmd=None, expected_files=(), working_dir=ws, corpus_version=0,
        ))
    return tasks, gone
```

注意：`EvalTask` 若是 frozen dataclass 则 `dataclasses.replace` 可用；先确认（`grep -n "frozen" argos_agent/eval/corpus.py`）。非 frozen 也兼容。

- [ ] **Step 4: 跑测试确认通过 + promotion_gate 回归**

Run: `uv run pytest tests/learning/ -q --no-cov`
Expected: PASS（全部）

- [ ] **Step 5: Commit**

```bash
rtk git add argos_agent/learning/promotion_gate.py argos_agent/learning/dream.py tests/learning/test_promotion_gate.py tests/learning/test_dream.py
rtk git commit -m "feat(learning): A/B 晋升接线 — promote(runner_b) + HintedRunner + 语料构造"
```

---

### Task 7: `memory/consolidate.py` 记忆整理（合并 + 归档，永不硬删）`[standard]`

**Files:**
- Create: `argos_agent/memory/consolidate.py`
- Test: `tests/test_memory_consolidate.py`

操作对象是 4-tier JSONL 目录（`~/.argos/memory/`，测试用 `ARGOS_MEMORY_DIR`/参数注入）。**对 dict 操作，不重构 MemoryEntry**（坏行兼容、解耦）。打分公式与 auto-memory 文档一致：`score = clamp(confidence - 0.01*天数(now-last_used_at) + 0.02*min(use_count,10), 0, 1)`——**实现前先 grep `decay` in `argos_agent/memory/auto.py`，若已有现成打分函数则复用，不要重写第二份**。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_memory_consolidate.py`：

```python
"""memory consolidate:合并重复 + 归档衰减,永不硬删。"""
import json
import time
from pathlib import Path

from argos_agent.memory.consolidate import consolidate


def _entry(key: str, value: str, *, ts: float, conf: float = 0.8,
           use_count: int = 0) -> dict:
    return {
        "id": f"id-{key}-{ts}", "type": "failure", "scope": "project",
        "key": key, "value": value, "confidence": conf, "evidence": [],
        "ts": ts, "last_used_at": ts, "use_count": use_count,
        "skill_name": None, "project_id": "p1", "session_id": None,
    }


def _write(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")


def test_merge_same_key_keeps_newest_sums_use_count(tmp_path):
    now = time.time()
    f = tmp_path / "projects" / "p1.jsonl"
    _write(f, [
        _entry("reflection.run1", "old lesson", ts=now - 3600, use_count=2),
        _entry("reflection.run1", "new lesson", ts=now, use_count=1),
    ])
    rep = consolidate(tmp_path, now=now)
    assert rep.merged == 1
    kept = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l]
    assert len(kept) == 1
    assert kept[0]["value"] == "new lesson"
    assert kept[0]["use_count"] == 3


def test_archive_decayed_entries_never_hard_delete(tmp_path):
    now = time.time()
    f = tmp_path / "projects" / "p1.jsonl"
    old = _entry("reflection.old", "stale", ts=now - 90 * 86400, conf=0.7)
    fresh = _entry("reflection.new", "fresh", ts=now, conf=0.7)
    _write(f, [old, fresh])
    rep = consolidate(tmp_path, now=now, archive_threshold=0.2)
    assert rep.archived == 1
    kept = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l]
    assert [e["key"] for e in kept] == ["reflection.new"]
    arch = tmp_path / "archive.jsonl"
    assert arch.exists()
    archived = [json.loads(l) for l in arch.read_text(encoding="utf-8").splitlines() if l]
    assert archived[0]["key"] == "reflection.old"  # 归档,不是删除


def test_consolidate_skips_corrupt_lines_and_archive_file(tmp_path):
    now = time.time()
    f = tmp_path / "user.jsonl"
    f.write_text('{bad json\n' + json.dumps(_entry("k", "v", ts=now)), encoding="utf-8")
    (tmp_path / "archive.jsonl").write_text(json.dumps(_entry("a", "x", ts=0)), encoding="utf-8")
    rep = consolidate(tmp_path, now=now)
    assert rep.errors == 0  # 坏行跳过不算 error;archive.jsonl 不扫
    kept = [l for l in f.read_text(encoding="utf-8").splitlines() if l]
    assert len(kept) == 2  # 坏行原样保留(不动看不懂的数据)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_memory_consolidate.py -q --no-cov`
Expected: FAIL（ImportError）

- [ ] **Step 3: 实现 `argos_agent/memory/consolidate.py`**

```python
"""consolidate:记忆整理(Dream 夜间整合 phase ④)。

纪律:
- 永不硬删:衰减条目移入 <root>/archive.jsonl;
- 看不懂的行(坏 JSON)原样保留 —— 不动不属于自己的数据;
- 原子重写(tmp+replace);任何文件失败只记数,绝不抛。
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

ARCHIVE_NAME = "archive.jsonl"
DEFAULT_ARCHIVE_THRESHOLD = 0.2


@dataclass(frozen=True, slots=True)
class ConsolidationReport:
    """一次整理的结果计数。"""
    merged: int = 0
    archived: int = 0
    files_touched: int = 0
    errors: int = 0


def _score(e: dict, now: float) -> float:
    """衰减打分:confidence - 0.01/天 + 0.02*use_count(封顶10),clamp [0,1]。"""
    try:
        conf = float(e.get("confidence", 0.5))
        last = float(e.get("last_used_at", e.get("ts", now)))
        use = min(int(e.get("use_count", 0)), 10)
        days = max(0.0, (now - last) / 86400.0)
        return max(0.0, min(1.0, conf - 0.01 * days + 0.02 * use))
    except Exception:  # noqa: BLE001 — 算不出分 = 不归档(保守)
        return 1.0


def consolidate(
    memory_dir: Path, *, now: float | None = None,
    archive_threshold: float = DEFAULT_ARCHIVE_THRESHOLD,
) -> ConsolidationReport:
    """整理 memory_dir 下所有 tier JSONL(递归;跳过 archive.jsonl)。"""
    now = time.time() if now is None else now
    merged = archived = touched = errors = 0
    archive_path = memory_dir / ARCHIVE_NAME
    if not memory_dir.exists():
        return ConsolidationReport()

    for f in sorted(memory_dir.rglob("*.jsonl")):
        if f.name == ARCHIVE_NAME:
            continue
        try:
            raw_lines = f.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as e:
            log.warning("consolidate: 读失败 %s: %s", f, e)
            errors += 1
            continue
        keep_raw: list[str] = []     # 坏行原样保留
        by_key: dict[str, dict] = {}  # key → 最新条目(合并)
        to_archive: list[dict] = []
        file_merged = 0
        for line in raw_lines:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
                assert isinstance(e, dict) and "key" in e
            except Exception:  # noqa: BLE001 — 看不懂的行原样保留
                keep_raw.append(line)
                continue
            k = str(e["key"])
            prev = by_key.get(k)
            if prev is None:
                by_key[k] = e
            else:
                # 同 key 重复:留 ts 新的,use_count 累加
                newer, older = (e, prev) if float(e.get("ts", 0)) >= float(prev.get("ts", 0)) else (prev, e)
                newer = dict(newer)
                newer["use_count"] = int(newer.get("use_count", 0)) + int(older.get("use_count", 0))
                by_key[k] = newer
                file_merged += 1
        survivors: list[dict] = []
        for e in by_key.values():
            if _score(e, now) < archive_threshold:
                to_archive.append(e)
            else:
                survivors.append(e)
        if file_merged == 0 and not to_archive:
            continue  # 无变化不重写
        try:
            # 先追加归档(归档成功才允许从源移除 —— 宁可重复不可丢失)
            if to_archive:
                with archive_path.open("a", encoding="utf-8") as af:
                    for e in to_archive:
                        af.write(json.dumps(e, ensure_ascii=False) + "\n")
            new_lines = keep_raw + [json.dumps(e, ensure_ascii=False) for e in survivors]
            tmp = f.with_suffix(".jsonl.tmp")
            tmp.write_text("\n".join(new_lines) + ("\n" if new_lines else ""), encoding="utf-8")
            tmp.replace(f)
            merged += file_merged
            archived += len(to_archive)
            touched += 1
        except Exception as e:  # noqa: BLE001
            log.warning("consolidate: 重写失败 %s: %s", f, e)
            errors += 1
    return ConsolidationReport(merged=merged, archived=archived,
                               files_touched=touched, errors=errors)
```

- [ ] **Step 4: 跑测试确认通过 + memory 回归**

Run: `uv run pytest tests/test_memory_consolidate.py tests/test_memory.py tests/test_memory_decay.py tests/test_memory_tiers.py -q --no-cov`
Expected: PASS（全部）

- [ ] **Step 5: Commit**

```bash
rtk git add argos_agent/memory/consolidate.py tests/test_memory_consolidate.py
rtk git commit -m "feat(memory): consolidate 记忆整理 — 同key合并+衰减归档,永不硬删"
```

---

### Task 8: DreamPipeline 编排 + dream 事件 + 报告落盘 `[complex]`

**Files:**
- Modify: `argos_agent/learning/dream.py`（追加 `DreamPipeline` / `DreamReport` / `has_material` / `scan_material`）
- Modify: `argos_agent/protocol/events.py`（追加 `DreamProgressEvent` / `DreamReportEvent`）
- Test: `tests/learning/test_dream_pipeline.py`、`tests/protocol/test_event_golden.py`（追加）

- [ ] **Step 1: 写失败测试**

`tests/protocol/test_event_golden.py` 追加（仿 `test_hook_fired_golden` 的 `_golden`/`_round` 写法）：

```python
def test_dream_progress_golden():
    from argos_agent.protocol.events import DreamProgressEvent
    ev = DreamProgressEvent(stage="cluster", detail="2 units", ts=1.5)
    _golden(ev, {"stage": "cluster", "detail": "2 units", "ts": 1.5})


def test_dream_report_golden_and_roundtrip():
    from argos_agent.protocol.events import DreamReportEvent
    ev = DreamReportEvent(
        units_total=2, promoted=1, rejected=1, skipped=0,
        memory_merged=3, memory_archived=2,
        report_path="/tmp/dreams/2026-06-13.jsonl", ts=2.0,
    )
    _golden(ev, {
        "units_total": 2, "promoted": 1, "rejected": 1, "skipped": 0,
        "memory_merged": 3, "memory_archived": 2,
        "report_path": "/tmp/dreams/2026-06-13.jsonl", "ts": 2.0,
    })
    assert _round(ev).promoted == 1
```

创建 `tests/learning/test_dream_pipeline.py`：

```python
"""DreamPipeline:端到端编排(全 fake 注入,无网络无模型)。"""
import asyncio
import json
from pathlib import Path

from argos_agent.learning.candidates import save_candidate, list_unconsumed
from argos_agent.learning.dream import DreamPipeline
from argos_agent.learning.distiller import SkillCandidate


def _seed(root: Path, name: str, goal: str, run: str, ws: Path | None):
    save_candidate(
        SkillCandidate(name=name, body_markdown=f"# {name}\n```python\nok()\n```",
                       verify_cmd="true", skill_md_path=Path("u")),
        root=root, source_run=run, workspace=str(ws) if ws else None, goal=goal)


class _PassRunner:
    def run(self, task, *, model_tier):
        class _R: pass
        r = _R(); r.pass_status = "passed"
        return r


class _FailRunner:
    def run(self, task, *, model_tier):
        class _R: pass
        r = _R(); r.pass_status = "failed"
        return r


def _mk_pipeline(tmp_path, runner_a, runner_b, events):
    async def _bcast(ev: dict) -> None:
        events.append(ev)
    return DreamPipeline(
        candidates_root=tmp_path / "cands",
        skills_root=tmp_path / "skills",
        memory_dir=tmp_path / "memory",
        dreams_dir=tmp_path / "dreams",
        runner_factory=lambda hint: runner_b if hint else runner_a,
        narrate=None,
        broadcast_fn=_bcast,
    )


def test_pipeline_promotes_and_consumes_on_improvement(tmp_path):
    ws = tmp_path / "proj"; ws.mkdir()
    croot = tmp_path / "cands"
    _seed(croot, "a", "fix login bug", "run1aaaaaaaaaaaa", ws)
    _seed(croot, "b", "fix login auth bug", "run2bbbbbbbbbbbb", ws)
    events: list = []
    pipe = _mk_pipeline(tmp_path, _FailRunner(), _PassRunner(), events)
    report = asyncio.run(pipe.run())
    assert report.promoted == 1
    promoted = list((tmp_path / "skills").glob("*/SKILL.md"))
    assert len(promoted) == 1
    assert list_unconsumed(croot) == []          # 晋升 → 消费
    kinds = [e.get("kind") for e in events]
    assert "dream_progress" in kinds and "dream_report" in kinds
    # 报告落盘
    assert list((tmp_path / "dreams").glob("*.jsonl"))


def test_pipeline_no_tasks_keeps_candidates_unconsumed(tmp_path):
    croot = tmp_path / "cands"
    # workspace=None → build_eval_tasks 全 gone → 标记 consumed(workspace_gone)
    _seed(croot, "a", "fix login bug", "run1aaaaaaaaaaaa", None)
    events: list = []
    pipe = _mk_pipeline(tmp_path, _FailRunner(), _PassRunner(), events)
    report = asyncio.run(pipe.run())
    assert report.promoted == 0
    assert not (tmp_path / "skills").exists() or not list((tmp_path / "skills").glob("*/SKILL.md"))
    # workspace 永远拿不到证据 → consumed(防夜夜重复)
    assert list_unconsumed(croot) == []


def test_pipeline_single_flight(tmp_path):
    """并发第二次 run() 直接返回 None(单飞锁)。"""
    ws = tmp_path / "proj"; ws.mkdir()
    croot = tmp_path / "cands"
    _seed(croot, "a", "fix login bug", "run1aaaaaaaaaaaa", ws)
    events: list = []

    class _SlowRunner:
        def run(self, task, *, model_tier):
            import time as _t
            _t.sleep(0.05)
            class _R: pass
            r = _R(); r.pass_status = "passed"
            return r

    pipe = _mk_pipeline(tmp_path, _SlowRunner(), _SlowRunner(), events)

    async def _go():
        t1 = asyncio.create_task(pipe.run())
        await asyncio.sleep(0.01)
        t2 = asyncio.create_task(pipe.run())
        return await asyncio.gather(t1, t2)

    r1, r2 = asyncio.run(_go())
    assert (r1 is None) != (r2 is None)  # 恰好一个被锁拒绝
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/learning/test_dream_pipeline.py tests/protocol/test_event_golden.py -k dream -q --no-cov`
Expected: FAIL（ImportError / 无事件类）

- [ ] **Step 3: 实现**

`protocol/events.py` 追加（仿 `ProactiveSuggestionEvent` 的 dataclass 模式，确保进 serialize/deserialize 注册表——先看该文件 kind 注册机制）：

```python
@dataclass(frozen=True, slots=True)
class DreamProgressEvent:
    """Dream 夜间整合进度(daemon → client,SSE 推送,_conductor 通道)。"""
    kind = "dream_progress"
    stage: str    # scan | cluster | synthesize | promote | memory | done
    detail: str
    ts: float


@dataclass(frozen=True, slots=True)
class DreamReportEvent:
    """Dream 整合结果汇总(诚实计数,直接来自 DreamReport)。"""
    kind = "dream_report"
    units_total: int
    promoted: int
    rejected: int
    skipped: int
    memory_merged: int
    memory_archived: int
    report_path: str
    ts: float
```

`dream.py` 追加：

```python
@dataclass(frozen=True, slots=True)
class DreamReport:
    """一次 Dream 的诚实结果计数。"""
    units_total: int = 0
    promoted: int = 0
    rejected: int = 0
    skipped: int = 0
    memory_merged: int = 0
    memory_archived: int = 0
    report_path: str = ""


def has_material(candidates_root: Path, *, min_units: int = 1) -> bool:
    """材料门:候选区有未消费材料才值得建议(供 conductor_supervisor 过滤)。"""
    from argos_agent.learning.candidates import list_unconsumed
    return len(list_unconsumed(candidates_root)) >= min_units


class DreamPipeline:
    """夜间整合管道:① 聚类 → ② 综合 → ③ A/B 晋升 → ④ 记忆整理 → ⑤ 报告。

    全依赖注入(测试用 fake);单飞锁防并发;任何阶段异常 → 该单元 skipped,
    管道继续,绝不抛到 caller。
    """

    def __init__(self, *, candidates_root: Path, skills_root: Path,
                 memory_dir: Path, dreams_dir: Path,
                 runner_factory, narrate=None, broadcast_fn=None,
                 max_units: int = DEFAULT_MAX_UNITS) -> None:
        # runner_factory(hint: str | None) -> runner:hint=None 给 A 侧,
        # 非 None 给 B 侧(daemon 接线时内部包 HintedRunner)
        self._candidates_root = candidates_root
        self._skills_root = skills_root
        self._memory_dir = memory_dir
        self._dreams_dir = dreams_dir
        self._runner_factory = runner_factory
        self._narrate = narrate
        self._broadcast_fn = broadcast_fn
        self._max_units = max_units
        import asyncio
        self._lock = asyncio.Lock()

    async def _emit(self, kind: str, **payload) -> None:
        if self._broadcast_fn is None:
            return
        try:
            await self._broadcast_fn({"kind": kind, **payload})
        except Exception as e:  # noqa: BLE001
            log.warning("dream: 广播失败(%s): %s", kind, e)

    async def run(self) -> DreamReport | None:
        """跑一轮整合。已在跑 → 返 None(单飞)。"""
        import time as _t
        if self._lock.locked():
            log.info("dream: 已有整合在跑,本次跳过(单飞)")
            return None
        async with self._lock:
            from argos_agent.learning import candidates as _cands
            from argos_agent.learning import promotion_gate
            from argos_agent.memory.consolidate import consolidate

            await self._emit("dream_progress", stage="scan", detail="扫描候选区", ts=_t.time())
            cands = _cands.list_unconsumed(self._candidates_root)
            units = cluster_candidates(cands, max_units=self._max_units)
            await self._emit("dream_progress", stage="cluster",
                             detail=f"{len(units)} units", ts=_t.time())

            promoted = rejected = skipped = 0
            for unit in units:
                try:
                    cand = synthesize(unit, narrate=self._narrate)
                    if cand is None:
                        skipped += 1
                        continue
                    tasks, gone = build_eval_tasks(unit)
                    # workspace 永远拿不到证据 → 直接消费(防夜夜重复建议)
                    for s in gone:
                        _cands.mark_consumed(s.path, reason="workspace_gone")
                    if not tasks:
                        skipped += 1
                        continue
                    hint = cand.body_markdown
                    res = promotion_gate.promote(
                        candidate=cand, tasks=tasks,
                        runner=self._runner_factory(None),
                        runner_b=self._runner_factory(hint),
                        skills_root=self._skills_root,
                    )
                    live = [s for s in unit.sources if s not in gone]
                    if res.promoted:
                        promoted += 1
                        for s in live:
                            _cands.mark_consumed(s.path, reason="promoted")
                    elif res.reason.startswith("no_improvement"):
                        rejected += 1
                        for s in live:
                            _cands.mark_consumed(s.path, reason="rejected_ab")
                    else:
                        # runner_error 等临时性失败:不消费,下晚重试
                        skipped += 1
                    await self._emit("dream_progress", stage="promote",
                                     detail=res.reason, ts=_t.time())
                except Exception as e:  # noqa: BLE001 — 单元失败不挂管道
                    log.warning("dream: 单元整合失败(跳过): %s", e)
                    skipped += 1

            await self._emit("dream_progress", stage="memory", detail="记忆整理", ts=_t.time())
            try:
                mem = consolidate(self._memory_dir)
            except Exception as e:  # noqa: BLE001
                log.warning("dream: 记忆整理失败(跳过): %s", e)
                from argos_agent.memory.consolidate import ConsolidationReport
                mem = ConsolidationReport()

            report = DreamReport(
                units_total=len(units), promoted=promoted, rejected=rejected,
                skipped=skipped, memory_merged=mem.merged,
                memory_archived=mem.archived,
                report_path=self._write_report_line(
                    units=len(units), promoted=promoted, rejected=rejected,
                    skipped=skipped, mem=mem, ts=_t.time()),
            )
            await self._emit("dream_report",
                             units_total=report.units_total, promoted=report.promoted,
                             rejected=report.rejected, skipped=report.skipped,
                             memory_merged=report.memory_merged,
                             memory_archived=report.memory_archived,
                             report_path=report.report_path, ts=_t.time())
            return report

    def _write_report_line(self, *, units: int, promoted: int, rejected: int,
                           skipped: int, mem, ts: float) -> str:
        """报告落 ~/.argos/dreams/<YYYY-MM-DD>.jsonl(复用 jsonl_log 风格 best-effort)。"""
        import datetime
        try:
            self._dreams_dir.mkdir(parents=True, exist_ok=True)
            day = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
            p = self._dreams_dir / f"{day}.jsonl"
            from argos_agent.jsonl_log import append_jsonl  # 先确认函数名;不存在则直接 open("a") 写
            append_jsonl(p, {
                "ts": ts, "units_total": units, "promoted": promoted,
                "rejected": rejected, "skipped": skipped,
                "memory_merged": mem.merged, "memory_archived": mem.archived,
            })
            return str(p)
        except Exception as e:  # noqa: BLE001
            log.warning("dream: 报告落盘失败: %s", e)
            return ""
```

（`jsonl_log` 的实际函数名先 `grep -n "def " argos_agent/jsonl_log.py` 确认；对不上就用 `open("a")` 直写同语义。）

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/learning/ tests/protocol/ -q --no-cov`
Expected: PASS（全部）

- [ ] **Step 5: Commit**

```bash
rtk git add argos_agent/learning/dream.py argos_agent/protocol/events.py tests/learning/test_dream_pipeline.py tests/protocol/test_event_golden.py
rtk git commit -m "feat(learning): DreamPipeline 编排 + dream_progress/report 事件 + 报告落盘"
```

---

### Task 9: daemon 接线 — builtin order + 材料门 + confirm 路由 + /dream 端点 `[complex]`

**Files:**
- Modify: `argos_agent/daemon/conductor_supervisor.py`（builtin order 注册 + 材料门过滤）
- Modify: `argos_agent/daemon/server.py`（confirm 按 action 路由 + `POST /dream/run` + `GET /dream/report`）
- Test: `tests/conductor/test_daemon_wiring.py`（追加；沿用现有 fake broadcast / tmp orders_dir 风格，daemon 测试守 `ARGOS_NO_DAEMON=1` 与现有 xdist_group 标记纪律）

实现要点（动手前先读 `server.py` 路由分发段 `:262` 附近与 `_handle_confirm_suggestion` 全文 `:1331-1473`）：

1. **builtin order**：`ConductorSupervisor._run_loop()` 构造 `OrderStore` 后调用：

```python
def ensure_builtin_dream_order(store) -> None:
    """注册内置夜间 Dream order(幂等;用户可 disable,disable 后不复活)。"""
    if store.get("builtin-dream-nightly") is not None:
        return
    import time as _t
    from argos_agent.conductor.orders import StandingOrder
    store.add(StandingOrder(
        id="builtin-dream-nightly",
        utterance="夜间整合:跨 run 综合蒸馏 + 记忆整理(Dream)",
        kind="schedule", schedule="03:00", trigger_glob=None,
        goal_template="__dream__", enabled=True,
        created_at=_t.time(), last_fired_at=None, action="dream",
    ))
```

2. **材料门**：`_run_loop` 的 `for s in suggestions:` 前过滤：

```python
                for s in suggestions:
                    if getattr(s, "action", "run") == "dream":
                        from argos_agent.learning.dream import has_material
                        from argos_agent.learning.candidates import DEFAULT_ROOT
                        if not has_material(DEFAULT_ROOT):
                            continue  # 空料静默,不打扰用户
                    self._pending[s.id] = s
                    await self._emit_suggestion(s)
```

3. **confirm 路由**：`_handle_confirm_suggestion` 拿到 `s` 后、查 loop_factory 前插入：

```python
        if getattr(s, "action", "run") == "dream":
            return await self._confirm_dream(writer, suggestion_id, s)
```

`_confirm_dream`：构建 DreamPipeline（`runner_factory` 用 `EvalRunner` + `self._worktree` + components 的 loop_factory；hint 非 None 时包 `HintedRunner`；`narrate` 用 components 的 ModelClient：

```python
    def _build_narrate(self):
        """叙述层模型调用(cheap 路由意图;无 components → None,模板兜底)。"""
        if self._components is None:
            return None
        client = getattr(self._components, "model", None)
        if client is None:
            return None
        def _narrate(prompt: str) -> str:
            import asyncio as _a
            return _a.run_coroutine_threadsafe(  # 注意:若已在事件循环内,改用 await 形式
                client.complete([{"role": "user", "content": prompt}],
                                system="你是技能文档撰写者。只输出文字,不输出代码。"),
                _a.get_event_loop(),
            ).result(timeout=60)
        return _narrate
```

   ——**实现时把 narrate 做成 async 友好**：`DreamPipeline` 在 async 上下文里跑，最简是把 `narrate` 类型放宽为 sync 或 async callable，`synthesize` 处 `inspect.iscoroutinefunction` 分流；或 daemon 侧直接传 async 包装。以最简通过测试为准，不要引入线程。
   单飞被拒（`run()` 返 None）→ 409；启动成功 → `202 {"state": "dream_started", "suggestion_id": ...}`；`pop_suggestion` + 广播 `suggestion_confirmed`（复用现有事件，`run_id` 填 `"_conductor"`）。
4. **端点**：路由分发段加 `POST /dream/run`（手动触发，绕过 suggestion 但同样跑管道，owner 鉴权 `_require_owner`）和 `GET /dream/report`（读 `~/.argos/dreams/` 最新一行，无 → `{"report": null}`，诚实空态）。

- [ ] **Step 1: 写失败测试**（先写 wiring 测试：builtin order 幂等注册、材料门空料静默、dream confirm 不调 create_run 而是启动管道——仿 `test_daemon_wiring.py` 现有 fake 风格，包括 `_bcast` 收集事件断言）
- [ ] **Step 2: 跑 `uv run pytest tests/conductor/test_daemon_wiring.py -q --no-cov` 确认新增 FAIL**
- [ ] **Step 3: 按上述要点实现**
- [ ] **Step 4: 跑 `uv run pytest tests/conductor/ tests/daemon/ -q --no-cov` 确认 PASS**
- [ ] **Step 5: Commit**

```bash
rtk git add argos_agent/daemon/conductor_supervisor.py argos_agent/daemon/server.py tests/conductor/test_daemon_wiring.py
rtk git commit -m "feat(daemon): Dream 接线 — builtin夜间order+材料门+confirm路由+/dream端点"
```

---

### Task 10: TUI `/dream` + CLI twin `argos dream` `[standard]`

**Files:**
- Modify: `argos_agent/tui/app.py`（仿 `:642` 的 `elif cmd.name == "orders":` 模式加 `dream`；slash 注册表同步——先 grep 该文件 slash 命令注册结构）
- Create: `argos_agent/cli/dream.py`
- Modify: `argos_agent/__main__.py`（`sub.add_parser("dream", ...)` + dispatch，仿 `eval` 子命令接法）
- Test: TUI 命令测试仿现有 `/orders` 的测试位置与写法（grep `orders` in tests/ 定位）；CLI 测试创建 `tests/test_cli_dream.py`

行为：

- TUI `/dream` → daemon 模式 `POST /dream/run`，活动栏显示 `dream_progress`/`dream_report` 事件（事件已经走 `_conductor` SSE 通道，TUI 订阅处加两个 kind 的渲染分支）；inline 模式诚实提示 "Dream 需要 daemon 模式"。
- TUI `/dream status` → `GET /dream/report`，渲染最近报告或诚实空态。
- CLI `argos dream` → 不经 daemon：直接构建 `DreamPipeline`（`app_factory.build_components` 拿 model/skills 路径；无 key → `narrate=None` 模板兜底 + 提示），同步跑完打印报告表格；`argos dream --report` 只读最近报告。

- [ ] **Step 1: 写失败测试**（TUI：`/dream` 在 daemon session 下发 POST 的桩断言 + inline 模式诚实拒绝；CLI：`argos dream --report` 空态输出含 "暂无"）
- [ ] **Step 2: 确认 FAIL**
- [ ] **Step 3: 实现**
- [ ] **Step 4: `uv run pytest tests/test_cli_dream.py <TUI测试文件> -q --no-cov` PASS**
- [ ] **Step 5: Commit**

```bash
rtk git add argos_agent/tui/app.py argos_agent/cli/dream.py argos_agent/__main__.py tests/
rtk git commit -m "feat(ui): /dream 命令 + argos dream CLI twin"
```

---

### Task 11: 文档 + 全量门 `[trivial]`

**Files:**
- Create: `docs/dream.md`（一文档一特性：动机、铁律、数据流、目录布局、命令、消费规则、与 E4 防火墙的关系）
- Modify: `README.md`（"Self-test firewall (learning)" 节后加 "Dream nightly consolidation" 小节 + Commands 表加 `/dream`）
- Modify: `CLAUDE.md`（subpackage map 的 `learning/`、`conductor/` 行补 Dream 一笔；Commands 不变）
- Modify: `CHANGELOG.md`（Unreleased 加 feat 条目）

- [ ] **Step 1: 写 docs/dream.md（含上述全部小节，铁律原文引用 spec）**
- [ ] **Step 2: README / CLAUDE.md / CHANGELOG 同步（注意：版本号三处同步走 /ship，此处不动版本）**
- [ ] **Step 3: 全量门**

Run: `uv run pytest -n auto --dist loadgroup`
Expected: 仅 3 个已知环境红（desktop_smoke×2 + terminal_bench_docker×1）；覆盖率 ≥80%

- [ ] **Step 4: Commit**

```bash
rtk git add docs/dream.md README.md CLAUDE.md CHANGELOG.md
rtk git commit -m "docs: Dream 夜间整合 — 特性文档+README+CHANGELOG"
```

---

## Self-Review 记录

- **Spec 覆盖**：spec §1 材料模型+通电 → Task 2/3；§2 聚类综合 → Task 5；§3 A/B+消费规则 → Task 6/8；§4 记忆整理 → Task 7；§5 接线/UX → Task 4/9/10；§6 错误处理 → 各任务内嵌；§7 测试/文档 → 全任务 TDD + Task 11。反思断电修复（Task 1）是 spec 写作后的现场发现，属"材料模型"的前置依赖。
- **命名偏离**：spec 的 `kind` 字段实现为 `action`（避开 `StandingOrder.kind` 占用），Task 4 注明。
- **类型一致性**：`StoredCandidate`（T2 定义，T5/T6/T8 使用）、`DreamUnit`（T5 定义，T6/T8 使用）、`promote(runner_b=)`（T6 定义，T8 调用）、`has_material`（T8 定义，T9 调用）已对齐。
- **已知风险**（实现者注意）：① `_slugify_goal` 私有复用（T5 内注明备选）；② narrate 的 async 适配（T9 内注明，以最简过测试为准）；③ `entry.workspace` 字段名（T3 内注明先 grep registry）。
