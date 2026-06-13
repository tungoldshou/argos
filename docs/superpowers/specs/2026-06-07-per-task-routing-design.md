# Per-task model routing + effort — 设计规格(spec)

> Road-map entry **#11** "Per-task model routing + effort (中等,扩多模型)" 的设计规格。
> 估时 2-3 天,中等。**灵魂对齐**"让便宜模型可靠"——不是"我接了 7 个 model
> 卖花活",而是让"主用便宜模型 + 关键任务切强模型 + 看得见切到哪里花了多少"
> 这条**省钱且不出错**的链路成为**可配置 + 可观察 + 可量化**的一等公民。

## 1. 背景与现状

- **v0.1.0 已发**,1507 测试绿。`ModelClient` + `Protocol` 抽象(`AnthropicProtocol` /
  `OpenAIProtocol`)已就位;`config.json` 支持 `models: { cheap, default, strong }`
  + `active` 切档;`tier` 字段(`ModelTierName`)贯穿 `LoopConfig` / `CostUpdate` /
  `SubAgentFactory.model_factory(profile)`。
- **当前缺口**:
  1. **每次 run 用一个 tier**——`build_components` 只装一个 `ModelClient`(绑死 active
     profile),整个 run 全程只能用这一个模型。简单编辑(改个 typo)和复杂 refactor
     都吃"默认"档,前者浪费钱、后者质量不稳。
  2. **没有"任务分类"概念**——"什么算简单 / 什么算复杂"目前只看用户输 goal 时的
     `--model` 覆盖,**没**按"工具调用 / 代码块 / 阶段"细分。`#5b` SubAgentFactory
     已支持 `task.model` 字段(每个子 agent 可指定 profile),但 host 侧 loop 不会自己
     切档。
  3. **没有"effort"概念**——Claude Code / Codex 都有 `effort=low/medium/high` 档位
     控制思考深度 / 推理回合。Argos 当前 `max_steps=40` 是硬上限,但**用户**调不到。
  4. **成本归属不可见**——`CostUpdate.cost_usd` 是当前 active profile 的成本,但**谁
     在哪一档跑了多少**不可追溯;做 A/B("切 strong 比 cheap 贵多少")无从下手。
  5. **审批与档位无联动**——strong 模型在 OBSERVE 档仍跑(不被拦截),cheap 模型在
     AUTO 档仍可能被 hard-rule 拦(spec 缺一条"strong 必 CONFIRM"的硬规则)。
- **风险**:
  1. **过度切档**——若按 tool_call 切,一次 `write_file` 后跟一次 `read_file` 会横跳
     两次档位,cache 命中率 ↓ cost ↑;若按 phase 切,会漏掉"act 内的复杂 refactor"
  2. **强模型出幻觉**——把 refactor 路由到 strong 模型 ≠ 强模型不会撒谎;verify 门 +
     CostUpdate.tier_name 仍要诚实记"这步是 strong 跑的",后续 audit 可追
  3. **effort 抽到不存在的"档"**——effort 实质是 max_steps / max_rounds / approval
     level 的组合,如果把 effort 拍成另一组完全独立的旋钮,与 `LoopConfig` 字段
     重叠 → 改一个忘一个,行为漂移
- **灵魂**:不跟 LangChain/LlamaIndex 拼"我接了 N 个 model"(他们没治理所以没护城河),
  也不跟 CC 抄"effort 是个神秘旋钮";而是做"我按 (category, tool) 算 tier、effort
  显式映射到 LoopConfig 字段、CostUpdate 诚实带 tier 标签、`/routing` 让用户随时
  看到上一条调用跑了哪档"——把"切档"做成**可观察可治理**的闭环。

## 2. 目标与非目标

### 2.1 目标(本期)

1. **8 类别任务分类** `file_edit` / `refactor` / `test_write` / `verify` / `plan` /
   `long_run` / `auto_capture` / `simple_read`,启发式从 (tool_call, code_block, phase)
   三元组推出(纯本地、零网络)
2. **三层路由** `~/.argos/config.json` 加 `routing: { default, by_category, by_tool }`,
   引用 `models.<name>`,任意 profile 名都有效
