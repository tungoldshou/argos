# Per-task model routing + effort — 实施计划

> Road-map #11 / spec `2026-06-07-per-task-routing-design.md` 的 TDD 实施计划。
> **9 任务,1 任务 = 1 commit,合计 +35 测试,0 新外部依赖**(stdlib only:
> `json` / `re` / `enum` / `dataclasses` / `collections.deque` / `pathlib` / `os.replace` /
> `dataclasses.replace`)。
>
> **本计划不动**:`ModelClient` 既有方法签名(`stream` / `complete` / `last_usage` /
> `__init__`)、`LoopConfig` 既有字段、`ApprovalGate` 既有签名、`core/loop.py` 既有
> 流程、`Config` 加载器签名(只在 build_components 加 effort 参数)。
>
> **新代码全部在**:`argos/routing/`(5 个新模块)+ `argos/core/models.py`
> + `core/loop.py` + `app_factory.py` + `__main__.py` 扩展 + `tui/commands.py` +
> `tui/app.py` + `tui/events.py`(`CostUpdate.tier_name` 新字段,默认空串保旧事件)。
>
> **不** git 跟踪运行时产物;**不**引入 sqlite / 新依赖 / daemon / MCP 路由。

## 0. 总览

| 任务 | 标题 | 估测 | 关键文件 | 测试文件 |
|---|---|---|---|---|
| T1 | `routing/` 骨架 + `TaskCategory` + `categorize()` 启发式 | 25 min | `routing/__init__.py` + `routing/categorizer.py`(新) | `test_routing_categorizer.py` |
| T2 | `RoutingConfig` 加载 + safe default + `set_category()` 原子写 | 25 min | `routing/config.py`(新) | `test_routing_config.py` |
| T3 | `RoutingResolver.resolve()` 3 层优先级 + tier 名 fail-closed | 15 min | `routing/resolver.py`(新) | `test_routing_resolver.py` |
| T4 | `ModelRouter` 懒构造 + `select()` + history + `tier_force_confirm` | 30 min | `routing/router.py`(新) + `routing/effort.py`(新) | `test_routing_router.py` |
| T5 | CLI `--effort` + `build_components` 接线 + `CostUpdate.tier_name` | 20 min | `__main__.py` + `app_factory.py` + `tui/events.py`(扩展) | `test_routing_loop_integration.py`(基础) |
| T6 | `AgentLoop` 注入 router 扩展(不修改流程) | 25 min | `core/loop.py`(扩展) + `app_factory.py`(扩展) | `test_routing_loop_integration.py`(补) |
| T7 | TUI `/routing` + `/routing set` + ActivityPanel tier 标签 | 30 min | `tui/commands.py` + `tui/app.py` + `tui/widgets/activity_panel.py`(扩展) | `test_tui_routing.py` |
| T8 | e2e 铁证:cheap/default/strong 三档切换 + strong→CONFIRM | 20 min | `tests/test_routing_e2e.py`(新) | (e2e) |
| T9 | 文档 + CHANGELOG + README + 验收 | 25 min | `CHANGELOG.md` + `docs/per-task-routing.md` + `README.md` | (e2e 已含) |

**关键不变量**(spec 灵魂,plan 全程守住):
- **不**改 `ModelClient` 既有方法 / `__init__` 签名(spec §21 锁)
- **不**改 `core/loop.py` 既有流程,只在循环顶部加 `if router` 短路(spec §10)
- **不**改 `LoopConfig` 既有字段;effort 拆 preset 填既有 max_steps + approval_level
- **tier 名 fail-closed**(拼错 → ConfigError 启动失败,防悄悄退化)
- **strong 强制 CONFIRM**(opt-in 默认开,tier_force_confirm=["strong"])
- **0 新依赖**(stdlib only)
- **1507 既有测试 0 破坏**(router 不注入 = 走原路径)

## 1. 任务 T1:`routing/` 骨架 + `TaskCategory` + `categorize()`

### 1.1 目标

- 新目录 `argos/routing/`
- `__init__.py`:`TaskCategory` 枚举(8 类)、公开 `categorize()` 函数
- `categorizer.py`:`_extract_tool_calls()` 抽 `tool_name`、`_classify()` 决策
- 8 类别穷尽覆盖 + 兜底 `SIMPLE_READ`
- 启发式只看静态文本,无 LLM 调用;任何异常都兜底,绝不抛

### 1.2 实现(节选)

`routing/__init__.py`:

```python
"""Per-task model routing(契约 §11;spec #11)。"""
from argos.routing.categorizer import TaskCategory, categorize

__all__ = ["TaskCategory", "categorize"]
```

`routing/categorizer.py`:

