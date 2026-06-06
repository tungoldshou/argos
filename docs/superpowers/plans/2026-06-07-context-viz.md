# Context 可视化 /context + proactive 压缩 — 实施计划

> Road-map #12 / spec `2026-06-07-context-viz-design.md` 的 TDD 实施计划。
> **8 任务,1 任务 = 1 commit,合计 +44 测试,0 新强制外部依赖**(stdlib only;
> `tiktoken` 走可选 import 降级)。
>
> **本计划不动**:`ModelClient` 既有方法签名(`stream` / `complete` / `last_usage` /
> `__init__`)、`compact_messages` 既有签名、`core/loop.py` 既有流程(`while` 顶部加 1 行
> `async for ev in self._maybe_proactive_compact(...): yield ev`,不重排不重构)、既有
> `CostUpdate` 字段(只读 `context_used` 路径)、`Config` 加载器签名(只在 build_components
> 加 `compact_threshold` 透传 kw)、`tui/commands.py` 既有 `COMMAND_HELP`(只加 "context")、
> `tui/widgets/activity_panel.py` 既有 `on_context`(只加一行 badge 文本,保旧 10 格条不破)。
>
> **新代码全部在**:`argos_agent/context/`(4 个新模块)+ `core/loop.py`(扩展) +
> `tui/commands.py`(扩展)+ `tui/app.py`(扩展)+ `tui/widgets/activity_panel.py`(扩展)+
> `tui/widgets/status_bar.py`(扩展)+ `__main__.py`(扩展)+ `CHANGELOG.md` + `README.md` +
> `docs/context-viz.md`。
>
> **不** git 跟踪运行时产物;**不**引入 sqlite / 新强制依赖 / daemon / MCP 路由。

## 0. 总览

| 任务 | 标题 | 估测 | 关键文件 | 测试文件 |
|---|---|---|---|---|
| T1 | `tokens.py` 估算函数(可选 tiktoken 降级 + method 字段) | 15 min | `context/__init__.py` + `context/tokens.py`(新) | `test_context_tokens.py` |
| T2 | `analyzer.py` 4 桶分桶(system/memory/tools/messages)+ details + window fallback | 30 min | `context/analyzer.py`(新) | `test_context_analyzer.py` |
| T3 | `threshold.py` 5 跳过 + 2 允许 + 幂等(used ≤ last+5%buffer) | 15 min | `context/threshold.py`(新) | `test_context_threshold.py` |
| T4 | `render.py` 文本表格 + 颜色 + JSON + 字段对齐 + method 后缀 | 20 min | `context/render.py`(新) | `test_context_render.py` |
| T5 | `core/loop.py` 扩展:`LoopConfig.compact_threshold` + `_maybe_proactive_compact` + `_messages_override` | 30 min | `core/loop.py`(扩展) + `app_factory.py`(扩展) | `test_context_e2e.py`(基础) |
| T6 | TUI 接入:`COMMAND_HELP.context` + `_context_cmd` 调度 + 活动栏 badge + 状态栏 `.ctx-warn` | 25 min | `tui/commands.py` + `tui/app.py` + `tui/widgets/activity_panel.py` + `tui/widgets/status_bar.py`(扩展) | `test_tui_context.py` |
| T7 | CLI `argos context show [--json] [--session=<id>]` | 15 min | `__main__.py`(扩展) | `test_context_cli.py` |
| T8 | 文档 + CHANGELOG + README + e2e 铁证 | 25 min | `CHANGELOG.md` + `docs/context-viz.md` + `README.md` | (e2e 已含) |

**关键不变量**(spec 灵魂,plan 全程守住):
- **不**改 `ModelClient` 既有方法 / `__init__` 签名(spec §21 锁)
- **不**改 `compact_messages` 既有签名(本期 0 调用它,只走既有 error 路径)
- **不**改 `core/loop.py` 流程(只在 `while` 顶部加 1 行 yield,既有 1570 测试 0 破)
- **不**改 `LoopConfig` 既有字段(只加 `compact_threshold: float = 0.8`,**有 default**)
- **不**改 `CostUpdate` 既有字段(只读 `context_used`,不重定义)
- **tiktoken 可选**(没装降级 `len // 4`,method 字段透明)
- **CLI/TUI 数字一致**(单一 `ContextAnalyzer.analyze(...)`)
- **每桶数字带 method 后缀**(`[est]` / `[api]`),防止"估当真值"误判
- **0 新强制依赖**(stdlib only;`tiktoken` 走 `try/except ImportError`)