3. **解析器 + tier 追踪** `RoutingResolver` 把 (category, tool) → tier,
   记到 `RouteDecision`,供 CostUpdate / /routing 视图读
4. **ModelClient 扩展** `ModelClient.select_tier(category, tool)` 返回选中的
   `ModelClient` 实例(从 `ModelRouter` 拿);**不**改既有 `stream/complete` 签名
5. **effort 等级** `low` / `medium` / `high` 三档,显式映射到 `LoopConfig.max_steps`
   + `approval_level`(low=8 steps+AUTO;medium=40+CONFIRM;high=80+CONFIRM)
6. **CLI `--effort`** `argos --effort=high <goal>` 全程覆盖;`<goal>` 不带 flag 走 medium
7. **CostUpdate 加 tier 字段** `tier_name: str`,按实际调用方计费(cheap/strong 等)
8. **/routing TUI 命令** `/routing` 列当前 config + 最近 10 步 tier 分配;
   `/routing set <category> <tier>` 快速改写 config.json
9. **smart approval 联动** strong tier 强制 CONFIRM(纵深防线);cheap tier 仍可 AUTO
10. **0 新外部依赖**(stdlib only: `json` / `re` / `dataclasses` / `enum` /
    `collections.deque` / `pathlib`)
11. **不**改 `ModelClient` 既有方法 / **不**改 `core/loop.py` 流程 / **不**改
    `ModelClient.__init__` 签名;扩展通过 `ModelRouter` + 新方法实现
12. **不**接 sqlite / **不**起 daemon / **不**接 MCP 工具路由(留 v1.1)

### 2.2 非目标(本期不做)

- ❌ **路由策略的 LLM-judge** —— 启发式就够,LLM-judge 自身要 token,违背"省 token"目标
- ❌ **跨 tier 共享 prompt cache** —— 切 tier = 换 system prefix,cache 必然 miss;
  v1.1 接 prefix-stable 的 design(M3 等多数模型 prefix cache 粒度粗)
- ❌ **自动按历史成功率切档** —— v1 静态 config;v1.1 接 memory tier
- ❌ **用户态生效强约束** —— 只在 host 侧 loop 生效,子 agent 已用 `task.model` 字段
  独立,本 spec 不去统一
- ❌ **跨 run 持久化路由历史** —— 本期 tier 决策只在本 run 的 ActivityPanel 展示,
  持久化走 v1.1(cost attribution + eval 联动)
- ❌ **per-project routing override** —— 暂只 `~/.argos/config.json` 全局;
  v1.1 走 `.argos/routing.json` 项目级覆盖

## 3. 架构总览

```
                ┌──────────────────────────────────────┐
                │   ~/.argos/config.json                 │
                │   {                                    │
                │     "models": { cheap, default, strong }│
                │     "active": "default"                │
                │     "routing": {                       │
                │       "default": "default",            │
                │       "by_category": {                 │
                │         "file_edit": "cheap",          │
                │         "verify": "strong",            │
                │         "long_run": "default"          │
                │       },                               │
                │       "by_tool": {                     │
                │         "run_command": "cheap",        │
                │         "lsp_diagnostics": "default"   │
                │       }                                │
                │     }                                  │
                │   }                                    │
                └──────────────┬───────────────────────┘
                               │ 加载
                               ▼
              ┌────────────────────────────────────────┐
              │       routing/                          │
              │                                         │
              │  config.py     ─ RoutingConfig 加载器  │
              │                  + 字段校验             │
              │  categorizer.py ─ (tool, code, phase)   │
              │                    → TaskCategory       │
              │  resolver.py   ─ (category, tool)      │
              │                    → Tier (3 层优先级)  │
              │  router.py     ─ ModelRouter           │
              │                  = 多个 ModelClient +   │
              │                  决策 + 最近 N 步历史   │
              │  effort.py     ─ EffortLevel 枚举 +     │
              │                  → LoopConfig 字段映射  │
              └──────────────┬──────────────────────────┘
                               │
                               ▼
        ┌────────────────────────────────────────────┐
        │  core/loop.py(扩展:不修改流程)             │
        │  · _step 前调 categorizer.categorize()    │
        │  · router.select(category, tool)          │
        │  · 用返回的 ModelClient.stream(...)       │
        │  · CostUpdate 附 tier_name                │
        │  · /routing 读 router.history()            │
        └────────────────────────────────────────────┘
                               │
                               ▼
        ┌────────────────────────────────────────────┐
        │  TUI /routing 命令                         │
        │  · 列 routing config + 最近 10 步决策     │
        │  · /routing set <category> <tier>          │
        │    改写 ~/.argos/config.json               │
        └────────────────────────────────────────────┘
```

