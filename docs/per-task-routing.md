# Per-task model routing + effort

> 让"主用便宜模型 + 关键任务切强模型 + 看得见切到哪里花了多少"成为可配置、可观察、可治理的一等公民。
> 文档随 #11 实施同步:spec 在 `docs/superpowers/specs/2026-06-07-per-task-routing-design.md`、plan 在 `docs/superpowers/plans/2026-06-07-per-task-routing.md`。

## 为什么

Argos 的灵魂是"让便宜模型可靠"。`verify 硬门禁 + 诚实协议` 让便宜模型能**老实交付**,
但**成本优化**这一条,只有 verify 不够 —— 用户希望:

- 简单编辑(改个 typo)用 **cheap** 模型,几毫秒、$0.0001
- 复杂 refactor 切 **strong** 模型,$0.05 但质量稳
- 每次切档**看得见**:活动栏 `↑100 ↓200 [str]  $0.005` 这种标签
- 配置**一次到位**:`~/.argos/config.json` 的 `routing` 段写完,自动跑

不靠"接 N 个 model 卖花活" —— 那是 LangChain/LlamaIndex 红海;靠"切档可观察可治理"——
那条路别人没治理所以没护城河。

## 怎么用

### 1. 配置 routing

`~/.argos/config.json` 加 `routing` 段(可选,缺则 safe default):

```json
{
  "models": {
    "cheap":   { "protocol": "anthropic", "base_url": "https://api.minimaxi.com/anthropic", "model": "MiniMax-Haiku",  "api_key_env": "MINIMAX_KEY" },
    "default": { "protocol": "anthropic", "base_url": "https://api.minimaxi.com/anthropic", "model": "MiniMax-M2",     "api_key_env": "MINIMAX_KEY" },
    "strong":  { "protocol": "anthropic", "base_url": "https://api.minimaxi.com/anthropic", "model": "MiniMax-M2-Pro", "api_key_env": "MINIMAX_KEY" }
  },
  "active": "default",
  "routing": {
    "default": "default",
    "by_category": {
      "file_edit":     "cheap",
      "refactor":      "default",
      "test_write":    "default",
      "verify":        "strong",
      "long_run":      "default"
    },
    "by_tool": {
      "run_command":   "cheap"
    },
    "tier_force_confirm": ["strong"]
  }
}
```

- **`by_category`** 按任务类别路由(8 类别见下)
- **`by_tool`** 按工具调用路由,**优先级高于** `by_category`
- **`tier_force_confirm`** 列出来的 tier 即使 `--yolo` 启动也强制 CONFIRM(强模型负责任)

### 2. CLI effort 等级

```bash
argos --effort=low    <goal>   # 8 步 + AUTO(放手,试错/小修)
argos --effort=medium <goal>   # 40 步 + CONFIRM(默认,典型任务)
argos --effort=high   <goal>   # 80 步 + CONFIRM(复杂 refactor / 大改)
```

`--effort` 与 `--model` **正交**:`argos --effort=high --model strong <goal>` 跑最强档 + 最强模型。
反之 `--effort=low --model strong` 仍只跑 8 步(effort 限制 max_steps)。

### 3. TUI `/routing` 查看

```bash
/routing                       # 列 routing config + 最近 10 步决策
/routing set verify strong     # 把 verify 类别路由到 strong profile
/routing set file_edit cheap   # 把 file_edit 类别路由到 cheap
```

`/routing` 典型输出:

```
[Argos routing]
  default:        default
  by_category:
    file_edit     → cheap
    verify        → strong
  by_tool:
    run_command   → cheap
  tier_force_confirm: ['strong']

[最近 10 步决策]
  step   0  cat=file_edit  tool=edit_file        → cheap      (by_category)
  step   1  cat=simple_read tool=read_file       → default    (default)
  step   2  cat=verify      tool=run_command     → strong     (by_category)
  ...
```

活动栏成本区自动附 tier 标签:

```
↑100 ↓200 [str]  $0.005       ← strong tier
↑100 ↓200 [chp]  $0.0001      ← cheap tier
↑100 ↓200 [def]  $0.001       ← default tier
```

## 8 类别任务分类

| 类别 | 触发条件 |
|---|---|
| `plan` | `phase == "plan"`(plan 阶段首轮) |
| `verify` | `phase == "verify"`(verify 阶段) |
| `long_run` | `step >= 20`(长任务) |
| `auto_capture` | tool = `run_command` / `lsp_diagnostics` |
| `test_write` | code 含 `assert` / `pytest` / `def test_` / `TestCase` |
| `refactor` | code 含 `edit_file` 且 new - old ≥ 5 行 |
| `file_edit` | code 含 `edit_file` 且 new - old < 5 行 **或** `write_file` |
| `simple_read` | tool = `read_file` / `search_files` 或兜底 |

启发式 0 LLM 调用,任何异常(正则不命中)兜底 `simple_read`,**不**抛。

## 故障排查

### "tier 'srong' 不在 config.models"

拼错 tier 名 → `set_category` 拒写,启动加载也拒。**不**悄悄退化到 default。
检查 `~/.argos/config.json` 的 `models` 键名(routing 段必须引用存在的 model 名)。

### "category 'foo_bar' 不在合法类别内"

routing.by_category 键必须是 8 类别之一。合法值:`file_edit` / `refactor` /
`test_write` / `verify` / `plan` / `long_run` / `auto_capture` / `simple_read`。

### "/routing 不可用(无 router 注入)"

demo / fake 模式没接真 router(用 `FakeLoop`)。真 loop 路径(`argos` 不带 `--demo`)
会自动从 `~/.argos/config.json` 读 routing + 构造 `ModelRouter`。

### "切到 strong 还是自动跑"

`tier_force_confirm` 段默认 `["strong"]`,AgentLoop 拿到 strong 决策即强制 CONFIRM。
若要放开(不推荐),改 `tier_force_confirm: []`。

## 诚实防线(关键)

1. **tier 名 fail-closed** —— 拼写错立刻报错,绝不悄悄退化(spec D17)
2. **tier 决策可见性** —— 每次 `select()` 必带 `RouteDecision` 落 history,`CostUpdate.tier_name` 必带非空 tier(spec D15)
3. **strong 强制 CONFIRM** —— `tier_force_confirm` 默认 `["strong"]`(spec D13)
4. **3 层优先级** —— by_tool > by_category > default,命中层标 `source`(spec D2)
5. **不**动 `ModelClient` 既有方法 / `LoopConfig` 字段 / `core/loop.py` 流程 —— 全部通过
   `router` kw-only 注入 + 循环顶部 `if router` 短路(既有 1507 测试 0 破坏)

## 已知边界(留 v1.1)

- **不**持久化跨 run 路由历史 → v1.1 接 store
- **不**接 prefix-stable prompt cache → v1.1 接 M3 prefix 优化
- **不**支持 per-project `.argos/routing.json` 覆盖 → v1.1
- **不**做路由学习(基于 eval 调权)→ v1.1
- **不**支持 LLM-judge 分类器 → 启发式够用
- **不**接路由 A/B CLI → v1.1

## 命令行示例

```bash
# 默认:medium effort + 走 routing 切档
argos

# 复杂 refactor,强档 + 高 effort
argos --effort=high <goal>

# 试错小修,低 effort + 放手
argos --effort=low "改个 typo"

# 强制用某个 model(不走 routing)
argos --model strong <goal>

# 看 TUI 内 routing
# 启动后输入 /routing
```