```python
"""任务分类(契约 §11;spec §5):从 (tool, code, phase, step) 推出 TaskCategory。"""
from __future__ import annotations

import ast
import enum
import re

LONG_RUN_THRESHOLD = 20


class TaskCategory(enum.Enum):
    FILE_EDIT = "file_edit"
    REFACTOR = "refactor"
    TEST_WRITE = "test_write"
    VERIFY = "verify"
    PLAN = "plan"
    LONG_RUN = "long_run"
    AUTO_CAPTURE = "auto_capture"
    SIMPLE_READ = "simple_read"


_TEST_MARKERS = ("assert ", "pytest", "def test_", "TestCase", "unittest")
_WRITE_RE = re.compile(r"write_file\((?P<q>['\"])(?P<path>.+?)(?P=q)\s*,\s*(?P<q2>['\"])(?P<content>.*?)(?P=q2)\)", re.DOTALL)
_EDIT_RE = re.compile(r"edit_file\((?P<q>['\"])(?P<path>.+?)(?P=q)\s*,\s*(?P<q2>['\"])(?P<old>.*?)(?P=q2)\s*,\s*(?P<q3>['\"])(?P<new>.*?)(?P=q3)", re.DOTALL)


def _tool_names(code: str | None) -> list[str]:
    """从代码块抓 first tool call(粗略). 复用 core/loop.extract_tool_names 是不可能的
    (私有),我们这里走更轻的 regex:抽 (\\w+)\\(( 即可,失败兜底 []. """
    if not code:
        return []
    m = re.search(r"(\w+)\(", code)
    return [m.group(1)] if m else []


def _line_count(s: str) -> int:
    return len(s.splitlines())


def _edit_scale(code: str) -> int | None:
    """edit_file 改了多少行。解析失败返 None(让上层兜底 FILE_EDIT)。"""
    m = _EDIT_RE.search(code)
    if not m:
        return None
    return _line_count(m.group("new")) - _line_count(m.group("old"))


def _write_lines(code: str) -> int | None:
    m = _WRITE_RE.search(code)
    if not m:
        return None
    return _line_count(m.group("content"))


def _has_test_marker(code: str) -> bool:
    return any(m in code for m in _TEST_MARKERS)


def categorize(*, tool: str | None = None, code: str | None = None,
               phase: str = "act", step: int = 0) -> TaskCategory:
    """(tool, code, phase, step) → TaskCategory。启发式,无 LLM 调用,异常兜底 SIMPLE_READ。"""
    try:
        if phase == "plan":
            return TaskCategory.PLAN
        if phase == "verify":
            return TaskCategory.VERIFY
        if step >= LONG_RUN_THRESHOLD:
            return TaskCategory.LONG_RUN
        if tool in ("run_command", "lsp_diagnostics"):
            return TaskCategory.AUTO_CAPTURE
        if code and _has_test_marker(code):
            return TaskCategory.TEST_WRITE
        if code and "edit_file(" in code:
            scale = _edit_scale(code)
            if scale is None or scale < 5:
                return TaskCategory.FILE_EDIT
            return TaskCategory.REFACTOR
        if tool in ("read_file", "search_files"):
            return TaskCategory.SIMPLE_READ
        if code and "write_file(" in code:
            return TaskCategory.FILE_EDIT
        return TaskCategory.SIMPLE_READ
    except Exception:  # noqa: BLE001 — 启发式永不该崩 run
        return TaskCategory.SIMPLE_READ
```

### 1.3 RED 测试(`tests/test_routing_categorizer.py`)

8 测试(每类一个)+ 兜底 + 异常:
- `test_categorize_plan_phase_returns_plan`
- `test_categorize_verify_phase_returns_verify`
- `test_categorize_long_step_returns_long_run`(step=25)
- `test_categorize_run_command_returns_auto_capture`
- `test_categorize_test_marker_returns_test_write`(code 含 `assert `)
- `test_categorize_edit_small_returns_file_edit`(scale < 5)
- `test_categorize_edit_large_returns_refactor`(scale >= 5)
- `test_categorize_read_tool_returns_simple_read`
- `test_categorize_no_code_no_tool_returns_simple_read`(兜底)
- `test_categorize_garbage_input_returns_simple_read`(异常兜底)

### 1.4 验证

```bash
rtk pytest tests/test_routing_categorizer.py -v
rtk pytest tests/ -q   # 全量 1507+ 仍绿
```

### 1.5 Commit

```
feat(routing): #11 T1 TaskCategory 枚举 + categorize() 启发式
```

## 2. 任务 T2:`RoutingConfig` 加载 + safe default + `set_category()` 原子写

### 2.1 目标

- 新 `routing/config.py`
- `RoutingConfig` 冻结 dataclass(default + by_category + by_tool + tier_force_confirm)
- `load_routing(config_dir: Path) -> RoutingConfig`:读 `config.json` 的 `routing` 段,
  缺则 safe default(零破坏)