## 4. 数据结构

### 4.1 `TaskCategory` 枚举

8 个固定值(避免自由字符串 → 拼写错误导致静默回退 default):

```python
class TaskCategory(enum.Enum):
    FILE_EDIT = "file_edit"        # 改 1-2 行(typo / 改字符串)
    REFACTOR = "refactor"          # 结构性改(改函数签名 / 抽公共)
    TEST_WRITE = "test_write"      # 写测试
    VERIFY = "verify"              # verify 阶段跑命令
    PLAN = "plan"                  # plan 阶段首次输出
    LONG_RUN = "long_run"          # 当前 step > 阈值(默认 20)
    AUTO_CAPTURE = "auto_capture"  # memory auto-capture 内部调用
    SIMPLE_READ = "simple_read"    # read_file / search_files 主导
```

### 4.2 `RouteDecision` 不可变记录

```python
@dataclass(frozen=True, slots=True)
class RouteDecision:
    category: TaskCategory
    tool: str | None
    tier: str            # 实际选中的 profile 名
    source: str          # "by_tool" | "by_category" | "default"
    step: int = 0        # 哪一步做的决策
```

### 4.3 `EffortLevel` 枚举

```python
class EffortLevel(enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
```

### 4.4 `RoutingConfig` 冻结 dataclass

```python
@dataclass(frozen=True, slots=True)
class RoutingConfig:
    default: str
    by_category: dict[str, str]    # category.value → profile
    by_tool: dict[str, str]        # tool name → profile
```

## 5. 分类启发式(`categorizer.py`)

输入:`tool_name: str | None`(从 `extract_tool_names(code)` 抓)、`code: str | None`、
`phase: str`(`plan` / `act` / `verify` / `report`)、`step: int`(loop 步序号)。

输出:`TaskCategory`。

判定顺序(短路返回):

| 条件 | → 类别 |
|---|---|
| `phase == "plan"` | `PLAN` |
| `phase == "verify"` | `VERIFY` |
| `step >= LONG_RUN_THRESHOLD`(默认 20) | `LONG_RUN` |
| `tool_name in {run_command, lsp_diagnostics}` | `AUTO_CAPTURE` |
| code 含 `assert` 或 `pytest` / `def test_` / `TestCase` | `TEST_WRITE` |
| code 含 `edit_file(` + `lines_changed(code) < 5` | `FILE_EDIT` |
| code 含 `edit_file(` + `lines_changed >= 5` 或含 `class` / `def ` + indent 变化 | `REFACTOR` |
| tool_name in `{read_file, search_files}` | `SIMPLE_READ` |
| code 含 `write_file(` | `FILE_EDIT`(无法判断规模,保守归 edit) |
| 兜底 | `SIMPLE_READ`(无 code 块也走这个) |

`lines_changed(code)`:`edit_file(old, new)` 抽 old/new 算 `len(new.splitlines()) -
len(old.splitlines())`;`write_file` 算 new 行数。

**不变量**:
- 启发式只看静态文本,无 LLM 调用 → 0 token
- 任意启发式失败(`ast.literal_eval` 异常)→ 兜底 `SIMPLE_READ`,**不**抛
- 类别不在 `TaskCategory` 枚举里 → `ConfigError`(加载期 fail-closed)

## 6. 路由解析(`resolver.py`)

签名:
```python
def resolve(routing: RoutingConfig, *, category: TaskCategory,
            tool: str | None) -> RouteDecision:
    """3 层优先级:by_tool > by_category > default。"""
```

算法:

```python
if tool is not None and tool in routing.by_tool:
    return RouteDecision(category, tool, routing.by_tool[tool], "by_tool")
if category.value in routing.by_category:
    return RouteDecision(category, tool,
                         routing.by_category[category.value], "by_category")
return RouteDecision(category, tool, routing.default, "default")
```

