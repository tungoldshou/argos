# Context 可视化 /context + proactive 压缩 (#12)

Argos 让 LLM 的上下文消耗**可观察 + 可治理**:你既能看见当前窗口被谁占,也能
让 Argos 在超阈值时主动 `compact_messages`,而不是等模型吐
`context_length_exceeded`。

**核心架构**(spec `2026-06-07-context-viz-design.md`):

- 4 桶分桶(`system` / `memory (4 tier)` / `tools` / `messages`),每桶带
  `tokens` / `entries` / `source`(文件:行号,debug 用)/ `method`
  (`api` / `estimate:chars4` / `estimate:tiktoken` / `unavailable`)。
- API 真值(`last_usage.input_tokens + cache_read + cache_creation`)走
  `method=api`;非对话侧(system / memory / tools)走可选 `tiktoken.cl100k_base`,
  降级 `len // 4`,method 字段透明。
- Proactive compaction:每 step 顶部 1 行 `_maybe_proactive_compact(...)`,
  阈值满足 → 调 `compact_messages` + reload messages + yield
  `CompactedEvent(before, after, reduction_pct, triggered_by="proactive")`。
  5 跳过条件(verify/plan 阶段、`compaction=False`、`threshold<=0`、刚
  verify 失败、同范围 5% buffer 内)+ 1 允许(超过阈值且 idle)。
- TUI/CLI **单一来源**:`ContextAnalyzer.analyze(...)` 同时供 `/context` 和
  `argos context show` 用,数字不漂。

## 用法

### TUI

```
/context              # 4 桶分桶文本表格(绿/黄/红着色)
/context --json       # 整段 JSON(无 markup)
```

活动栏第 8 段追加一行 `[ctx N/M X%]` badge(旧 10 格进度条不破);状态栏
>80% 时整条加 `.ctx-warn` class(单红点,无文字)。

### CLI

```bash
$ argos context show
Argos Context Breakdown
──────────────────────────────────────────────────
  system              1,840 tok  [est]    core/loop.py:471
  memory (4 tier)       623 tok  [est]    memory/auto.py:82
    · user                  0 tok  [est]
    · project             340 tok  [est]
    · skill               220 tok  [est]
    · session              63 tok  [est]
  tools (22)          1,120 tok  [est]    core/loop.py:430
  messages            4,517 tok  [api]    memory/store.py:259
──────────────────────────────────────────────────
[green]total 8,100 tok / 200,000 (4.0%)[/green]

$ argos context show --json
{
  "system": {"name": "system", "tokens": 1840, "entries": 1, "method": "estimate:chars4", ...},
  "memory": {...},
  "tools": {...},
  "messages": {...},
  "total": 8100, "window": 200000, "pct": 0.0405, "health": "green",
  "method": "api+estimate"
}
```

### Proactive compaction

阈值默认 `0.8`(占 80% 触发)。可改:

```bash
uv run argos --compact-threshold=0.7    # 70% 就压,留更多 buffer
```

或者在 `~/.argos/config.json` 持久化:

```json
{ "compact_threshold": 0.7 }
```

`0` = 完全不主动压(只走既有 error 应急路径,模型吐
`context_length_exceeded` 时才压)。

## 5 跳过条件(诚实,spec D4 锁)

| 条件 | 后果 |
|---|---|
| `compaction=False` / `compact_threshold=0` | 全程不压(走 emergency 路径) |
| 当前 phase == `verify` 或 `plan` | 不压(不破门禁/规划阶段) |
| 刚 verify 失败(`_fail_count > 0`) | 不压(等 verify 收敛) |
| 同范围 5% buffer 内 | 不压(幂等,防刚压又涨一点点就再压) |
| `used / window < threshold` | 不压(还没到) |

## 6 透明点(方法字段必带,防"估当真值"误判)

- 活动栏 badge:`[est]` = 估算,`[api]` = API 真值
- 表格每个数字后跟 `[est]` / `[api]` 后缀
- JSON 顶层 `method` 字段 + 各 bucket 自己的 `method` 字段
- 跳过 / 压不压的决策都 yield `CompactedEvent(triggered_by="proactive"|"error")`,
  不静默

## 验收(对应 spec §17)

- 测试:1570 → 1614(+44);0 失败
- 既有 1570 测试 0 破(`LoopConfig.compact_threshold` 有 default 0.8,老 config
  缺字段不破;`compact_messages` 既有签名不动;`core/loop.py` 既有 `while` 内
  逻辑零修改)
- CLI/TUI 一致:同一 `ContextAnalyzer.analyze(...)`,数字不漂
- 0 新强制依赖(stdlib only;`tiktoken` 走可选 import 降级)

## 不触动清单(spec §21 锁)

- 不改 `ModelClient` 既有方法签名(`stream` / `complete` / `last_usage` / `__init__`)
- 不改 `compact_messages` 既有签名
- 不改 `core/loop.py` 既有 `while` 内逻辑(只在顶部加 1 行 yield + override 消费)
- 不改 `LoopConfig` 既有字段(只加 `compact_threshold: float = 0.8`)
- 不改 `CostUpdate` 既有字段(只读 `context_used`)
- 不改 `tui/commands.py` 既有 COMMAND_HELP(只加 "context")
- 不加 sqlite / 不加新强制外部依赖
- 不起 daemon / 不接 MCP 工具路由(留 v1.1)