- `save_routing(config_dir, config: RoutingConfig)`:原子写 `config.json` 的 `routing` 段
- `set_category(config_dir, category: TaskCategory, tier: str)`:快速改写(原子写)
- tier 名必须在 `config.models` 里 → fail-closed

### 2.2 实现(节选)

```python
"""Routing 配置:从 ~/.argos/config.json 的 routing 段读/写。"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from argos.config import ConfigError, load_config
from argos.routing.categorizer import TaskCategory


@dataclass(frozen=True, slots=True)
class RoutingConfig:
    default: str = "default"
    by_category: dict[str, str] = field(default_factory=dict)
    by_tool: dict[str, str] = field(default_factory=dict)
    tier_force_confirm: list[str] = field(default_factory=list)

    def is_force_confirm(self, tier: str) -> bool:
        return tier in self.tier_force_confirm


def load_routing(config_dir: Path) -> RoutingConfig:
    """从 config_dir/config.json 读 routing 段;缺则 safe default(零破坏)。"""
    config_dir = Path(config_dir).expanduser()
    cfile = config_dir / "config.json"
    if not cfile.exists():
        return RoutingConfig()  # safe default
    try:
        raw = json.loads(cfile.read_text())
    except json.JSONDecodeError as e:
        raise ConfigError(f"config.json 解析失败:{e}") from e
    routing = raw.get("routing")
    if not isinstance(routing, dict):
        return RoutingConfig()
    # 校验 known 字段
    default = routing.get("default") or "default"
    by_category = routing.get("by_category") or {}
    by_tool = routing.get("by_tool") or {}
    tier_force_confirm = routing.get("tier_force_confirm") or []
    for k, v in {**by_category, **by_tool}.items():
        if not isinstance(v, str):
            raise ConfigError(f"routing.{k} 的 tier 值必须是 str,得 {type(v).__name__}")
    for v in tier_force_confirm:
        if not isinstance(v, str):
            raise ConfigError("routing.tier_force_confirm 项必须是 str")
    # 校验 category 键必须在 8 枚举内
    valid_cats = {c.value for c in TaskCategory}
    for k in by_category:
        if k not in valid_cats:
            raise ConfigError(
                f"routing.by_category 的键 {k!r} 不在合法类别 {sorted(valid_cats)} 内")
    return RoutingConfig(
        default=default, by_category=dict(by_category),
        by_tool=dict(by_tool), tier_force_confirm=list(tier_force_confirm),
    )


def _validate_tier(tier: str, config_dir: Path) -> None:
    """tier 名必须在 config.models 里(fail-closed 防拼写退化)。"""
    cfile = config_dir / "config.json"
    if not cfile.exists():
        return  # 无 config.json 走 safe default,不强校验
    try:
        raw = json.loads(cfile.read_text())
    except json.JSONDecodeError as e:
        raise ConfigError(f"config.json 解析失败:{e}") from e
    models = raw.get("models") or {}
    if tier not in models:
        raise ConfigError(
            f"routing tier '{tier}' 不在 config.models {list(models)} 内(防拼写退化)")


def set_category(config_dir: Path, category: TaskCategory, tier: str) -> RoutingConfig:
    """原子改写 config.json 的 routing.by_category[category] = tier;返回新 config。"""
    _validate_tier(tier, config_dir)
    config_dir = Path(config_dir).expanduser()
    cfile = config_dir / "config.json"
    if not cfile.exists():
        raise ConfigError(f"无 {cfile},无法 set_category")
    raw = json.loads(cfile.read_text())
    routing = dict(raw.get("routing") or {})
    by_category = dict(routing.get("by_category") or {})
    by_category[category.value] = tier
    routing["by_category"] = by_category
    raw["routing"] = routing
    # 原子写:.tmp + os.replace
    tmp_fd, tmp_path = tempfile.mkstemp(dir=str(config_dir), suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w") as f:
            json.dump(raw, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, cfile)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return load_routing(config_dir)
```

### 2.3 RED 测试(`tests/test_routing_config.py`)

8 测试:
- `test_load_routing_no_file_returns_safe_default`
- `test_load_routing_no_routing_section_returns_safe_default`
- `test_load_routing_parses_all_fields`
- `test_load_routing_invalid_category_raises`
- `test_load_routing_garbage_json_raises`
- `test_set_category_writes_to_config_atomically`
- `test_set_category_unknown_tier_raises`(fail-closed 防拼写)
- `test_set_category_persists_across_reload`(写完再读,值一致)

### 2.4 验证

```bash
rtk pytest tests/test_routing_config.py -v
```

### 2.5 Commit

```
feat(routing): #11 T2 RoutingConfig 加载 + set_category 原子写 + tier fail-closed
```

## 3. 任务 T3:`RoutingResolver.resolve()` 3 层优先级

### 3.1 目标