**Tier 名必须存在于 `config.models`**(否则 `ConfigError`);解析时 **不** fallback
到 `default`(fail-closed:把 `"strong"` 拼成 `"srong"` 会立刻报,而不是悄悄退化到
default 模型上跑一堆强模型逻辑)。

## 7. ModelRouter(`router.py`)

`ModelRouter` 把 N 个 `ModelClient`(按 `models` 字典构造)塞进一个对象,`select()`
按 (category, tool) 返回对应的 `ModelClient` 实例 + 记录 `RouteDecision`。

```python
class ModelRouter:
    def __init__(self, *, clients: dict[str, ModelClient], config: RoutingConfig,
                 router_tier: str) -> None:
        """clients: profile 名 → ModelClient;router_tier: 当前 router 所在 tier
        (用于 RouteDecision 自身;不参与选档)。"""
        self._clients = clients
        self._config = config
        self._router_tier = router_tier
        self._history: deque[RouteDecision] = deque(maxlen=10)

    def select(self, *, category: TaskCategory, tool: str | None,
               step: int = 0) -> tuple[ModelClient, RouteDecision]:
        """返回选中的 client + 决策(决策 append 到 history)。"""
        decision = resolve(self._config, category=category, tool=tool)
        client = self._clients.get(decision.tier)
        if client is None:
            # 解析时已 fail-closed 校验过;这里只是防御性兜底
            raise ConfigError(f"profile '{decision.tier}' 未构造 ModelClient")
        decision = replace(decision, step=step)
        self._history.append(decision)
        return client, decision

    def history(self) -> list[RouteDecision]:
        return list(self._history)
```

**懒构造**:`ModelClient` 含 `CredentialPool`,而 `CredentialPool` 需要 key。
`ModelRouter.__init__` **不**立即造所有 tier 的 client(避免无 key 的 tier 启动
报错);而是 `select()` 时**懒**构造:第一次访问某 tier 时 `config.tier_for(name)
+ key_for(name) + CredentialPool([key])` → `ModelClient`。

**不变量**:
- 单 `ModelClient` 实例缓存(`self._clients: dict` 首次 miss 时构造并缓存)
- `select()` 失败(无 key / config 坏)→ 抛 `ConfigError`,loop 顶层 catch 投 `Error`
  事件(spec §3.3 L5)
- `history()` 返回 snapshot(不可变),不暴露 deque

## 8. Effort 映射(`effort.py`)

```python
@dataclass(frozen=True, slots=True)
class EffortSettings:
    max_steps: int
    approval_level: ApprovalLevel

EFFORT_PRESETS: dict[EffortLevel, EffortSettings] = {
    EffortLevel.LOW: EffortSettings(
        max_steps=8, approval_level=ApprovalLevel.AUTO),
    EffortLevel.MEDIUM: EffortSettings(
        max_steps=40, approval_level=ApprovalLevel.CONFIRM),
    EffortLevel.HIGH: EffortSettings(
        max_steps=80, approval_level=ApprovalLevel.CONFIRM),
}
```

CLI 解析:

```python
# argos/__main__.py 加:
p.add_argument("--effort", choices=["low", "medium", "high"], default="medium",
               help="LoopConfig.max_steps + approval_level 档位(默认 medium)")
```

`build_components` 接收 `effort: EffortLevel` 参数,把 preset 展开填进 `LoopConfig`。
`LoopConfig` 不直接接 `EffortLevel`(避免改既有 dataclass),而是拆 `max_steps` +
`approval_level` 两个字段。

## 9. CostUpdate 扩展(`tui/events.py`)

```python
@dataclass(frozen=True, slots=True)
class CostUpdate:
    ...  # 既有字段
    tier_name: str = ""     # 实际跑这步的 profile(默认 ""=沿用 active)
```

既有调用点(`core/loop.py` yield CostUpdate 处)加 `tier_name=self._current_tier`。
`_current_tier` 在 `select()` 后更新,verify 阶段也用同 tier(强模型跑 verify = 真验证,
不是便宜模型敷衍)。

序列化:`serialize_event` 不变(asdict 自动展开),replay 路径兼容(空串 = 旧事件)。

