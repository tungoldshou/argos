# Context 可视化 `/context` + proactive 压缩 — 设计规格(spec)

> Road-map entry **#12** "Context 可视化 /context + proactive 压缩(短+短)" 的设计规格。
> 估时 1.5 天,小。两个小特性拼一个 spec:**让用户**看见 LLM 用了多少上下文、压在哪;**让 Argos**
> 在超阈值时主动压缩,而不是被动等模型吐 `context_length_exceeded`。

## 1. 背景与现状

- **v0.1.0 已发**,1570 测试绿。`CostUpdate.context_used` 已经在每步报"当前窗口输入侧
  token 数(input + cache_creation + cache_read)";`ActivityPanel.on_context` 已经在活动
  栏第 8 段画 10 格进度条(`▓▓▓▓░░░░░░ 47%`)。
- **`compact_messages(session_id, keep_recent=5)` 已经存在**:`memory/store.py:267`,
  折叠老 user/assistant 消息成一条摘要,保留最近 N 条。`core/loop.py:613` 在
  `classify_error(ce).should_compress` 触发(模型吐 `context_length_exceeded`)**被动**
  调一次,上限 3 次。
- **当前缺口**:
  1. **看不见** — 用户只能看活动栏"47%"的单数字,不知道"47% 都是什么":是 system prompt
     大、还是 memory 占、还是 messages 长?没法 debug"为什么 47%?"
  2. **算错** — `context_used` 是当前**窗口**(input+cache),不是**会话累计**;新用户扫一眼
     容易当成"已用总 token",实际"会话累计 = _tok_in"在 cost 区。两个数字挨着,容易混
  3. **压不动** — 压只被动:模型吐 `context_length_exceeded` 才压。三次压不动就死。贵的
     模型(`MiniMax-M2`)窗口小(200k),单次任务只要不超就 OK;便宜的(8k)只要多轮
     read_file + 多 write 反馈就超。用户希望"快到 80% 时**主动**压,别等爆"
  4. **无成本/质量对照** — 压了省多少?压在哪一段?用户不知道
  5. **缺 CLI 导出** — 想接 M3 / Cursor / Codex 二次开发的人没机器可读格式
- **风险**:
  1. **压丢上下文** — 摘要截断("前 60 字"拼接)是真损;压在 verify / plan 阶段会破坏
     "verifier 看到的是完整对话"这条契约
  2. **重复压** — 长会话 80% 触发一次,下一次 step 又 80%(内容没换)再压,反喂
     `compact_messages` 浪费 IO;要"本 session 已压过同范围不重压"
  3. **算错 token** — `last_usage.input_tokens` 来自 API 返回,准确;但**预估算**(system
     prompt / memory / tool sigs)要走启发式,不能假精确;spec 锁"估算法 + 误差诚实标注"
  4. **CLI/TUI 两路 drift** — `/context`(TUI) vs `argos context show`(CLI) 出不一致
     的数字 → 用户不信任。spec 锁"单一 `ContextAnalyzer`,TUI/CLI 共用"
- **灵魂**:不跟 Claude Code 抄"我们画了一个超漂亮 5 维仪表盘"——CC 是营销驱动,真用户只关心
  "我快用完了吗 / 还能用多久 / 谁在占"。也不抄 ChatGPT 那种"猜你想压缩"打扰弹窗;只做
  "看得见的桶 + 主动防爆"两件硬事,把"透明 + 防爆"做成**可配置 + 可观察 + 可治理**的一等公民。

## 2. 目标与非目标

### 2.1 目标(本期)

1. **`ContextAnalyzer`** 单模块(`context/analyzer.py`)输入 `(loop, store, workspace, goal)` →
   `ContextBreakdown(system, memory, tools, messages, total, window)`,4 桶 + 总 + 窗口。
   每桶带 `tokens`、`entries`(条数)、`source`(文件:行号)
2. **Token 估算** 混合策略:API `last_usage` 拿 input/cache 真值;非对话侧(系统提示 /
   memory / tools)走 `len(text) // 4`(英文 4 字符/token 经验值,中文 1.5 字符/token)
   + `cl100k_base`/`o200k_base`/`tiktoken`(若已装)优先;**估算法对每个数字带 `method`
   字段**(`api` / `estimate`)。**不**给假精确
