# Dream 夜间整合 — 跨 run 自进化 + 记忆整理

> 别让一次通过的经验被丢弃。 `argos_agent/learning/` 现在会在夜间把多次相似的已验证 run
> 聚类、综合成泛化 skill，再过 A/B 晋升门；同时整理记忆、合并重复、优雅衰减。
> 灵魂一句话：**只有验证通过的经验才能变成能力，夜间管道不擅自执行，建议恒需确认**。

## 一句话

夜间定时（或手动）扫描未晋升的候选、已晋升 skill、未消费反思，聚类相似的、综合成泛化经验、
过 A/B 晋升门、整理记忆。全程验证门控，所有建议都需用户确认。

## 为什么需要

### 单 run distiller 的缺口

`argos_agent/learning/` 早就有单 run 学习：当一个 run **通过验证** 时，daemon worker 触发
`hook.on_run_completed`，把 distiller 产物（简化版 skill）送进晋升门（A/B 对比）。

**但有两个生产缺口**：

1. **候选丢弃**：当 daemon 调 hook 时传 `runner_factory=None` 时，distiller 产物当场被丢弃，
   不落盘。等于只有走过 A/B 晋升门的 skill 才值得留下——大量轻微不同的优化机会死掉。

2. **没有跨 run 整合**：相同目标的 5 次成功 run 各留各的 skill，不会被综合成一个泛化、
   可配置版本。空闲期也没有批量整理记忆、合并重复。

### Dream 补齐两个缺口

一个完整的夜间管道，让候选**落盘 → 扫描 → 聚类 → 综合 → A/B 晋升 → 记忆整理**，把多次
相似的已验证经验智能合并。产品不变量不动摇：**只有验证通过的经验才能变成能力**
（verification-gated self-improvement）。

## 核心铁律（与 distiller 同源）

所有下述规则在 `argos_agent/learning/dream.py` + `candidates.py` 代码里都有断言钉死：

1. **代码段和 verify 命令逐字来自已验证源**：模型只能写叙述层（"何时适用 / 注意事项"），
   一切可执行内容都从源候选复制，不经模型之手。综合器会剥离模型输出中的一切 fenced code block
   作为硬防线。
2. **无证据绝不晋升**：workspace 消失 / 无有效 A/B 任务 → 跳过该簇，候选保留，报告注明原因。
3. **E4 防火墙**：self-verified 的候选（用户级验证未通过就已为真）永远不进材料库。
4. **建议恒需确认**：Conductor 的 `requires_confirmation` 恒 `True`；没有"静默夜跑"。
5. **永不硬删**：记忆整理（合并重复、衰减归档）绝不物理删除条目，只标记衰减或合并。

## 完整数据流（6 个阶段）

```
夜间 cron tick (builtin-dream-nightly, 03:00)      /dream 手动触发
        │                                            │
        ▼                                            ▼
  ① 扫描材料（候选 + reflection + 已晋升 skill）
        │
        ▼ （空料静默，≥1 簇或 ≥3 条未消费材料才建议）
        │
  ② ProactiveSuggestion(kind=dream) —— 需用户确认
        │
        ▼
  ③ DreamPipeline（daemon 进程内，host 侧管道）
        │
        ├─→ 聚类（token Jaccard，簇 ≥2 或单例各自参加 A/B）
        │
        ├─→ 综合（模型仅写叙述层，代码 / verify 逐字复制源，三层 fence 剥除）
        │
        ├─→ A/B 晋升（B 严格大于 A 才晋升，同名覆盖）
        │
        ├─→ 记忆整理（同 key 合并，衰减归档）
        │
        └─→ 报告落盘（~/.argos/dreams/<date>.jsonl）
```

## 目录与文件布局

```
~/.argos/
├── learning/
│   └── candidates/                  # 候选区（晋升前）
│       ├── <name>-<run_id12>/
│       │   ├── SKILL.md             # distiller 产物原文
│       │   └── meta.json            # {source_run, verify_cmd, workspace, created_at, consumed, consumed_reason, self_verified}
│       └── ...
├── dreams/                          # Dream 报告（可覆盖为 ARGOS_DREAMS_DIR）
│   ├── 2026-06-13.jsonl            # {kind, status, sources, details, timestamp}
│   └── ...
└── memory/
    ├── user.jsonl                  # 用户层记忆（含衰减字段）
    ├── projects/<hash>.jsonl       # 项目层记忆（含 consolidate 操作日志）
    └── archive.jsonl               # 已归档条目（衰减到阈值以下）
```

**E4 纵深防御**：候选区里的 `self_verified` 字段显式记录来源（True = 不进综合）；
`list_unconsumed()` 二次拒绝（代码硬断言）。

## 命令

### TUI 命令

```
/dream                    # 立即运行一轮整合（同一确认流后执行）
/dream status             # 显示上次报告内容
```

### CLI 命令

```bash
argos dream               # 立即运行一轮整合
argos dream --report      # 显示最新报告
```

## 端点（daemon HTTP/SSE）

```
POST /dream/run           # 触发一轮整合（请求体为空或 {dry_run: bool}）
GET  /dream/report        # 获取最新报告（owner 鉴权）

SSE 事件
  - dream_progress        # 进度更新（kind, status, sources, details）
  - dream_report          # 最终报告（完整报告 JSONL）
```

## 候选消费规则（防止"夜夜建议同一批"死循环）