- 新 `routing/resolver.py`
- `RouteDecision` 不可变记录
- `resolve(config, *, category, tool) -> RouteDecision` 3 层优先级
  by_tool > by_category > default;命中层标 source

### 3.2 实现(节选)

```python
"""Tier 解析:by_tool > by_category > default;命中层标 source(供 /routing 显示)。"""
from __future__ import annotations

from dataclasses import dataclass
from argos.routing.categorizer import TaskCategory
from argos.routing.config import RoutingConfig


@dataclass(frozen=True, slots=True)
class RouteDecision:
    category: TaskCategory
    tool: str | None
    tier: str
    source: str  # "by_tool" | "by_category" | "default"
    step: int = 0


def resolve(config: RoutingConfig, *, category: TaskCategory,
            tool: str | None) -> RouteDecision:
    if tool is not None and tool in config.by_tool:
        return RouteDecision(category, tool, config.by_tool[tool], "by_tool")
    if category.value in config.by_category:
        return RouteDecision(category, tool, config.by_category[category.value], "by_category")
    return RouteDecision(category, tool, config.default, "default")
```

### 3.3 RED 测试(`tests/test_routing_resolver.py`)

6 测试:
- `test_resolve_by_tool_wins_over_category`
- `test_resolve_by_category_used_when_no_tool`
- `test_resolve_default_when_no_match`
- `test_resolve_none_tool_skips_by_tool_layer`
- `test_resolve_decision_carries_source_label`
- `test_resolve_decision_carries_category_and_tool`

### 3.4 验证

```bash
rtk pytest tests/test_routing_resolver.py -v
```

### 3.5 Commit

```
feat(routing): #11 T3 RoutingResolver 3 层优先级 (by_tool > by_category > default)
```

## 4. 任务 T4:`ModelRouter` 懒构造 + `select()` + history + `tier_force_confirm`

### 4.1 目标

- 新 `routing/router.py`
- `ModelRouter` 类:clients dict 懒构造 + `select()` + `history()` + `tier_force_confirm`
- 新 `routing/effort.py`:`EffortLevel` 枚举 + `EFFORT_PRESETS` + `effort_settings()`

### 4.2 实现(节选)

`routing/effort.py`:

```python
"""Effort 等级(契约 §11;spec §8)。"""
from __future__ import annotations

import enum
from dataclasses import dataclass

from argos.approval import ApprovalLevel


class EffortLevel(enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class EffortSettings:
    max_steps: int
    approval_level: ApprovalLevel


EFFORT_PRESETS: dict[EffortLevel, EffortSettings] = {
    EffortLevel.LOW: EffortSettings(max_steps=8, approval_level=ApprovalLevel.AUTO),
    EffortLevel.MEDIUM: EffortSettings(max_steps=40, approval_level=ApprovalLevel.CONFIRM),
    EffortLevel.HIGH: EffortSettings(max_steps=80, approval_level=ApprovalLevel.CONFIRM),
}


def effort_settings(level: EffortLevel) -> EffortSettings:
    return EFFORT_PRESETS[level]
```

`routing/router.py`:

```python
"""ModelRouter:多个 ModelClient + RoutingConfig + history。

懒构造:首次 select() 某 tier 时才造 ModelClient(避免无 key 的 tier 启动即抛)。
history:deque(maxlen=10),本 run 内 /routing 读,run 终止即失(不持久化)。"""
from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable
from dataclasses import replace
from typing import TYPE_CHECKING

from argos.config import ConfigError
from argos.core.models import CredentialPool, ModelClient
from argos.routing.categorizer import TaskCategory
from argos.routing.config import RoutingConfig
from argos.routing.resolver import RouteDecision, resolve

if TYPE_CHECKING:
    pass

ClientFactory = Callable[[str], ModelClient]


class ModelRouter:
    def __init__(self, *, routing: RoutingConfig,
                 client_factory: ClientFactory) -> None:
        self._routing = routing
        self._client_factory = client_factory
        self._clients: dict[str, ModelClient] = {}
        self._history: deque[RouteDecision] = deque(maxlen=10)
        self._lock = threading.Lock()

    def select(self, *, category: TaskCategory, tool: str | None,
               step: int = 0) -> tuple[ModelClient, RouteDecision]:
        with self._lock:
            decision = resolve(self._routing, category=category, tool=tool)
            client = self._clients.get(decision.tier)
            if client is None:
                client = self._client_factory(decision.tier)
                self._clients[decision.tier] = client
            decision = replace(decision, step=step)
            self._history.append(decision)
            return client, decision

    def history(self) -> list[RouteDecision]:
        return list(self._history)

    @property
    def routing(self) -> RoutingConfig:
        return self._routing
```

### 4.3 RED 测试(`tests/test_routing_router.py`)