3. **`/context` 文本表格**(`context/render.py`):对齐 + 颜色 + 文件:行号,green<50%,
   yellow 50-80%,red>80%
4. **Proactive compaction** `core/loop.py` 扩展(不修改流程,spec §9):每 step 顶部
   `_maybe_proactive_compact(...)` 查 `used / window > threshold` → 调 `compact_messages`
   → yield `CompactedEvent(before, after, reduction_pct, triggered_by="proactive")`
5. **阈值可配** `LoopConfig.compact_threshold: float = 0.8`(默认 0.8);CLI
   `--compact-threshold=0.7` 临时覆盖;`config.json.compact_threshold` 持久化
6. **Skip 条件**:
   - 已在本 session 压过相同/更大的范围 → skip(spec D2 幂等)
   - 当前 phase == "verify" / "plan" → skip(spec D4 不破坏门禁/规划阶段)
   - `compaction=False` → 全程不压(spec §9 loop 短路)
7. **TUI 接入** `tui/commands.py` 加 `context` 命令,`app.py` 调度 `_context_cmd(...)` 调
   `ContextAnalyzer.analyze()` → 推文本到 transcript(line by line 着色)
8. **活动栏** 第 8 段进度条左侧加 `[ctx 4200/8000 52%]` 文本(`on_context` 改);
   状态栏 80%+ 显红点(spec §10 装饰最小化)
9. **CLI 子命令** `argos context show [--json] [--session=<id>]` 走同一 `ContextAnalyzer`,
   文本/JSON 双输出;`--session` 默认当前 session
10. **0 新外部依赖**(stdlib only: `json` / `dataclasses` / `enum` / `pathlib` / `re` /
    `dataclasses.replace`)。tiktoken 走 **可选 import**(`try/except ImportError`),没装就
    降级 `len // 4` + method=`estimate`
11. **不**改 `compact_messages` 既有签名 / **不**改 `ModelClient` 既有方法 / **不**改
    `core/loop.py` 流程 / **不**改 `CostUpdate` 既有字段(扩展不破,spec §21 锁)
12. **不**加 sqlite / **不**起 daemon / **不**接 MCP 工具路由 / **不**起新 EventBus
    channel(`CompactedEvent` 走 `workflow_progress` 旁路但单 dataclass,spec §9.4)

### 2.2 非目标(本期不做)

- ❌ **LLM 摘要中间段** — 现有 `compact_messages` 走"前 60 字"截断;v1.1 接 LLM
  summarization(本期 §15 风险中说明)
- ❌ **per-tool token 拆分** — `/context` 只看 4 桶,不细分 22 工具各自 token(spec D1 简化)
- ❌ **多模态(pdf/image)token** — vision token 估算法不准,本期只看文本
- ❌ **跨 session 上下文共享分析** — 单 session 内;v1.1 接 `#5b` 多 run 视图
- ❌ **自动按历史成功率调阈值** — v1 静态 `compact_threshold`;v1.1 接 eval + 自动调
- ❌ **per-project override** — 暂只 `~/.argos/config.json` 全局
- ❌ **LLM-judge "这该不该压"** — 启发式 + 阈值就够,LLM-judge 自身要 token 违背省钱目标

## 3. 架构总览

```
                ┌──────────────────────────────────────┐
                │   ~/.argos/config.json                 │
                │   { "models":{...},                    │
                │     "compact_threshold": 0.8 }        │
                └──────────────┬───────────────────────┘
                               │ 加载
                               ▼
              ┌────────────────────────────────────────┐
              │       context/                           │
              │                                         │
              │  analyzer.py   ─ ContextAnalyzer         │
              │                  = 4 桶(系统/记忆/工具/   │
              │                    消息)+ total + window  │
              │                  + 每桶 source(file:line) │
              │                  + 每桶 method(api/est)   │
              │  tokens.py     ─ token_estimate(text)     │
              │                  + tiktoken 可选降级      │
              │  render.py     ─ format_table(breakdown)  │
              │                  + 颜色 / --json          │
              │  threshold.py  ─ _should_compact(...)?     │
              │                  + skip-if-already-compact │
              │                  + skip-during-verify     │
              └──────────────┬──────────────────────────┘
                               │
                               ▼
        ┌────────────────────────────────────────────┐
        │  core/loop.py(扩展:不修改流程)             │
        │  · 每 step 顶部调 _maybe_proactive_compact  │
        │  · 超阈值 → 调 compact_messages + 重载 msgs │
        │  · yield CompactedEvent(before,after,...)  │
        │  · cost 旁路标 triggered_by='proactive'     │
        └──────────────┬──────────────────────────┘
                               │
                               ▼
        ┌────────────────────────────────────────────┐
        │  TUI /context 命令                          │
        │  · 调 ContextAnalyzer.analyze()             │
        │  · 文本表格 → transcript(逐行 markup)      │
        │  · 活动栏 [ctx N/M X%] badge                │
        │  · 状态栏 80%+ 红点                         │
        └────────────────────────────────────────────┘
                               │
                               ▼
        ┌────────────────────────────────────────────┐
        │  CLI: argos context show [--json]           │
        │  · 同一 ContextAnalyzer                     │
        │  · stdout 文本 / json(走 format_table)     │
        └────────────────────────────────────────────┘
```