## 10. loop 接线(`core/loop.py` 扩展)

**不**改 `run()` / `_drive()` 既有流程;**不**改 `ModelClient` 既有方法。
唯一接线点:`_drive` 的 `while step < self._cfg.max_steps` 循环顶部,**前**于
`async for delta in self._model.stream(...)`,加:

```python
# #11 per-task routing:每步按 (tool, code, phase) 选 tier;router 不存在时
# 静默用既有 self._model(零破坏默认路径)。
if hasattr(self, "_router") and self._router is not None:
    code = extract_code_block(text) if text else None
    tool_names = extract_tool_names(code) if code else []
    primary_tool = tool_names[0] if tool_names else None
    # phase 取 harness 当前 phase;phase == "plan" 时无 text,先拿默认
    phase = self._harness._current_phase if hasattr(self._harness, "_current_phase") else "act"
    client, decision = self._router.select(
        category=categorize(tool=primary_tool, code=code, phase=phase, step=step),
        tool=primary_tool, step=step,
    )
    self._current_tier = decision.tier
    self._model = client   # 本步用这个 client
else:
    self._current_tier = self._cfg.model_tier
```

⚠️ **关键不变量**:`_current_tier` 初始化于 `__init__`,默认 `self._cfg.model_tier`。
未注入 router → 走原路径,既有 1507 测试 0 破坏。

`AgentLoop.__init__` 加可选 kw-only 参数:

```python
def __init__(self, *, ..., router: ModelRouter | None = None, ...) -> None:
    ...
    self._router = router
    self._current_tier = self._cfg.model_tier
```

`app_factory.build_loop_factory` 在 `c.router` 存在时透传。

## 11. Smart approval 联动(`approval.py` 扩展)

**不**改 `ApprovalGate` 既有签名;**不**改 `smart approval` evaluator。
新增 `ModelRouter` 端逻辑:router 知道 strong tier → 在 `select()` 返 client 时,
若 `decision.tier in STRONG_TIERS`(用户配置 `tier_strength: ["strong"]`),
返回的 client 强行挂一个 `approval_level_override: ApprovalLevel.CONFIRM`。
`AgentLoop` 据此把 `LoopConfig.approval_level` 临时拨到 CONFIRM(act 段结束恢复)。

实际更简洁的方案:`routing_config.tier_force_confirm: list[str]`(默认 `["strong"]`)
+ `ModelRouter.select` 返回 `(client, decision)`,AgentLoop 端:
```python
if decision.tier in self._router.config.tier_force_confirm:
    self._approval_level_override = ApprovalLevel.CONFIRM
```
(`self._approval_level_override` 已是 plan mode 用的字段,直接复用。)

**T9 验收铁证**:`strong` tier 在用户配 `tier_force_confirm=["strong"]` 时,
即使启动 `--yolo`(AUTO),仍弹 CONFIRM 审批(强模型负责任;不放手)。

## 12. TUI `/routing` 命令(`tui/commands.py` + `tui/app.py`)

### 12.1 `parse_slash` 扩展

```python
COMMAND_HELP["routing"] = "查看 / 切换路由配置(/routing, /routing set <cat> <tier>)"
```

### 12.2 `/routing` 无参

`ArgosApp._cmd_routing()`:

```
[Argos routing]
  default:        default
  by_category:
    file_edit     → cheap
    refactor      → default
    verify        → strong
    long_run      → default
  by_tool:
    run_command   → cheap
  tier_force_confirm: [strong]

[最近 10 步决策]
  step  3  cat=file_edit  tool=edit_file        → cheap      (by_category)
  step  4  cat=refactor   tool=edit_file        → default    (default)
  step  5  cat=verify     tool=run_command      → strong     (by_category)
  ...
```

### 12.3 `/routing set <category> <tier>`

调 `RoutingConfig.set_category(category, tier)`(新方法,改写 `config.json` 原子写,
校验 tier 必须在 `models` 里)。category 名不在 8 个枚举内 → 弹错;
tier 不存在 → 弹错。成功 → 落一行 "已写入 ~/.argos/config.json"。

下一轮 run 生效(router 在 `build_components` 时重读)。

### 12.4 活动栏 tier 标签