| 情形 | 消费标记 | 理由 |
|---|---|---|
| 晋升或明确拒绝（A/B 跑完未过） | ✓ consumed | 已做过决策 |
| 源 workspace 已消失 | ✓ consumed + reason | 证据永不可得，重试无意义 |
| 仅临时性失败（runner 构建失败、模型超时等） | ✗ 不标记 | 下晚重试 |

## 与 E4 防火墙的关系

E4 防火墙（`argos_agent/verify/` + `permissions/`）防止"自验证 run 进晋升渠道"。
Dream 在此基础上再加**两层纵深**：

1. **候选落盘层**：`save_candidate(..., self_verified=bool(...))`，源记录在 `meta.json`。
2. **材料扫描层**：`list_unconsumed()` 硬拒 `self_verified=True` 的候选（代码断言）。

即使上游有漏洞，下游也堵住。

## 配置

### 环境变量

- `ARGOS_DREAMS_DIR` — 报告目录（默认 `~/.argos/dreams/`）

### 关闭夜间自动整合

在 `~/.argos/conductor/orders.json` 中，修改或删除 `builtin-dream-nightly` 的 `enabled: true` 字段：

```json
{
  "orders": [
    {
      "id": "builtin-dream-nightly",
      "trigger": {"kind": "cron", "pattern": "03:00"},
      "enabled": false,
      "action": "dream"
    }
  ]
}
```

手动触发仍可用（`/dream` / `argos dream`）。

## 聚类算法

**贪心单链聚类**（O(n²)，夜间规模 n < 100 可忽略）：

- 依次检查每个候选，归入首个相似度 ≥ 0.35（token Jaccard）的簇。
- 相似特征：`goal` 文本 + `verify_cmd` 的 token 重叠。
- 有 embedder（`llm_embed`）时用 embedding，不可用时降级 token 重叠。
- **双车道上限**：多源簇（≥2 个源）与单例各自最多 3 个单元参加整合，防失控烧 token。
- **超大簇截取**：单个综合单元源上限为 5；超出的源保持未消费，下晚重新聚类。

## 综合产物结构

一个综合出的 skill（`SkillCandidate`）包含：

```
# Dream Consolidated <name>

**何时适用**：<模型生成叙述，code block 已剥除>

**注意事项**：<模型生成叙述，code block 已剥除>

## 来源

<每个源候选的目标与 verify 命令，源 run_id 标注>

## 代码

<逐字复制自源 SKILL.md，无任何模型改写>

## Verify 命令

<逐字复制自最早源的 verify_cmd>
```

模型叙述层生成失败 → 模板兜底（"本技能综合自 N 次已验证通过的 run（目标见下），适用于同类任务"）。

## A/B 晋升

- **A 侧**（control）：原始候选，不注入 skill hint。
- **B 侧**（treatment）：综合产物，带 skill hint（模型可参考）。
- **晋升条件**：B 严格大于 A（pass_rate、cost、speed 二选一胜出）；同名 skill 自动覆盖。
- **晋升产物**：`enabled: false`（user review gate，沿用 install 流程）。
- **无证据拒晋升**：workspace 消失 / 无有效任务 → 报告 `no_tasks_available`，候选保留。

## 记忆整理（consolidate）

不做语义级改写，只做合并 + 衰减 + 归档：

- **合并**：同 scope、高相似 reflection 条目（阈值待实现，默认保守）→ 留最新，`use_count` 累加。
- **衰减**：分数衰减到阈值以下（默认 0.2，可配置）→ 移入 `archive.jsonl`。
- **永不硬删**：整理动作计入 Dream 报告，条目元数据标记操作时间与原因。

## 性能与成本

- **聚类**：O(n²)，n < 100（夜间规模），毫秒级。
- **综合**：最多 3 个单元，每个最多 5 个源；模型调用 ≤ 3 次（cheap 档）。
- **A/B 晋升**：eval runner 复用，worktree 隔离，真验证。
- **记忆整理**：线性扫描 + 条件更新，毫秒级。

**成本上限**：综合失败 → 模板兜底，不烧 token；A/B workspace 消失 → 推荐诚实拒绝，不强行。

## 明确不做（v1 边界）

- 不让模型写任何可执行内容（代码 / 命令）。
- 不做跨项目 skill 共享 / 上传（local-only）。
- 不做空闲检测触发（仅 cron + 手动）。
- 不动单 run distiller 的模板化设计（skill 格式保持一致）。
- 记忆整理不做语义级改写，只做合并 / 衰减 / 归档。
- 不做 embedding 聚类（本期用 token 重叠，embedding 降级路径同 memory）。

## 相关文件

- `argos_agent/learning/dream.py` — DreamPipeline、聚类、综合
- `argos_agent/learning/candidates.py` — 候选落盘与扫描
- `argos_agent/learning/distiller.py` — 单 run 产物生成（Dream 的源头）
- `argos_agent/learning/promotion_gate.py` — A/B 晋升（Dream 与单 run 共用）
- `argos_agent/memory/consolidate.py` — 记忆合并 + 衰减 + 归档
- `argos_agent/conductor/` — 夜间 builtin order、提案生成
- `argos_agent/daemon/server.py` — `/dream/run` 与 `/dream/report` 端点
- `argos_agent/cli/dream.py` — CLI 子命令 `argos dream`
- `docs/superpowers/specs/2026-06-13-dream-consolidation-design.md` — 完整设计规格