## 4. 数据结构

### 4.1 `ContextBucket` 不可变记录(spec §4.1)

```python
@dataclass(frozen=True, slots=True)
class ContextBucket:
    name: str               # "system" | "memory" | "tools" | "messages"
    tokens: int             # 估算/真值
    entries: int            # 条数(memory 4 tier 算 1 个 bucket 但 entries=4 子段)
    source: str             # 文件:行号(便于 debug),例 "core/loop.py:471"
    method: str             # "api" | "estimate"(每个数字带诚实标注)
    # spec D5:可携带 details 子段(memory 4 tier 各自 tokens;messages 各角色)
    details: tuple[tuple[str, int], ...] = ()
```

### 4.2 `ContextBreakdown`(spec §4.2)

```python
@dataclass(frozen=True, slots=True)
class ContextBreakdown:
    system: ContextBucket       # 系统提示(估算)
    memory: ContextBucket       # 4 tier 记忆(估算,带 tier1/tier2/tier3/tier4 details)
    tools: ContextBucket        # 22 工具签名(估算)
    messages: ContextBucket     # user+assistant 历史;tokens 走 API 拿的 input+cache
    total: int                  # 4 桶求和(跟 API input+cache 校准,允许 ±10% 误差)
    window: int                 # 当前模型 context_window
    pct: float                  # total/window,0-1
    method: str                 # 总体口径 "api+estimate"

    @property
    def health(self) -> str:    # "green" | "yellow" | "red"
        if self.pct < 0.5: return "green"
        if self.pct < 0.8: return "yellow"
        return "red"
```

### 4.3 `CompactedEvent`(spec §4.3)

```python
@dataclass(frozen=True, slots=True)
class CompactedEvent:
    kind = "compacted"
    before: int             # 压缩前 token(input+cache 真值)
    after: int              # 压缩后 token(重发后 API 报的回)
    reduction_pct: float    # (before-after)/before,0-1
    triggered_by: str       # "proactive"(本期) | "error"(既有 overflow 路径)
    session_id: str = ""    # 留 trace;不破旧事件
```

## 5. `tokens.py` 估算(契约 §12;spec D1)

### 5.1 估算策略

输入:任意 `str`。输出 `(tokens: int, method: "api" | "estimate")`。

| 输入类型 | 方法 | 理由 |
|---|---|---|
| `last_usage.input_tokens` / `cache_read` / `cache_creation` | `api`(真值) | API 返回的;不再估 |
| 系统提示(整段)/ tools 签名(拼接) | `estimate`(`len//4` 或 `tiktoken`) | 不进 API,无法拿真值;标 "estimate" |
| 4 tier memory 段 | `estimate` | 同上;用户知道"估" |
| 单条 user/assistant message | `api`(`last_usage` 累加) | API 报的 input+cache 反映最近一轮 |

`method="api"` 走 `cost_of` / `last_usage` 路径(已有,零新代码);
`method="estimate"` 走:

```python
def token_estimate(text: str) -> tuple[int, str]:
    """若装了 tiktoken → 优先 cl100k_base(Anthropic 兼容近似);否则降级 len//4。
    返回 (tokens, method)。"""
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text or "")), "estimate:tiktoken"
    except Exception:  # noqa: BLE001
        return max(1, len(text or "") // 4), "estimate:chars4"
```