`CostUpdate.tier_name` 已带 tier;ActivityPanel 渲染成本时附 `[cheap]` / `[strong]`
前缀(短标签,3 字母),用户看到每一行成本归属。

## 13. CLI `--effort` 与子命令

`argos/__main__.py`:

```python
p.add_argument("--effort", choices=["low", "medium", "high"], default="medium",
               help="任务努力档(low=8 步+AUTO;medium=40+CONFIRM;high=80+CONFIRM)")
```

`build_components` 接 `effort: str | None = None`,解析为 `EffortLevel`,展开到
`LoopConfig`:

```python
preset = EFFORT_PRESETS[effort]
loop_config = LoopConfig(
    ...
    max_steps=preset.max_steps,
    approval_level=preset.approval_level,
)
```

`argos --effort=high --model strong <goal>` 跑最强档 + 最强模型(给关键任务用)。
注意:`--effort=low` + `--model strong` 仍报 `low` effort 配置(8 步,即使模型强
也会早停)——effort 与 model **正交**,用户自己组合。

## 14. 持久化设计

### 14.1 `~/.argos/config.json` 扩展 schema

既有 schema(契约 §8):
```json
{
  "models": { "<name>": { "protocol", "base_url", "model", "api_key_env", ... } },
  "active": "<name>"
}
```

本 spec 新增(可选,缺则用 safe default):
```json
{
  "routing": {
    "default": "default",
    "by_category": { "file_edit": "cheap", "verify": "strong" },
    "by_tool": { "run_command": "cheap" },
    "tier_force_confirm": ["strong"]
  }
}
```

缺 `routing` → `RoutingConfig(default="default", by_category={}, by_tool={},
tier_force_confirm=[])`(零破坏已有用户)。

`config.json` 加载走 `load_config()`(已有),**不**改;`routing` 段在
`build_components` 时单独由 `routing.config.load_routing(config_dir: Path) ->
RoutingConfig` 读。

### 14.2 路由历史(本 run, in-memory)

`ModelRouter._history: deque(maxlen=10)`,本 run 内 `/routing` 读;**不**持久化
(下个 run 重置,v1.1 接 store)。

## 15. 诚实防线(关键)

### 15.1 tier 名错配防线

`RoutingConfig` 加载期:`by_category` / `by_tool` 的 tier 值必须存在于
`config.models`,否则 `ConfigError` 拒绝启动。**不** fallback 到 `default`
(避免把 `"strong"` 拼成 `"srong"` 后悄悄退到默认跑一批强模型逻辑)。

### 15.2 tier 决策可见性防线

每一次 `select()` 必 yield 一行日志到活动栏 + 落 `RouteDecision` 到 `router.history()`;
`CostUpdate.tier_name` 必带非空 tier 名(默认 `self._cfg.model_tier`)。
**不**允许"决策后不留痕"。

### 15.3 strong tier 强制 CONFIRM 防线

`tier_force_confirm` 默认 `["strong"]`;`AgentLoop` 拿到 strong 决策即
`_approval_level_override = CONFIRM`,即使 `--yolo` 启动仍弹 CONFIRM(纵深)。
**不**留"用户开了 yolo 强模型仍自动跑"的口子。

### 15.4 effort 边界防线

`--effort=low` 的 `max_steps=8` 是硬上限(spec §3.3 L3 既有 `max_steps` 契约),
即使模型在第 8 步还在 loop 也停。`EffortLevel` 字段拼错 → argparse 拒(`choices`)。

## 16. 错误处理

| 错误 | 处理 |
|---|---|
| `config.json` 无 `routing` 段 | 走 safe default,**不**抛 |
| `routing.tier` 不在 `models` | `ConfigError` 启动失败(防拼写) |
| `routing.by_category` 键不在 8 类 | `ConfigError` 启动失败(防漂移) |
| `extract_tool_names` 失败 | 归 `simple_read` |
| 启发式 `ast.literal_eval` 失败 | 归 `simple_read`(不抛) |
| `ModelRouter.select` 时 key 缺 | `ConfigError` → loop 投 `Error` 事件 |
| 同一 tier 多次访问 | 缓存 client,只造一次 |
| `--effort=foo` | argparse 拒(`choices`) |
| `/routing set foo bar` | 弹 transcript 错("category 'foo' 不存在,8 个 = ...") |
| cost_of 找不到 tier 模型 | `CostUpdate.cost_usd = None`(诚实 $(N/A),不编价) |