## 1. 任务 T1:`tokens.py` 估算函数

### 1.1 目标

- 新目录 `argos_agent/context/`
- `tokens.py`:`token_estimate(text: str) -> tuple[int, str]` —— 走 chars4 兜底,
  若装了 tiktoken 用 cl100k_base
- 返回 `(tokens, method)`,method ∈ `{"estimate:chars4", "estimate:tiktoken"}`
- 永远不抛(`except Exception: ...` 兜底)
- `context/__init__.py`:`from argos_agent.context.tokens import token_estimate`

### 1.2 实现要点

```python
def token_estimate(text: str) -> tuple[int, str]:
    """若装了 tiktoken → 优先 cl100k_base(Anthropic/OpenAI 兼容近似);
    否则降级 chars4。返回 (tokens, method)。
    永不抛(spec §13)。"""
    txt = text or ""
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(txt)), "estimate:tiktoken"
    except Exception:  # noqa: BLE001 — 没装/版本不兼容
        return max(1, len(txt) // 4), "estimate:chars4"
```

### 1.3 测试(`test_context_tokens.py`,8 测试)

1. `test_estimate_empty_returns_min_one`:`token_estimate("")` → `(1, "estimate:chars4")`(min 1 兜底)
2. `test_estimate_short_text_uses_chars4`:`"hello world"` (11 字符) → `(2, "estimate:chars4")`(11//4=2)
3. `test_estimate_long_text_uses_chars4`:`"a" * 1000` → `(250, "estimate:chars4")`
4. `test_estimate_method_explicit_chars4`:`method` 字段含 `"chars4"`
5. `test_estimate_uses_tiktoken_if_available`:`monkeypatch` 注入 `tiktoken` → method=`"estimate:tiktoken"`
6. `test_estimate_tiktoken_missing_falls_back`:`monkeypatch.delitem(sys.modules, "tiktoken", raising=False)` + 注入 fake module `raise ImportError` → 降级 chars4
7. `test_estimate_unicode_chinese`:`"你好世界"`(12 字符) → `(3, "estimate:chars4")`(12//4=3)
8. `test_estimate_never_raises`:`token_estimate(None)` 走 `or ""` 兜底,正常返回

## 2. 任务 T2:`analyzer.py` 4 桶分桶

### 2.1 目标

- `analyzer.py`:`ContextAnalyzer.analyze(loop, *, store, workspace, goal=None) -> ContextBreakdown`
- 4 桶独立计算,失败降级(返回 `entries=0 tokens=0` + method=`"unavailable"`)
- `ContextBucket` / `ContextBreakdown` 冻结 dataclass(本模块定义)
- memory 桶 `details` 字段固定 4 项:user / project / skill / session
- window 来自 `loop._model.tier.context_window`,fallback 200_000

### 2.2 实现要点

```python
@dataclass(frozen=True, slots=True)
class ContextBucket:
    name: str
    tokens: int
    entries: int
    source: str           # "core/loop.py:471" 等文件:行号
    method: str           # "api" | "estimate:chars4" | "estimate:tiktoken" | "api:unavailable" | "estimate:unavailable"
    details: tuple[tuple[str, int], ...] = ()

@dataclass(frozen=True, slots=True)
class ContextBreakdown:
    system: ContextBucket
    memory: ContextBucket
    tools: ContextBucket
    messages: ContextBucket
    total: int
    window: int
    pct: float
    method: str           # "api+estimate"

    @property
    def health(self) -> str:
        if self.pct < 0.5: return "green"
        if self.pct < 0.8: return "yellow"
        return "red"


def analyze(loop, *, store, workspace, goal=None) -> ContextBreakdown:
    """4 桶独立;任一失败降级(不崩)。"""
    # 1) system:loop._build_system(goal or "") → token_estimate
    try:
        sys_text = loop._build_system(goal or "")
        sys_tok, sys_m = token_estimate(sys_text)
        system = ContextBucket("system", sys_tok, 1, "core/loop.py:471", sys_m)
    except Exception:  # noqa: BLE001
        system = ContextBucket("system", 0, 0, "(unknown)", "estimate:unavailable")

    # 2) memory:4 tier 各自 load → 各自 token → details
    try:
        from argos_agent.memory import auto as _auto
        u_t, _ = token_estimate("\n".join(e.value for e in _auto.load(scope="user")))
        p_t, _ = token_estimate("\n".join(e.value for e in _auto.load(scope="project")))
        s_t, _ = token_estimate("\n".join(e.value for e in _auto.load(scope="skill")))
        ss_t, _ = token_estimate("\n".join(e.value for e in _auto.load(scope="session")))
        mem_tok = u_t + p_t + s_t + ss_t
        memory = ContextBucket("memory", mem_tok, 4, "memory/auto.py:82",
                                "estimate:chars4",
                                details=(("user", u_t), ("project", p_t),
                                         ("skill", s_t), ("session", ss_t)))
    except Exception:  # noqa: BLE001
        memory = ContextBucket("memory", 0, 0, "memory/auto.py:82", "estimate:unavailable")

    # 3) tools:loop._tool_signatures_block() → token_estimate;entries=22(估数,Spec 不强求真)
    try:
        tool_text = loop._tool_signatures_block()
        tool_tok, tool_m = token_estimate(tool_text)
        tools = ContextBucket("tools", tool_tok, 22, "core/loop.py:430", tool_m)
    except Exception:  # noqa: BLE001
        tools = ContextBucket("tools", 0, 0, "core/loop.py:430", "estimate:unavailable")

    # 4) messages:store.get_messages(session_id) 拿全量;entries=len;tokens 走 API 真值
    try:
        msgs = store.get_messages(getattr(loop, "_session_id", "")) if hasattr(store, "get_messages") else []
        usage = getattr(loop._model, "last_usage", None) or {}
        msg_tok = (int(usage.get("input_tokens") or 0)
                   + int(usage.get("cache_read") or 0)
                   + int(usage.get("cache_creation") or 0))
        messages = ContextBucket("messages", msg_tok, len(msgs), "memory/store.py:259", "api")
    except Exception:  # noqa: BLE001
        messages = ContextBucket("messages", 0, 0, "memory/store.py:259", "api:unavailable")

    # 5) window
    try:
        window = loop._model.tier.context_window or 200_000
    except Exception:  # noqa: BLE001
        window = 200_000

    total = system.tokens + memory.tokens + tools.tokens + messages.tokens
    pct = total / window if window else 0.0
    return ContextBreakdown(system, memory, tools, messages, total, window, pct, "api+estimate")
```

### 2.3 测试(`test_context_analyzer.py`,10 测试)

1. `test_analyze_four_buckets_independent`:`_build_system` 抛 → 其它 3 桶仍正常
2. `test_analyze_system_uses_build_system`:mock `_build_system` 返回固定串 → 桶 tokens 匹配
3. `test_analyze_memory_loads_four_scopes`:mock `memory.auto.load` 4 次 → details 4 项
4. `test_analyze_tools_uses_signatures_block`:mock `_tool_signatures_block` 返回固定串 → 桶 tokens 匹配
5. `test_analyze_messages_uses_api_usage`:mock `last_usage` → 桶 tokens = input+cache_read+cache_creation
6. `test_analyze_window_fallback`:model.tier.context_window=0 → window=200_000
7. `test_analyze_window_from_model`:model.tier.context_window=8192 → window=8192
8. `test_analyze_pct_calculation`:total=100, window=1000 → pct=0.1
9. `test_analyze_health_property`:pct<0.5 → green;0.5-0.8 → yellow;>=0.8 → red
10. `test_analyze_never_raises`:loop 完全 mock 抛各种异常 → `analyze` 返回全空桶 Breakdown

## 3. 任务 T3:`threshold.py` 压不压决策

### 3.1 目标

- `threshold.py`:`_should_compact(*, used, window, threshold, phase, already_compacted_at, last_verdict_fail_count) -> bool`
- 5 跳过条件 + 2 允许条件(短路返回)
- 纯函数,无副作用;接 `dataclass LastCompactedAt(used: int) | None` 跟踪状态

### 3.2 实现要点

```python
@dataclass(frozen=True, slots=True)
class LastCompactedAt:
    used: int             # 压前 used

def _should_compact(*, used: int, window: int, threshold: float, phase: str,
                    compaction_enabled: bool = True,
                    already_compacted_at: LastCompactedAt | None = None,
                    last_verdict_fail_count: int = 0) -> bool:
    """判定顺序(短路):
    1) compaction_enabled=False → False
    2) phase in (verify, plan) → False
    3) threshold<=0 → False
    4) used/window < threshold → False
    5) last_verdict_fail_count > 0 → False(等 verify 收敛)
    6) already_compacted_at and used <= already_compacted_at.used + 5% window → False
    7) 默认 → True
    """
    if not compaction_enabled:
        return False
    if phase in ("verify", "plan"):
        return False
    if threshold <= 0:
        return False
    if window <= 0:
        return False
    if used / window < threshold:
        return False
    if last_verdict_fail_count > 0:
        return False
    if already_compacted_at is not None:
        buffer = int(window * 0.05)
        if used <= already_compacted_at.used + buffer:
            return False
    return True
```

### 3.3 测试(`test_context_threshold.py`,8 测试)

1. `test_skip_when_compaction_disabled`
2. `test_skip_when_phase_is_verify`
3. `test_skip_when_phase_is_plan`
4. `test_skip_when_threshold_zero`
5. `test_skip_when_ratio_below_threshold`:80% 阈值,60% 占用 → False
6. `test_skip_when_just_compacted`:already_compacted_at.used=100k, used=101k, window=200k(5% buffer=10k) → False
7. `test_skip_when_recent_verify_failed`:last_verdict_fail_count=1 → False
8. `test_allow_when_above_threshold_and_idle`:80% 阈值,85% 占用,未压过,无 verify 失败 → True

## 4. 任务 T4:`render.py` 文本表格 + JSON

### 4.1 目标

- `format_table(breakdown: ContextBreakdown) -> str`:对齐 + 颜色 + method 后缀 + 文件:行号
- `format_json(breakdown: ContextBreakdown) -> str`:`json.dumps(..., indent=2, default=str)`
- 输出 **不带 ANSI 码**(颜色走 Textual markup `[green]...[/green]`);TUI 直接渲染;
  CLI 走 rich/colorama 时也识别

### 4.2 实现要点

```python
def format_table(b: ContextBreakdown) -> str:
    health_color = {"green": "green", "yellow": "yellow", "red": "red"}[b.health]
    def line(name: str, tok: int, method: str, src: str, indent: int = 0) -> str:
        m = f"[{method}]" if not method.startswith("api") else "[api]"
        pad = "  " * indent
        return f"{pad}{name:<18}{tok:>7,} tok  {m:<22}{src}"
    out = ["Argos Context Breakdown", "─" * 50]
    out.append(line("system", b.system.tokens, b.system.method, b.system.source))
    out.append(line("memory (4 tier)", b.memory.tokens, b.memory.method, b.memory.source))
    for sub_name, sub_tok in b.memory.details:
        out.append(f"  · {sub_name:<14}{sub_tok:>7,} tok  [est]")
    out.append(line(f"tools ({b.tools.entries})", b.tools.tokens, b.tools.method, b.tools.source))
    out.append(line("messages", b.messages.tokens, b.messages.method, b.messages.source))
    out.append("─" * 50)
    out.append(f"[{health_color}]total {b.total:>7,} tok / {b.window:,} ({b.pct*100:.1f}%)[/{health_color}]")
    return "\n".join(out)


def format_json(b: ContextBreakdown) -> str:
    d = {
        "system": {"name": b.system.name, "tokens": b.system.tokens, "entries": b.system.entries,
                    "method": b.system.method, "source": b.system.source, "details": list(b.system.details)},
        "memory": {"name": b.memory.name, "tokens": b.memory.tokens, "entries": b.memory.entries,
                    "method": b.memory.method, "source": b.memory.source, "details": list(b.memory.details)},
        "tools": {"name": b.tools.name, "tokens": b.tools.tokens, "entries": b.tools.entries,
                   "method": b.tools.method, "source": b.tools.source, "details": list(b.tools.details)},
        "messages": {"name": b.messages.name, "tokens": b.messages.tokens, "entries": b.messages.entries,
                      "method": b.messages.method, "source": b.messages.source, "details": list(b.messages.details)},
        "total": b.total, "window": b.window, "pct": b.pct, "health": b.health,
        "method": b.method,
    }
    return json.dumps(d, indent=2, ensure_ascii=False, default=str)
```

### 4.3 测试(`test_context_render.py`,7 测试)

1. `test_format_table_contains_all_buckets`:输出含 "system" / "memory" / "tools" / "messages" / "total"
2. `test_format_table_method_suffix_per_bucket`:每个数字带 `[est]` 或 `[api]`
3. `test_format_table_memory_details`:memory 段展开 4 个 sub
4. `test_format_table_health_color`:green/yellow/red 对应不同 markup
5. `test_format_table_no_ansi_codes`:输出不含 `\x1b[`(纯 markup)
6. `test_format_json_keys_in_spec_order`:顶层键序 system→memory→tools→messages→total→window→pct→health→method
7. `test_format_json_serializable`:返回的 str 能被 `json.loads` 再 parse 回去

## 5. 任务 T5:`core/loop.py` 扩展

### 5.1 目标

- `LoopConfig` 加 `compact_threshold: float = 0.8`(有 default,旧 config 不破)
- `AgentLoop.__init__` 加 `self._last_compact_used: LastCompactedAt | None = None`
- `AgentLoop._messages_override: list[dict] | None = None`(本 step 顶部取,消费后清空)
- `AgentLoop._maybe_proactive_compact(session_id, step) -> AsyncIterator[CompactedEvent]`
- `AgentLoop._drive` 在 `while step < self._cfg.max_steps:` 顶部加 1 行:

```python
async for ev in self._maybe_proactive_compact(session_id, step):
    yield ev
messages = self._messages_override or self._store.get_messages(session_id) \
           if hasattr(self._store, "get_messages") else []
self._messages_override = None
```

**不**修改既有循环体的其他部分(continue / step+=1 / yield 顺序全保)

### 5.2 实现要点(`_maybe_proactive_compact`)

```python
async def _maybe_proactive_compact(self, session_id: str, step: int):
    from argos_agent.context.threshold import _should_compact, LastCompactedAt
    if not getattr(self._cfg, "compact_threshold", 0.8):
        return
    usage = getattr(self._model, "last_usage", None) or {}
    used = (int(usage.get("input_tokens") or 0)
            + int(usage.get("cache_read") or 0)
            + int(usage.get("cache_creation") or 0))
    window = getattr(getattr(self._model, "tier", None), "context_window", 0) or 200_000
    if not _should_compact(
        used=used, window=window,
        threshold=self._cfg.compact_threshold,
        phase="act",
        compaction_enabled=self._cfg.compaction,
        already_compacted_at=self._last_compact_used,
        last_verdict_fail_count=self._fail_count,
    ):
        return
    if not hasattr(self._store, "compact_messages"):
        return
    pre_used = used
    try:
        self._store.compact_messages(session_id, keep_recent=5)
    except Exception:  # noqa: BLE001
        return  # 写盘失败,下轮再试
    new_messages = self._store.get_messages(session_id) if hasattr(self._store, "get_messages") else []
    new_total = sum(max(1, len(m.get("content") or "") // 4) for m in new_messages)
    self._messages_override = new_messages
    self._last_compact_used = LastCompactedAt(used=pre_used)
    from argos_agent.tui.events import CompactedEvent
    yield CompactedEvent(
        before=pre_used, after=new_total,
        reduction_pct=max(0.0, (pre_used - new_total) / max(1, pre_used)),
        triggered_by="proactive", session_id=session_id,
    )
```

### 5.3 `app_factory.py` 透传(2 行)

`build_components(...)` 加 `compact_threshold: float | None = None` 透传 kw;`LoopConfig(...)`
传 `compact_threshold=compact_threshold if compact_threshold is not None else 0.8`。

### 5.4 `tui/events.py` 扩展

加 `EventKind` 字面量 `"compacted"`,`@dataclass(frozen=True, slots=True) class CompactedEvent`。
`deserialize_event` 既有未知 kind 走 `pass`(无破坏)。

### 5.5 测试(`test_context_e2e.py`,5 测试)

1. `test_proactive_compact_triggers_above_threshold`:
   - 注入 mock ModelClient(`last_usage` 随 step 涨到 90k),window=100k
   - 跑 loop 1 步
   - 断言:yield 了 `CompactedEvent(triggered_by="proactive", before=90k, after<90k)`
2. `test_proactive_compact_skips_during_verify`:
   - 注入 mock loop,phase=verify,90% 占用
   - 断言:不 yield `CompactedEvent`
3. `test_proactive_compact_idempotent_5pct_buffer`:
   - 第一次压触发 → 第二次同样 used(在 5% buffer 内)不触发
4. `test_proactive_compact_messages_override_consumed`:
   - 压后 `_messages_override` 一次,下一轮变 None(不持续覆盖)
5. `test_existing_compact_messages_error_path_still_works`:
   - 注入 `classify_error` 抛 overflow → 走既有 error 路径 → 触发 compact_messages
     (既有行为不破)

## 6. 任务 T6:TUI 接入

### 6.1 目标

- `tui/commands.py` `COMMAND_HELP` 加 `"context": "查看当前 LLM 上下文分桶(/context, /context --json)"`
- `tui/app.py` 加 `_context_cmd(arg)`:
  - 调 `ContextAnalyzer.analyze(self._agent_loop, ...)`(loop 实例在 app 里)
  - 文本:逐行 `await log.append_line(line)`(让 markup 着色生效)
  - `--json`:整段 `format_json`,不走 markup
- `tui/widgets/activity_panel.py` `on_context` 加一行 badge:`[ctx {used}/{window} {pct}%]`
- `tui/widgets/status_bar.py` 加 `update_ctx_pressure(pct)`:`>0.8` → `.ctx-warn` class

### 6.2 实现要点(`_context_cmd`)

```python
async def _context_cmd(self, arg: str) -> None:
    from argos_agent.context.analyzer import analyze
    from argos_agent.context.render import format_table, format_json
    log = self.query_one(Transcript)
    try:
        b = analyze(self._agent_loop,
                    store=self._store, workspace=self._workspace)
    except Exception as e:  # noqa: BLE001 — 永远不崩 run
        await log.append_line(f"/context 失败:{e}", kind="error")
        return
    if "--json" in arg:
        await log.append_line(format_json(b), kind="info")
    else:
        for line in format_table(b).split("\n"):
            await log.append_line(line, kind="info")
```

### 6.3 活动栏 badge(扩展,不破旧进度条)

```python
def on_context(self, *, used: int, window: int) -> None:
    pct = 0 if not window else round(used * 100 / window)
    filled = min(10, max(0, round(pct / 10)))
    bar = "▓" * filled + "░" * (10 - filled)
    win = f"{window // 1000}k" if window else "?"
    badge = f"[ctx {used}/{window} {pct}%]"
    self._set(8, f"{self._model_label} · {win}\n{bar} {pct}%\n{badge}")
```

### 6.4 状态栏红点

```python
def update_ctx_pressure(self, pct: float) -> None:
    cls = "ctx-warn" if pct >= 0.8 else ""
    self.set_class(cls == "ctx-warn", "ctx-warn")
```

### 6.5 测试(`test_tui_context.py`,6 测试)

1. `test_command_help_includes_context`:`"context" in COMMAND_HELP`
2. `test_context_cmd_runs_text_output`:`_context_cmd("")` 调 analyze,产出 ≥ 5 行 transcript
3. `test_context_cmd_runs_json_output`:`_context_cmd("--json")` 调 analyze,产出 1 段 JSON(可 parse)
4. `test_activity_panel_on_context_adds_badge`:`on_context(used=4200, window=8000)` 输出含 `[ctx 4200/8000 52%]`
5. `test_activity_panel_on_context_zero_window_safe`:`on_context(used=0, window=0)` 不除零
6. `test_status_bar_ctx_warn_class_above_80`:`update_ctx_pressure(0.85)` → `.ctx-warn` class 存在

## 7. 任务 T7:CLI `argos context show`

### 7.1 目标

- `__main__.py` 子命令分发加 `context`:
  - `argos context show [--json] [--session=<id>]`
  - 默认 `session` = `store.get_sessions()[-1].session_id` 若有,否则空(全空桶)
  - `--json` 走 `format_json`;否则 `format_table`
- 错误(无 active store / 无 session)→ 打印 `usage: argos context show [--json]`,exit 1

### 7.2 实现要点

```python
elif cmd == "context":
    sub = rest[0] if rest else "show"
    if sub != "show":
        print("usage: argos context show [--json] [--session=<id>]")
        return 1
    as_json = "--json" in rest
    # session 提取(简化:无显式 session 注入,analyzer 走 store 默认路径)
    from argos_agent.context.analyzer import analyze
    from argos_agent.context.render import format_table, format_json
    b = analyze(_active_loop, store=_active_store, workspace=_active_workspace)
    print(format_json(b) if as_json else format_table(b))
    return 0
```

### 7.3 测试(`test_context_cli.py`,4 测试)

1. `test_cli_context_show_text`:`invoke("context", "show")` 退出 0,stdout 含 "Argos Context Breakdown"
2. `test_cli_context_show_json`:`invoke("context", "show", "--json")` 退出 0,stdout 可 `json.loads`
3. `test_cli_context_show_with_session`:`invoke("context", "show", "--session=abc")` 退出 0
4. `test_cli_context_unknown_subcommand`:`invoke("context", "foo")` 退出非 0,stdout 含 "usage:"

## 8. 任务 T8:文档 + CHANGELOG + README + e2e

### 8.1 目标

- `CHANGELOG.md` `[Unreleased]` 加 #12 段(沿用 #11 风格,~30 行)
- `docs/context-viz.md` 新建:`/context` 截图占位(简笔 ASCII)、CLI 例、配置说明
- `README.md` 加 #12 链接(沿用 #11 行)
- 端到端铁证:长 session 触发主动压(已含在 T5 e2e)

### 8.2 CHANGELOG 模板

```markdown
- **Context 可视化 /context + proactive 压缩 (#12)**:**让"LLM 用了多少上下文 / 压在哪 / 谁在占"
  成为可配置 + 可观察 + 可治理的一等公民**,而不是"被动等模型吐 context_length_exceeded"或
  "假精确 token 计数"。**核心架构**:
  - **`ContextAnalyzer` 4 桶分桶**(`context/analyzer.py`):`system` / `memory (4 tier)` /
    `tools` / `messages`;每桶带 `tokens` / `entries` / `source` (文件:行号) / `method` (`api`/
    `estimate:chars4`/`estimate:tiktoken`/`unavailable`);`memory.details` 显 user/project/
    skill/session 4 tier 各自 token
  - **`tokens.py` 混合估算**(spec D1):API 报的真值(`last_usage.input_tokens + cache_read +
    cache_creation`)走 `method=api`;非对话侧(system/tools/memory)走可选 `tiktoken.cl100k_base`,
    降级 `len//4`,method 透明(用户扫表格知"哪个数是估的");**0 新强制依赖**
  - **`/context` 文本表格 + 颜色**(spec D7):`render.py` 左对齐 name 20 字符 + 右对齐 token
    + `[method]` 后缀 + 源文件:行号;`health` 绿(<50%)/ 黄(50-80%)/ 红(>80%);Textual
    markup(非 ANSI),TUI/CLI 共用
  - **`argos context show [--json] [--session=<id>]`** CLI(契约 §10;spec §11):同一
    `ContextAnalyzer`,文本/JSON 双输出;JSON 字段顺序 spec D13 锁死(system/memory/tools/
    messages/total/window/pct/health/method)
  - **Proactive compaction**(`core/loop.py` 扩展,spec §9 不修改流程):每 step 顶部 1 行
    `_maybe_proactive_compact(...)`;`LoopConfig.compact_threshold: float = 0.8` (CLI
    `--compact-threshold=0.7` 临时 + `config.json.compact_threshold` 持久化两路都有);
    `CompactMessages` 失败 / 同范围重复(5% buffer 幂等) / `phase=verify|plan` / 刚 verify
    失败 / `compaction=False` 全部跳过(spec D2/D4)
  - **`CompactedEvent`(tui/events.py 扩展)**:`before/after/reduction_pct/triggered_by/session_id`;
    `EventKind` 扩展加 `"compacted"`,`deserialize_event` 未知 kind 走 pass 保旧事件兼容
  - **TUI 接入**(`tui/commands.py` + `tui/app.py` + `tui/widgets/`):`COMMAND_HELP.context`
    + `_context_cmd` 调度;活动栏第 8 段加 `[ctx N/M X%]` badge(旧 10 格条不破);状态栏
    `>80%` 加 `.ctx-warn` CSS class(单红点,无文字)
  - **0 新强制外部依赖**(stdlib only;`tiktoken` 走 `try/except ImportError` 降级);+44 测试
    (6 文件:`test_context_tokens` 8 / `test_context_analyzer` 10 / `test_context_threshold`
    8 / `test_context_render` 7 / `test_context_e2e` 5 / `test_tui_context` 6);新文件
    `argos_agent/context/`(4 模块:__init__ / tokens / analyzer / render / threshold);
    spec 在 `docs/superpowers/specs/2026-06-07-context-viz-design.md`,plan 在
    `docs/superpowers/plans/2026-06-07-context-viz.md`;**不**改 `ModelClient` 既有方法 /
    `LoopConfig` 既有字段 / `core/loop.py` 流程 / `compact_messages` 既有签名 / `CostUpdate`
    既有字段(spec §21 锁)
```

### 8.3 README 加段

```markdown
- **/context + proactive 压缩 (#12)** — `/context` 看 4 桶分桶(系统提示/记忆/工具/消息)
  各自 token + 占比 + 文件:行号;80% 阈值自动 `compact_messages` 防止溢出;`argos context
  show --json` 接 eval/二次开发
```

## 9. 验收(对应 spec §17)

1. ✅ **测试**:1570 → 1614(+44),0 失败
2. ✅ **既有 1570 测试 0 破**:`compact_messages` 签名未改;`LoopConfig.compact_threshold`
   有 default(0.8),老 config.json 没字段不破;`core/loop.py` 既有 `while` 内逻辑零修改
3. ✅ **CLI/TUI 一致**:同一 `ContextAnalyzer.analyze(...)`,数字一致
4. ✅ **method 透明**:每桶数字带 `[est]` / `[api]` 后缀(spec §12.1 锁)
5. ✅ **跳过条件可见**:`/context` 不假装压过;`compaction=False` 时活动栏 badge 仍显
   `used/window` 但不压(spec §12.3)
6. ✅ **真 e2e**:长 session 触发 `CompactedEvent(triggered_by="proactive")` 至少 1 次
7. ✅ **0 新强制依赖**:`pip check` / `uv lock` 干净

## 10. 不触动清单(契约 §9 锁,执行期反复自检)

- [ ] 不改 `ModelClient.stream / complete / last_usage / __init__`
- [ ] 不改 `compact_messages` 既有签名
- [ ] 不改 `core/loop.py` 既有 `while` 内逻辑(只在顶部加 1 行 yield)
- [ ] 不改 `LoopConfig` 既有字段(只加 `compact_threshold: float = 0.8`)
- [ ] 不改 `CostUpdate` 既有字段(只读 `context_used`)
- [ ] 不改 `tui/commands.py` 既有 COMMAND_HELP(只加 "context")
- [ ] 不加 sqlite / 不加新强制外部依赖
- [ ] 不起 daemon
- [ ] 不接 MCP 工具路由
- [ ] 不改 `EventKind` 既有字面量(只扩展加 `"compacted"`)