**不**强制依赖 tiktoken(spec §2.1 #10);降级路径纯 stdlib。

### 5.2 误差诚实

`format_table` 渲染每桶 `[est]` / `[api]` 后缀,避免"用户把估算当 API 真值"误判。
spec D1 锁"每个数字必带 method 标签"。

## 6. `analyzer.py` 4 桶分桶(契约 §12;spec D1/D5)

### 6.1 `analyze(loop, store, workspace, goal) -> ContextBreakdown`

```python
def analyze(loop: "AgentLoop", *, store: "ArgosStore", workspace: Path,
            goal: str | None = None) -> ContextBreakdown:
    """一次性把 4 桶算齐。所有失败都降级(返回 entries=0 tokens=0),不崩。"""
    # 1) system:走 loop._build_system(goal) 拿原文;token_estimate
    #    source 标 "core/loop.py:471"(_build_system 实际行号)。
    # 2) memory:分 4 sub-bucket,从 memory/auto.load(scope=...) 抓;
    #    source 标 "memory/auto.py:82"(load 行号)。
    # 3) tools:走 _tool_signatures_block()(spec §2.3.3 那段),22 个 tool 拼接;
    #    source 标 "core/loop.py:430"。
    # 4) messages:store.get_messages(session_id) 拿全量;tokens 走 last_usage 真值;
    #    若 store 无 session → entries=0 tokens=0。
    # 5) window:loop._model.tier.context_window;fallback 200_000。
    ...
```

### 6.2 `details` 子段(memory 4 tier,spec D5)

memory bucket 的 `details` 字段固定 4 项:`(("user", N), ("project", N), ("skill", N),
("session", N))`,各 tier 的 token 数(都走 estimate)。`/context` 文本表格展开一行
`memory (4 tier): user=N project=N skill=N session=N`,让用户能看出"project tier 涨爆了"。

## 7. `render.py` 文本表格(契约 §12;spec §2.1 #3)

### 7.1 `format_table(breakdown) -> str`

```
Argos Context Breakdown
──────────────────────
system         1,840 tok  [est]   core/loop.py:471
memory (4 tier)  623 tok  [est]   memory/auto.py:82
  · user             0  [est]
  · project        340  [est]
  · skill          220  [est]
  · session         63  [est]
tools         1,120 tok  [est]   core/loop.py:430  (22 tools)
messages      4,517 tok  [api]   memory/store.py:259
──────────────────────
total         8,100 tok  / 200,000 (4.0%)  [green]
```

字段对齐:左 name(20 字符)+ 右 tokens(右对齐 8 字符)+ `[method]`(7)+ 源(可截断);
≥80% 总行 `[red]` 颜色,50-80% `[yellow]`,<50% `[green]`(走 Textual `color` markup,
非 ANSI 序列,TUI/CLI 共用)。

### 7.2 `format_json(breakdown) -> str`

走 `dataclasses.asdict()` + `json.dumps(indent=2, ensure_ascii=False)`,字段名 snake_case,
`health` 加进顶层;`details` 保 `[[name, tokens], ...]` 数组。

## 8. `threshold.py` 压不压(契约 §12;spec D2/D4)

### 8.1 `_should_compact(*, used, window, threshold, phase, already_compacted_at) -> bool`

判定顺序(短路返回 False):

| 条件 | → |
|---|---|
| `not compaction` (LoopConfig 字段) | False |
| `phase in ("verify", "plan")` | False(spec D4 不破门禁) |
| `used / window < threshold` | False |
| `already_compacted_at and used <= already_compacted_at.used_at_compact + 5% * window` | False(spec D2 幂等,防重复压) |
| `last_verdict_fail_count > 0`(刚 verify 失败) | False(等 verify 收敛后再压) |
| 默认 | **True**(压) |

返回 True 时 loop 调 `compact_messages` + yield `CompactedEvent`。

### 8.2 幂等关键

`AgentLoop._last_compact_used: int | None = None`(实例字段,本 run 有效):
- 第一次压前存 `used`(压前 token 数)
- 之后 `_should_compact` 比 `used <= _last_compact_used + 5% * window`(留 5% buffer,
  避免压完又涨一点点就再压)
- `compaction` / `verify` 触发的不算(独立路径,它们自己管)

## 9. `core/loop.py` 扩展(契约 §9;spec D2/D3)

### 9.1 不修改既有流程

`AgentLoop._drive(...)` 顶部加 1 行:

```python
async for ev in self._maybe_proactive_compact(session_id, step):
    yield ev
while step < self._cfg.max_steps:
    ...
```

`_maybe_proactive_compact` 是新增方法;若条件不满足,空生成器(零字节 yield)。

### 9.2 `_maybe_proactive_compact(session_id, step)`

```python
async def _maybe_proactive_compact(self, session_id: str, step: int):
    if not self._cfg.compaction or not self._cfg.compact_threshold:
        return
    usage = getattr(self._model, "last_usage", None) or {}
    used = (int(usage.get("input_tokens") or 0)
            + int(usage.get("cache_read") or 0)
            + int(usage.get("cache_creation") or 0))
    window = self._model.tier.context_window
    if not _should_compact(
        used=used, window=window,
        threshold=self._cfg.compact_threshold,
        phase="act",                  # 已经在 act 阶段(verify/plan 不在 while 里)
        already_compacted_at=self._last_compact_used,
        last_verdict_fail=self._fail_count,
    ):
        return
    # 调 store.compact_messages + 重载 messages
    pre_used = used
    self._store.compact_messages(session_id, keep_recent=5)
    new_messages = self._store.get_messages(session_id)
    # 让下一轮重发用压缩后的线程
    self._messages_override = new_messages   # loop 顶部短路读这里
    self._last_compact_used = pre_used
    # 估压缩后 token(reload 后 store 不知;粗略按 "摘要=老 N 条 1/N" 估)
    new_total = sum(len(m["content"]) // 4 for m in new_messages)
    self._last_compact_estimated = new_total
    yield CompactedEvent(
        before=pre_used, after=new_total,
        reduction_pct=(pre_used - new_total) / max(1, pre_used),
        triggered_by="proactive",
        session_id=session_id,
    )
```

### 9.3 `messages` 重载兼容

`while step < self._cfg.max_steps` 内**每轮顶部**先取 `self._messages_override or
self._store.get_messages(session_id)`,覆盖既有"messages 一次加载后续 append"行为;
override 消费一次后清空。

### 9.4 事件流

`CompactedEvent` 走 `EventKind` 现有 `workflow_progress` 旁路?**不** — `EventKind` 是
`Literal[...]` 联合,加一项 spec D10 锁"零破坏"。改 `EventKind` 加 `"compacted"`,
**且**保旧事件类型不变(仅扩展字面量);持久化(replay)兼容性:`deserialize_event` 看
`kind` 字段,未知 `kind` 走 `pass`(既有 pattern,无破坏)。

### 9.5 `LoopConfig` 新字段

`compact_threshold: float = 0.8` —— 0 = 不主动压(只保留 overflow 应急路径);0.5 = 半数就压;
1.0 = 几乎不主动压(留 safety net)。

## 10. TUI 接入(契约 §10;spec §2.1 #7/#8)

### 10.1 `tui/commands.py` 扩展

`COMMAND_HELP` 加:

```python
"context": "查看当前 LLM 上下文分桶(/context, /context --json)",
```

`/context` arg 走 `parse_slash(...).arg`,非空就透传给 `format_json`。

### 10.2 `tui/app.py` dispatch

`ArgosApp._dispatch_slash(sc)` 加 `if sc.name == "context":` → `await self._context_cmd(sc.arg)`。

`ArgosApp._context_cmd(arg)`:
- 调 `ContextAnalyzer.analyze(loop=self._agent_loop, ...)`
- 文本走 `await log.append_line(line, kind="info")`,逐行(让 markup 着色生效)
- `--json` 走 `format_json` 一整段(无 markup,无颜色)

### 10.3 活动栏 badge(契约 §10;spec §2.1 #8)

`ActivityPanel.on_context(used, window)` 改:

```python
def on_context(self, *, used: int, window: int) -> None:
    pct = 0 if not window else round(used * 100 / window)
    filled = min(10, max(0, round(pct / 10)))
    bar = "▓" * filled + "░" * (10 - filled)
    win = f"{window // 1000}k" if window else "?"
    health = "green" if pct < 50 else "yellow" if pct < 80 else "red"
    badge = f"[ctx {used}/{window} {pct}%]"   # 关键新元素
    self._set(8, f"{self._model_label} · {win}\n{bar} {pct}%\n{badge}")
```

### 10.4 状态栏红点(契约 §10;spec §2.1 #8)

`StatusBar` 扩展 `update_ctx_pressure(pct)`:>80% 时 widget 加 `.red-glow` CSS class
(Textual `set_class`),<80% 移除。**最小化装饰**(不画百分比数字,不画阈值线,只一颗红点)

## 11. CLI 子命令(契约 §10;spec §2.1 #9)

### 11.1 `__main__.py` 扩展

```python
elif cmd == "context":
    if sub == "show":
        as_json = "--json" in rest
        # 拿当前 session(走 store.get_sessions() 最新一条)
        breakdown = ContextAnalyzer.analyze(loop, store=store, workspace=ws)
        if as_json:
            print(format_json(breakdown))
        else:
            print(format_table(breakdown))
    else:
        print("usage: argos context show [--json]")
```

`--session=<id>` 解析(可选);默认 `store.get_sessions()[-1].session_id`。

### 11.2 `argos context show --json` 输出例

```json
{
  "system": {"name": "system", "tokens": 1840, "entries": 1, "method": "estimate:chars4", "details": []},
  "memory": {"name": "memory", "tokens": 623, "entries": 4,
    "method": "estimate:chars4", "details": [["user", 0], ["project", 340], ["skill", 220], ["session", 63]]},
  "tools": {"name": "tools", "tokens": 1120, "entries": 22, "method": "estimate:chars4", "details": []},
  "messages": {"name": "messages", "tokens": 4517, "entries": 12, "method": "api", "details": []},
  "total": 8100, "window": 200000, "pct": 0.0405, "health": "green"
}
```

## 12. 诚实防线(关键,spec §2.2 锁)

### 12.1 估算/真值不混

- `format_table` 强制每个数字带 `[est]` / `[api]` 后缀
- `format_json` 顶层有 `method` 字段,各 bucket 有 `method` 字段
- `messages` 桶的 `tokens` 走 API 真值(`input_tokens + cache_read + cache_creation`),
  但 `entries` 走 `len(store.get_messages())`;两条独立;避免"len × 估"虚报

### 12.2 主动压前必报

`CompactedEvent.before / after / reduction_pct` 三个数都报;**不**允许"已压但报 0% reduction"
(`after > before` 时 reduction_pct 钳到 0,不报负数)

### 12.3 跳过条件可见

若 `compaction=False` 或 `phase=verify`,**不**调 `_maybe_proactive_compact`(`return`),
但**也**不假装压了(零 yield)。spec D4 锁"压与不压都诚实"

### 12.4 文件:行号 source

每桶 `source` 字段必带,**不**允许空字符串(空就标 `"(unknown)"`,UI 显 `(unknown)`)

### 12.5 CLI/TUI 单一来源

`ContextAnalyzer.analyze(...)` 是 CLI + TUI + (未来)MCP 工具的**唯一入口**;
`format_table` / `format_json` 单一渲染函数。两路数字**不**允许不一致

## 13. 错误处理

| 错误 | 处理 |
|---|---|
| `tiktoken` 没装 | 降级 `len // 4`,method=`"estimate:chars4"`;**不**警告(常见情况) |
| `memory/auto.load` 抛异常 | memory bucket `entries=0 tokens=0`,method=`"estimate:unavailable"` |
| `store.get_messages` 抛 / 无 session | messages bucket `entries=0 tokens=0`,method=`"api:unavailable"` |
| `_build_system` 抛 | system bucket `entries=0 tokens=0`,method=`"estimate:unavailable"` |
| `compact_messages` 失败(写盘错误) | 静默 catch,`CompactedEvent` 不 yield,`self._last_compact_used` 不更新,下轮再试 |
| `context_window <= 0` | ratio 用 0 兜底,不除零 |
| `tier.context_window` 不存在(Ollama 老版本) | fallback `200_000`(`config.py:_DEFAULT_CONTEXT_WINDOW`) |
| `format_json` 不可序列化(自定义对象进 details) | `json.dumps(..., default=str)` 兜底,**不**崩 |

## 14. 测试(6 文件,+ ~40 测试,spec §17)

### 14.1 文件清单

| 文件 | 覆盖 | 估测 |
|---|---|---|
| `tests/test_context_tokens.py` | tokens.py:estimate 真值/tiktoken 降级/method 字段 | 8 测试 |
| `tests/test_context_analyzer.py` | analyzer.py:4 桶独立/全失败降级/memory details/window fallback | 10 测试 |
| `tests/test_context_threshold.py` | threshold.py:5 个跳过条件/2 个允许条件/幂等 | 8 测试 |
| `tests/test_context_render.py` | render.py:text 表格对齐+颜色+method/JSON 字段/dict-like | 7 测试 |
| `tests/test_tui_context.py` | tui/commands.py:COMMAND_HELP 加 context;app.py:_context_cmd 调度;活动栏 badge 改;status_bar 红点 class | 6 测试 |
| `tests/test_context_e2e.py` | 端到端:长会话(注入 50 步 token)→ 80% 触发主动压;压后 ratio 降回 50% 以下;`--json` 输出 parse 成功 | 5 测试 |

### 14.2 端到端铁证

`tests/test_context_e2e.py::test_proactive_compact_on_long_session`:
- mock `ModelClient.last_usage` 随 step 涨(0 → 100k)
- 跑 loop 30 步(超 80%)
- 断言:`CompactedEvent.triggered_by == "proactive"` 至少 yield 1 次
- 断言:压后 `last_usage.input_tokens` < 50k(从 100k 降回)
- 断言:`_last_compact_used` 记录压前 used,下一轮不再压

### 14.3 既有 1570 测试 0 破坏

`compact_messages` 既有签名不动;`LoopConfig.compact_threshold` 默认 0.8(老 config 文件
没这字段 → 走 default),既有 `compact_messages` 触发路径(error 触发)不变;新增方法
`_maybe_proactive_compact` 不挂在 `_drive` 必走路径(只挂 `while` 顶部,return 即空 yield)。

## 15. 风险与未来

- **风险 1**:压丢上下文 — 摘要走"前 60 字"截断;v1.1 接 LLM 摘要(便宜模型 1 次调用,成本 < $0.001)
- **风险 2**:重复压 — 5% buffer 可能不耐打(快速填满);v1.1 接滑动窗口度量
- **风险 3**:估算误差 — 中文 1.5 字符/token 不准(实际 ~1.0);若用户切中文任务,system
  桶会高估 30%。缓解:method 字段透明;v1.1 走 jieba 分词或本地多语言 tokenizer
- **风险 4**:CLI `--session=<id>` 拿错 session — store.get_sessions() 最新一条不一定是用户想看的
  (多 run 并发);v1.1 接 `#5b` RunRegistry(`run_id` 显式传)
- **风险 5**:压期间 race(loop 切 verify 同时压触发) — phase 短路解决(spec D4 锁)
- **风险 6**:状态栏红点装饰过度 — 走最小化(单红点,无文字);用户说多 → 移除
- **未来 v1.1**:
  - LLM-summarize 中间段
  - per-tool token 拆分(22 工具各自占比)
  - 中文/多语言 tokenizer
  - per-project override(`<project>/.argos/context.json`)
  - `/context` 图形化(分桶柱状图,Textual canvas widget)
  - 跨 session 上下文共享分析(`#5b` 多 run 联动)
  - 自动按 eval 成功率调阈值

## 16. 决策记录(D1-D20)

| # | 决策 | 选项 | 拍板 | 理由 |
|---|---|---|---|---|
| D1 | Token 估算 | tiktoken 必装 / chars4 / chars4+tiktoken 可选降级 | **chars4 + tiktoken 可选** | 0 新强制依赖;tiktoken 用户体验更好但不必备 |
| D2 | 主动压触发频率 | 每 step 查 / 每 N step / 阈值触发 | **每 step 查(阈值触发)** | spec 锁"主动"=阈值驱动,不是周期驱动 |
| D3 | 阈值默认 | 0.5 / 0.8 / 0.9 | **0.8** | 与 OpenAI cookbook "start thinking at 80%" 实践对齐 |
| D4 | 跳过 phase | verify / plan / all | **verify + plan** | 这两阶段 verifier/planner 需要完整对话;act 主动压 |
| D5 | memory 在 /context | 4 tier 全显 / 仅总数 / 显前 5 | **4 tier 全显(details 子段)** | 用户 debug 想知道"哪个 tier 涨爆" |
| D6 | CLI/TUI 共用分析器 | 各自实现 / 共享 | **共享(`ContextAnalyzer`)** | 防止数字漂移;spec §12.5 |
| D7 | 主动压 vs error 压 | 同一路径 / 独立 | **独立路径,事件统一** | 主动 = 阈值;error = API 报错;共享 `CompactedEvent` 字段但 `triggered_by` 区分 |
| D8 | 状态栏红点 | 显/隐 | **显(>80% 加 .red-glow class)** | 最小装饰,用户一眼知 |
| D9 | 主动压 idempotent | 简单 flag / 滑动窗口 | **`_last_compact_used + 5% buffer`** | 单实例字段,够用,简单 |
| D10 | `EventKind` 扩展 | 改 Literal / 旁路 workflow_progress | **改 Literal 加 `"compacted"`** | 事件类型真实;`deserialize_event` 未知 kind 走 pass 保兼容 |
| D11 | compact_messages 改签名 | 加 keep_recent kw / 保持 | **保持**(本期不调既有) | spec §9 锁零破坏;新调用走默认 keep_recent=5 |
| D12 | analyzer 调用方 | 同步 / 异步 | **同步** | 4 桶都是 IO 极小(读 store / 算 token);异步无收益 |
| D13 | json 字段顺序 | alphabetic / spec 序 | **spec 序(system/memory/tools/messages/total/window/pct/health)** | 用户读起来 4 桶 → 汇总,符合视觉 |
| D14 | 表格宽度 | 自适应 / 固定 80 | **固定 80 字符,左对齐 name 20** | TUI/CLI 通用;太宽 CLI 折行丑 |
| D15 | 状态栏红点 CSS class | .red-glow / .ctx-warn | **.ctx-warn(避免与 .error 撞)** | 命名按用途,不按颜色 |
| D16 | 主动压后 messages override | 覆盖 _messages 字段 / 让 while 重读 | **新加 `_messages_override` 字段,while 顶部取一次** | 不动既有"messages append"模式 |
| D17 | `compact_threshold` 0 含义 | 禁用 / 启用更多 | **0 = 不主动压(只留 error 应急路径)** | 跟 `compaction=False` 等价语义;用户可一刀切 |
| D18 | `--compact-threshold=0.7` vs config.json | 临时 / 持久 | **CLI 临时 + config.json 持久(两路都有,临时覆盖)** | 一致性,跟 `--effort` 模式相同 |
| D19 | 分析器出错 | 抛 / 降级 | **降级(返回空 bucket,tokens=0)** | 启发式 + 阈值决策不该崩 run |
| D20 | `tiktoken` 装不上的 UI 提示 | 警告 / 静默 | **静默**(方法字段已显) | 不刷屏;`/context` 表格自带 method 透明 |

## 17. 实施任务(对应 plan)

8 任务,1 任务 = 1 commit,完整 TDD,沿用 `#11` 风格:

1. `tokens.py` 估算函数 + method 字段 + 可选 tiktoken
2. `analyzer.py` 4 桶分桶 + details + window fallback
3. `threshold.py` 5 跳过条件 + 2 允许条件 + 幂等
4. `render.py` 文本表格 + 颜色 + JSON + 字段对齐
5. `core/loop.py` 扩展:`_maybe_proactive_compact` + `LoopConfig.compact_threshold` + `messages_override` 短路
6. `tui/commands.py` + `tui/app.py` + `tui/widgets/activity_panel.py` + `tui/widgets/status_bar.py` 接入
7. `__main__.py` 加 `context show [--json] [--session=<id>]` 子命令
8. 文档 + CHANGELOG + README 更新 + 端到端铁证

## 18. 不触动清单(契约 §9 锁)

- **不**改 `ModelClient` 既有方法签名(`stream` / `complete` / `last_usage`)
- **不**改 `ModelClient.__init__` 既有必填参数
- **不**改 `core/loop.py` 既有流程(只在 `while` 顶部加 `_maybe_proactive_compact` yield)
- **不**改 `LoopConfig` 既有字段(只加 `compact_threshold: float = 0.8`,**有 default**)
- **不**改 `compact_messages` 既有签名(本期 0 调用它,只走既有 error 路径)
- **不**改 `ApprovalGate` 既有签名
- **不**改 `Config` 加载器签名(只在 build_components 加 `compact_threshold` 透传 kw)
- **不**改 `tui/commands.py` 既有 COMMAND_HELP(只加 "context")
- **不**加 sqlite / **不**加新强制外部依赖
- **不**起 daemon
- **不**接 MCP 工具路由(留 v1.1)
- **不**改 `EventKind` 既有字面量(只扩展加 `"compacted"`,保旧事件兼容)