## 17. 测试(5 文件,+ ~35 测试)

| 文件 | 覆盖 | 估测数 |
|---|---|---|
| `tests/test_routing_categorizer.py` | 8 类别启发式 + 兜底 + 异常 | 8 |
| `tests/test_routing_config.py` | 加载/校验/safe default/set_category/写盘 | 8 |
| `tests/test_routing_resolver.py` | 3 层优先级 + tier 不存在 + history append | 6 |
| `tests/test_routing_router.py` | 懒构造 + select + history snapshot + EFFORT 映射 | 8 |
| `tests/test_routing_loop_integration.py` | AgentLoop 注入 router + CostUpdate.tier_name + strong→CONFIRM | 5 |
| **合计** | | **~35** |

### 17.1 端到端铁证

`tests/test_routing_e2e.py`:
- 配 3 个 profile: cheap / default / strong
- 配 `routing.by_category = {file_edit: cheap, verify: strong}` + `tier_force_confirm=[strong]`
- mock 三个 ModelClient(各 tier 一个),用 `_sse_transport` 注入 fake 文本
- 跑一 run(脚本:edit_file + run_command + 完成 → verify)
- 断言:
  1. step 0 (edit) → tier=cheap
  2. step 1 (verify) → tier=strong + approval_level_override=CONFIRM
  3. CostUpdate.tier_name 序列为 ["cheap", "default", ..., "strong", ...]
  4. strong 决策时,即使启动 AUTO 仍 yield ApprovalRequest(不是 silent 跑)

## 18. 决策记录(D1-D20)

| # | 决策 | 选项 | 拍板 | 理由 |
|---|---|---|---|---|
| D1 | 分类器实现 | 正则 / AST / LLM-judge | **正则 + 简单启发式** | 0 token,纯本地;LLM-judge 自身要 token |
| D2 | Tier 覆盖优先级 | per-tool > per-category > default | **per-tool > per-category > default** | 工具调用最具体,粒度最细 |
| D3 | Effort CLI 形态 | 全程 / per-call | **全程(`--effort=high <goal>`)** | per-call 用户操作成本高,per-run 简单 |
| D4 | Tier 切换与 prompt cache | 共享 / 各自 | **各自(切 tier = 换 prefix)** | prefix cache 粒度粗,跨 tier 共享难 |
| D5 | Cross-tier memory | cheap 看 strong 历史 / 反之 / 不看 | **不共享(cheap 看 cheap 历史;v1.1 统一)** | 跨 tier 记忆 = 跨强度幻觉叠加,先隔开 |
| D6 | Effort 字段 | 新 LoopConfig 字段 / 拆 preset | **拆 preset 填既有字段(max_steps/approval_level)** | 0 新字段,既有契约不变 |
| D7 | strong tier 强制 CONFIRM | 全局 / opt-in | **opt-in(tier_force_confirm,默认 ["strong"])** | 用户可显式关(强模型用 OBSERVE 模式只看不批) |
| D8 | Router 注入点 | 全局 var / LoopConfig / AgentLoop kw | **AgentLoop kw(向后兼容;c.router 透传)** | 既有 1507 测试 0 破坏 |
| D9 | Categorizer 失败 | 抛 / 兜底 | **兜底 `SIMPLE_READ`** | 启发式不该崩 run |
| D10 | /routing 历史长度 | 5 / 10 / 无限 | **10(deque maxlen)** | UI 友好,无限增长会成内存漏洞 |
| D11 | 路由 schema 兼容性 | 严格 / 宽松 | **宽松(未知字段忽略,已知字段类型校验)** | 远端可演进(v1.1 加 effort 同名键不影响) |
| D12 | RoutingConfig 写盘 | 原子写 / 直接覆盖 | **原子写(.tmp + os.replace)** | 跟 skills-curator / config.set_active 一致 |
| D13 | tier_force_confirm 默认 | `[]` / `["strong"]` | **`["strong"]`** | 强模型负责任;v1.1 改默认 |
| D14 | effort 写 LoopConfig.max_steps | 强制覆盖 / 允许 override | **强制覆盖(用户没 flag 不动)** | 既有 max_rounds=3 不动;effort 只动 max_steps |
| D15 | ActivityPanel tier 标签 | 短 3 字母 / 全名 / 颜色 | **短 3 字母 + 颜色(cheap=绿,default=灰,strong=红)** | UI 信息密度,3 字母够辨识 |
| D16 | /routing 无 router 注入 | 报错 / 静默 | **报错(诚实:你没接 router)** | demo / fake 路径不接 router,也不该用 /routing |
| D17 | RoutingConfig 错误配置 | 启动 fail / 静默降级 | **fail-closed(ConfigError)** | spec 灵魂"防假绿":路由拼错 fail-closed |
| D18 | 子 agent 是否走 router | 是 / 否 | **否(子 agent 仍走 task.model 字段,显式独立)** | 子 agent 在 workflow 引擎里,本期不动 |
| D19 | TUI tier 颜色 | 全 monospace / semantic | **semantic(cheap=绿,strong=红,default=灰)** | 用户扫一眼知 cost 等级 |
| D20 | RoutingConfig 内存 vs 磁盘 | 内存优先 / 磁盘优先 | **磁盘优先(每 build_components 重读)** | /routing set 改完下次 run 生效,简单一致 |