8 测试:
- `test_router_lazy_constructs_clients`
- `test_router_caches_client_across_selects`
- `test_router_select_returns_decision_with_step`
- `test_router_history_appends_and_caps_at_10`
- `test_router_history_returns_snapshot_not_deque`
- `test_effort_settings_low_medium_high_mapped`
- `test_effort_low_uses_auto_approval`
- `test_router_force_confirm_via_routing_config`(is_force_confirm → True)

### 4.4 验证

```bash
rtk pytest tests/test_routing_router.py -v
```

### 4.5 Commit

```
feat(routing): #11 T4 ModelRouter 懒构造 + history + EffortLevel 映射
```

## 5. 任务 T5:CLI `--effort` + `build_components` 接线 + `CostUpdate.tier_name`

### 5.1 目标

- `__main__.py` 加 `--effort` flag(默认 `medium`)
- `build_components` 接受 `effort: EffortLevel | None` 参数(无 = 默认 medium)
- `CostUpdate.tier_name: str = ""` 字段(默认空串保旧事件兼容)
- 不动既有 `ModelClient` / `LoopConfig`

### 5.2 实现(节选)

`__main__.py`:

```python
from argos.routing.effort import EffortLevel
...
p.add_argument("--effort", choices=[e.value for e in EffortLevel],
               default=EffortLevel.MEDIUM.value,
               help="任务努力档(low=8 步+AUTO;medium=40+CONFIRM;high=80+CONFIRM)")
...
effort = EffortLevel(args.effort)
components = build_components(..., effort=effort)
```

`app_factory.py:build_components`:

```python
from argos.routing.effort import EffortLevel, effort_settings
...
def build_components(*, ..., effort: EffortLevel = EffortLevel.MEDIUM) -> AppComponents:
    ...
    preset = effort_settings(effort)
    loop_config = LoopConfig(
        model_tier=tier.name, verify_cmd=verify_cmd,
        max_steps=preset.max_steps,
        max_rounds=max_rounds,
        ...
        approval_level=preset.approval_level,
    )
    ...
```

`tui/events.py:CostUpdate`:

```python
@dataclass(frozen=True, slots=True)
class CostUpdate:
    ...  # 既有字段
    tier_name: str = ""   # #11 per-task routing:实际跑这步的 profile
```

### 5.3 RED 测试(`tests/test_routing_loop_integration.py` 基础段)

- `test_effort_cli_flag_default_medium`
- `test_build_components_effort_low_uses_8_steps_auto`
- `test_build_components_effort_high_uses_80_steps_confirm`
- `test_cost_update_default_tier_name_empty`
- `test_cost_update_serialize_with_tier_name_round_trip`(replay 兼容)

### 5.4 验证

```bash
rtk pytest tests/test_routing_loop_integration.py -v
rtk pytest tests/ -q   # 1507+ 仍全绿
```

### 5.5 Commit

```
feat(routing): #11 T5 --effort CLI + build_components 接线 + CostUpdate.tier_name
```

## 6. 任务 T6:`AgentLoop` 注入 router 扩展(不修改流程)

### 6.1 目标

- `AgentLoop.__init__` 加可选 kw-only `router` 参数(默认 None)
- `_drive` 的 `while step < self._cfg.max_steps` 循环顶部加 `if router` 短路
- `self._current_tier` 字段跟踪每步实际 tier
- strong tier 触发 `_approval_level_override = CONFIRM`(复用 plan mode 字段)
- 既有 1507 测试 0 破坏

### 6.2 实现(节选)

`core/loop.py:AgentLoop.__init__`:

```python
def __init__(
    self, *, store, bus, sandbox, broker, model, verifier, config, workspace=None,
    verify_dir=None, allow_workflow=True, read_only=False, workflow_engine_factory=None,
    router: "ModelRouter | None" = None,   # #11
) -> None:
    ...
    self._router = router
    self._current_tier = config.model_tier   # 默认走原 tier;有 router 后每步重选
    self._approval_level_override = None      # 既有字段,复用
```

`core/loop.py:_drive` 循环顶部(在 `async for delta in self._model.stream(...)` 之前):

```python
# #11 per-task routing:每步按 (tool, code, phase) 选 tier;router 不存在时静默用既有 model。
if self._router is not None:
    code_so_far = text or ""
    code_block = extract_code_block(code_so_far) if code_so_far else None
    tool_names = extract_tool_names(code_block) if code_block else []
    primary_tool = tool_names[0] if tool_names else None
    phase = self._harness._current_phase if hasattr(self._harness, "_current_phase") else "act"
    try:
        client, decision = self._router.select(
            category=categorize(tool=primary_tool, code=code_block, phase=phase, step=step),
            tool=primary_tool, step=step,
        )
    except Exception:  # noqa: BLE001 — 路由失败走原 model,不挂 run
        client, decision = self._model, None
    self._current_tier = decision.tier if decision else self._cfg.model_tier
    if decision and self._router.routing.is_force_confirm(decision.tier):
        self._approval_level_override = ApprovalLevel.CONFIRM
    self._model = client
```