## 19. 风险与未来

- **风险 1**:cheap 模型在 refactor 任务上走 cheap,质量崩 → 解决:用户配
  `routing.by_category.refactor = "default"`,spec D11 留口子
- **风险 2**:强模型切档频繁 → 解决:`/routing` 暴露 history,用户自检 + D11 拼
  错 fail-closed
- **风险 3**:cross-tier memory 缺失 → v1.1 接 memory tier 共享(同 goal 同 project
  共享结果,只分强度不看对方历史)
- **风险 4**:prefix cache miss 增加 cost → v1.1 接 prompt caching 优化(同 tier
  共享 system prefix)
- **未来 v1.1**:
  - `argos routing` CLI 子命令(同 `argos skills`)
  - per-project `.argos/routing.json` 覆盖
  - 跨 run 路由历史持久化(接 store)
  - 路由决策学习(基于 eval 结果自动调权)
  - LLM-judge 分类器(可选,默认仍启发式)
  - 路由 A/B(同 goal 跑两个 tier,出对比)

## 20. 实施任务(对应 plan)

9 任务,1 任务 = 1 commit,完整 TDD,沿用 `#5b` / `#7` / `#9` / `#10` 风格:

1. `routing/` 骨架 + `TaskCategory` + `categorize()`(8 类别启发式)
2. `RoutingConfig` 加载器 + safe default + `set_category()` 原子写
3. `RoutingResolver.resolve()` 3 层优先级 + tier 名 fail-closed
4. `ModelRouter` 懒构造 + `select()` + history + `tier_force_confirm` 联动
5. `EffortLevel` + `EFFORT_PRESETS` + CLI `--effort` + `build_components` 接线
6. `CostUpdate.tier_name` 字段 + `AgentLoop` 注入 router 扩展(不修改流程)
7. TUI `/routing` + `/routing set` + COMMAND_HELP + ActivityPanel tier 标签
8. `tests/test_routing_e2e.py` 端到端铁证(cheap/default/strong 三档切换 + strong→CONFIRM)
9. 文档 + CHANGELOG + README 更新

## 21. 不触动清单(契约 §9 锁)

- **不**改 `ModelClient` 既有方法签名(`stream` / `complete` / `last_usage`)
- **不**改 `ModelClient.__init__` 既有必填参数
- **不**改 `core/loop.py` 流程(只在循环顶部加 `if router` 短路;既有 1507 测试 0 破)
- **不**改 `LoopConfig` 既有字段
- **不**改 `ApprovalGate` 既有签名
- **不**改 `Config` 加载器签名(只在 build_components 加 effort 参数)
- **不**改 `tui/commands.py` 既有 COMMAND_HELP(只加 "routing")
- **不**加 sqlite / 不加新外部依赖
- **不**起 daemon
- **不**接 MCP 工具路由(留 v1.1)