`core/loop.py:CostUpdate yield 处` 加 `tier_name=self._current_tier`:

```python
yield CostUpdate(
    tokens_in=self._tok_in, tokens_out=self._tok_out,
    cost_usd=cost, elapsed_s=time.time() - self._started,
    cache_read=self._cache_read, context_used=context_used,
    tier_name=self._current_tier,   # #11
)
```

`app_factory.py:AppComponents` 加 `router` 字段 + `build_components` 构造 router:

```python
from argos.routing.config import load_routing
from argos.routing.router import ModelRouter
...
def build_components(*, ..., effort=EffortLevel.MEDIUM) -> AppComponents:
    ...
    # Per-task routing(契约 §11):多个 ModelClient + 路由 config。
    config_dir = Path(os.environ.get("ARGOS_CONFIG_DIR") or Path.home() / ".argos")
    routing_cfg = load_routing(config_dir)
    # 拉所有可用 profile 名 → 构造 client_factory(懒)
    profile_names = config.list_profiles()
    def _client_factory(name: str) -> ModelClient:
        t = config.tier_for(name)
        k = config.key_for(name) or ""  # key 缺时 router.select 会失败
        return ModelClient(tier=t, pool=CredentialPool([k] or ["_missing_"]))
    router = ModelRouter(routing=routing_cfg, client_factory=_client_factory)
    ...
    return AppComponents(..., router=router)

def build_loop_factory(c):
    def factory() -> AgentLoop:
        return AgentLoop(
            store=c.store, ..., router=c.router,   # #11 透传
        )
    return factory
```

### 6.3 RED 测试(`tests/test_routing_loop_integration.py` 补段)

- `test_agent_loop_no_router_uses_existing_model`(既有路径,0 破坏)
- `test_agent_loop_with_router_emits_cost_update_tier_name`(每步 CostUpdate 带 tier)
- `test_agent_loop_strong_tier_sets_approval_level_override`
- `test_agent_loop_router_failure_falls_back_to_default_model`
- `test_app_factory_build_components_constructs_router`

### 6.4 验证

```bash
rtk pytest tests/test_routing_loop_integration.py -v
rtk pytest tests/ -q   # 1507+ 仍全绿
```

### 6.5 Commit

```
feat(routing): #11 T6 AgentLoop 注入 router 扩展 + strong 强制 CONFIRM
```

## 7. 任务 T7:TUI `/routing` + `/routing set` + ActivityPanel tier 标签

### 7.1 目标

- `tui/commands.py` 加 `routing` 进 `COMMAND_HELP` + 解析 `/routing set <cat> <tier>`
- `tui/app.py` 加 `action_routing` / `_cmd_routing` / `_cmd_routing_set`
- ActivityPanel 渲染 `CostUpdate` 时附 tier 标签(3 字母 + 颜色)
- 无 router 注入 → 友好提示,不报错(诚实)

### 7.2 实现(节选)

`tui/commands.py`:

```python
COMMAND_HELP["routing"] = "查看 / 切换路由配置(/routing, /routing set <cat> <tier>)"
```

`tui/app.py:action_routing`:

```python
def _cmd_routing(self) -> None:
    """无参:列 routing config + 最近 10 步决策。"""
    log = self.query_one(ActivityPanel)
    router = self._current_router()  # helper 拿 self._current_loop._router
    if router is None:
        asyncio.create_task(log.append_line(
            "/routing 不可用(无 router 注入;走 demo/fake 模式)。", kind="info"))
        return
    routing = router.routing
    lines = ["[Argos routing]"]
    lines.append(f"  default:        {routing.default}")
    if routing.by_category:
        lines.append("  by_category:")
        for k, v in routing.by_category.items():
            lines.append(f"    {k:14}→ {v}")
    if routing.by_tool:
        lines.append("  by_tool:")
        for k, v in routing.by_tool.items():
            lines.append(f"    {k:14}→ {v}")
    lines.append(f"  tier_force_confirm: {routing.tier_force_confirm}")
    lines.append("")
    lines.append("[最近 10 步决策]")
    for d in router.history():
        lines.append(f"  step {d.step:3}  cat={d.category.value:13} tool={d.tool or '-':14} → {d.tier:8} ({d.source})")
    asyncio.create_task(log.append_line("\n".join(lines), kind="info"))
```

`_cmd_routing_set`:

```python
def _cmd_routing_set(self, arg: str) -> None:
    """/routing set <category> <tier>"""
    parts = arg.split()
    if len(parts) != 2:
        asyncio.create_task(self.query_one(ActivityPanel).append_line(
            "用法:/routing set <category> <tier>", kind="error"))
        return
    cat_name, tier = parts
    try:
        category = TaskCategory(cat_name)
    except ValueError:
        asyncio.create_task(self.query_one(ActivityPanel).append_line(
            f"category '{cat_name}' 不存在;8 个合法值:"
            f"{[c.value for c in TaskCategory]}", kind="error"))
        return
    try:
        config_dir = Path(os.environ.get("ARGOS_CONFIG_DIR") or Path.home() / ".argos")
        set_category(config_dir, category, tier)
    except ConfigError as e:
        asyncio.create_task(self.query_one(ActivityPanel).append_line(
            f"/routing set 失败:{e}", kind="error"))
        return
    asyncio.create_task(self.query_one(ActivityPanel).append_line(
        f"已写入 {config_dir}/config.json:routing.by_category.{category.value} = {tier}", kind="info"))
```

`tui/widgets/activity_panel.py:CostUpdate 渲染` 加 tier 标签(`[cheap]` 绿 / `[strong]` 红 /
`[default]` 灰)。

### 7.3 RED 测试(`tests/test_tui_routing.py`)

- `test_parse_slash_routing_known`
- `test_parse_slash_routing_set_args`
- `test_routing_command_no_router_friendly_message`
- `test_routing_set_invalid_category_error`
- `test_routing_set_unknown_tier_error`
- `test_routing_set_persists`(写盘后再读一致)
- `test_activity_panel_cost_update_renders_tier_label`

### 7.4 验证

```bash
rtk pytest tests/test_tui_routing.py -v
rtk pytest tests/ -q
```

### 7.5 Commit

```
feat(tui): #11 T7 /routing + /routing set + ActivityPanel tier 标签
```

## 8. 任务 T8:e2e 铁证:cheap/default/strong 三档切换 + strong→CONFIRM

### 8.1 目标

- `tests/test_routing_e2e.py` 端到端铁证(spec §17.1):
  - 配 3 profile(cheap/default/strong)+ routing + tier_force_confirm=["strong"]
  - 跑一 run(脚本:edit + run + 完成 → verify)
  - 断言 tier 分配序列、CostUpdate.tier_name、strong → CONFIRM 行为

### 8.2 实现(节选)

```python
"""#11 per-task routing 端到端铁证。

mock 3 ModelClient(cheap/default/strong),配 routing.by_category 与 tier_force_confirm,
跑一 run(edit_file + run_command + 完成 → verify),断言:
1. step 0 (edit) → tier=cheap
2. step 1 (run_command) → AUTO_CAPTURE
3. step 2 (verify) → tier=strong + approval_level_override=CONFIRM
4. CostUpdate.tier_name 序列为 ["cheap", ..., "strong"]
5. strong 决策时,即使启动 AUTO 仍 yield ApprovalRequest
"""
import json
from pathlib import Path

import httpx
import pytest

from argos.approval import ApprovalLevel
from argos.config import save_config
from argos.core.loop import AgentLoop, LoopConfig
from argos.core.models import CredentialPool, ModelClient
from argos.routing.categorizer import TaskCategory
from argos.routing.config import RoutingConfig, set_category
from argos.routing.router import ModelRouter
from argos.tui.events import (
    ApprovalRequest, CostUpdate, EventBus, VerifyVerdict,
)


def _sse_transport(text_pieces: list[str]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        lines = []
        for piece in text_pieces:
            data = {"type": "content_block_delta", "delta": {"type": "text_delta", "text": piece}}
            lines.append(f"event: content_block_delta\ndata: {json.dumps(data)}\n")
        lines.append('event: message_stop\ndata: {"type":"message_stop"}\n')
        body = "\n".join(lines)
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
    return httpx.MockTransport(handler)


def _client(name: str, text: str) -> ModelClient:
    from argos.core.models import ModelTier
    tier = ModelTier(name=name, model=f"{name}-model", base_url="https://x/a", max_tokens=4096)
    return ModelClient(tier=tier, pool=CredentialPool(["key"]), transport=_sse_transport([text]))


def test_e2e_routing_strong_tier_forces_confirm(tmp_path):
    """三档切换 + strong→CONFIRM 端到端铁证。"""
    from argos.sandbox.broker import CapabilityBroker
    from argos.sandbox.egress import EgressPolicy
    from argos.sandbox.executor import SeatbeltExecutor
    from argos.tools.receipts import ReceiptSigner
    from argos.core.verify_gate import Verifier
    from argos.memory.store import ArgosStore

    ws = tmp_path / "ws"
    ws.mkdir()
    db = tmp_path / "a.db"
    store = ArgosStore(db_path=str(db))
    signer = ReceiptSigner(key=b"e2e")
    # routing config
    routing = RoutingConfig(
        default="default",
        by_category={"file_edit": "cheap", "verify": "strong", "auto_capture": "cheap"},
        tier_force_confirm=["strong"],
    )
    clients = {"cheap": _client("cheap", "ok"), "default": _client("default", "ok"),
               "strong": _client("strong", "ok")}
    def factory(name: str) -> ModelClient:
        if name not in clients:
            return _client(name, "ok")
        return clients[name]
    router = ModelRouter(routing=routing, client_factory=factory)

    # 注:不强校验 -- 这是 e2e,用 in-memory
    cfg = LoopConfig(model_tier="default", verify_cmd=None, max_steps=8, max_rounds=3,
                     approval_level=ApprovalLevel.AUTO, compaction=False)
    bus = EventBus()
    sandbox = SeatbeltExecutor(broker_handler=lambda a, b: None)
    broker = CapabilityBroker(
        gate=None,   # 强 tier 强制 CONFIRM 后由 harness 弹 ApprovalRequest
        egress=EgressPolicy(llm_hosts=set(), search_hosts=set(), mcp_hosts=set()),
        signer=signer,
    )
    # ... (脚本模型:edit_file + run_command + 完成)
    # 断言 CostUpdate.tier_name 序列含 cheap + strong
```

### 8.3 验证

```bash
rtk pytest tests/test_routing_e2e.py -v
rtk pytest tests/ -q
```

### 8.4 Commit

```
test(routing): #11 T8 e2e 铁证 — cheap/default/strong 三档切换 + strong→CONFIRM
```

## 9. 任务 T9:文档 + CHANGELOG + README + 验收

### 9.1 目标

- `CHANGELOG.md` 加 `[Unreleased]` 段
- 新建 `docs/per-task-routing.md` 详尽用户文档
- `README.md` 加一段"Per-task model routing"简介
- 跑全量测试 1507+ 验证

### 9.2 实现(节选)

`CHANGELOG.md` `[Unreleased]` 段:

```
### Added
- #11 per-task model routing:按 (category, tool) 自动选 tier(config.json `routing` 段)
- #11 effort levels:CLI `--effort=low|medium|high`,映射到 max_steps + approval_level
- #11 TUI `/routing` 命令:列 routing config + 最近 10 步决策;`/routing set <cat> <tier>` 快速改写
- #11 CostUpdate.tier_name 字段:每步成本归属具体 profile
- #11 strong tier 强制 CONFIRM(防拼写退化;tier_force_confirm 默认 `["strong"]`)
```

`docs/per-task-routing.md` 内容:
- 概述(为什么 + 怎么用)
- 配置 schema(完整 JSON 示例)
- 8 类别启发式表
- effort 等级表
- /routing 命令
- 故障排查(tier 不存在 / category 拼错 / strong 不弹 CONFIRM)
- 诚实防线(防假绿)

`README.md` 加一段:

```markdown
## Per-task model routing (#11)

Different tasks → different models. Configure in `~/.argos/config.json`:

\`\`\`json
{
  "routing": {
    "default": "default",
    "by_category": { "file_edit": "cheap", "verify": "strong" },
    "tier_force_confirm": ["strong"]
  }
}
\`\`\`

CLI: `argos --effort=high <goal>`.
TUI: `/routing` to see last 10 calls; `/routing set verify strong` to update.
```

### 9.3 验证

```bash
rtk pytest tests/ -q
rtk python -c "from argos.routing import categorize, TaskCategory; print(categorize(code='edit_file(...)', phase='act', step=3))"
```

### 9.4 Commit

```
docs(routing): #11 T9 文档 + CHANGELOG + README + 验收铁证
```

## 何时用

T1-T4 → 路由核心(0 依赖 + 0 接线);可独立验。
T5-T6 → loop/CLI 接线,改 `__main__.py` + `app_factory.py` + `core/loop.py` 既有
文件(扩展,不修改流程);既有 1507 测试 0 破。
T7 → TUI 扩展,改 `tui/commands.py` + `tui/app.py` + ActivityPanel widget(扩展)。
T8 → e2e 铁证,跑全链路。
T9 → 文档 + CHANGELOG + README。

**总计**:9 commit,5 新模块(`routing/__init__.py` + `categorizer.py` +
`config.py` + `resolver.py` + `router.py` + `effort.py`),1 e2e 测试,5 单测文件,
~35 测试,0 新依赖。

**不动清单**(契约 §9):
- `ModelClient` 既有方法 / `__init__` 签名(spec §21 锁)
- `core/loop.py` 流程(spec §10 锁)
- `LoopConfig` 字段
- `ApprovalGate` 签名
- `Config` 加载器签名
- `tui/commands.py` 既有 COMMAND_HELP(只加 "routing")
- `tui/events.py` 既有事件(只 CostUpdate 加 `tier_name: str = ""`)
