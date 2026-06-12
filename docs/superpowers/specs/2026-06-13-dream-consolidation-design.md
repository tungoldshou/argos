# Dream 夜间整合 — 设计 spec

日期：2026-06-13
状态：已批准（brainstorming 三决策 + 七节设计均经用户确认）

## 背景与目标

`argos_agent/learning/` 已有单 run 学习闭环：daemon worker 收尾触发
`hook.on_run_completed` —— passed 且非 self_verified 走 `distiller`（模板化蒸馏，
不调模型）+ `promotion_gate`（A/B 晋升门）；其余走 `reflection` 写记忆。

两个缺口：

1. **生产路径晋升断电**：`daemon/worker.py` 调 hook 时传
   `runner_factory=None, tasks=[]`，而 distill 的候选不落盘 —— 等于 passed run
   蒸出的候选当场被丢弃，生产环境真正留下的只有 reflection。
2. **没有跨 run 整合**：不会把多次相似经验综合成泛化 skill，也没有空闲期
   批量整理记忆。

Dream = 夜间整合管道，一次补齐两者。产品不变量不动摇：
**只有验证通过的经验才能变成能力**（verification-gated self-improvement）；
Conductor **绝不擅自执行**（建议恒需用户确认）。

## 已拍板的决策

| 决策点 | 结论 |
|---|---|
| 综合机制 | **混合**：规则聚类；模型（cheap 档）只写叙述层（"何时适用/教训"），代码段与 verify 命令逐字复制自已验证材料，综合器剥离模型输出中的一切代码块；再过 A/B 晋升门 |
| 范围 | **skill 综合 + 记忆整理**（合并重复 reflection、归档衰减条目，永不硬删） |
| 触发姿态 | **默认注册夜间 builtin order + `/dream` 手动**；一切执行仍走 Conductor 确认流 |
| 架构 | **host 侧管道**（daemon 进程内），不是 agent run（沙箱开洞 / 编造风险 / 永远 unverifiable，三处顶铁律，否决） |

## 架构与数据流

```
夜间 cron tick（builtin-dream-nightly）        /dream 手动
        │                                        │
        ▼                                        ▼
  材料扫描（够料才建议，空料静默）── ProactiveSuggestion(kind=dream) ── /confirm
                                                 │
                                                 ▼
                                   DreamPipeline（host 侧，daemon 进程内）
                                    ① 聚类 → ② 综合 → ③ A/B 晋升 → ④ 记忆整理 → ⑤ 报告
```

新增模块：

- `argos_agent/learning/candidates.py` —— 候选落盘/读取/消费标记。
- `argos_agent/learning/dream.py` —— DreamPipeline 本体（聚类/综合/晋升/记忆整理/报告）。

复用不改语义：`distiller.py`、`promotion_gate.py`、`eval/runner.py`、
`conductor/` 触发器、`memory/` 存储。

## 1. 材料模型 + 通电修复

- `hook._on_passed` 无 runner 时：候选从"丢弃"改为**落盘**到
  `~/.argos/learning/candidates/<name>-<run_id>/`：
  - `SKILL.md` —— distiller 产物原文；
  - `meta.json` —— `{source_run, verify_cmd, workspace, created_at, consumed}`。
- 候选区不在 `skills_root`，skills 加载器不读它 —— 不会未晋升先生效。
- Dream 输入 = 未消费候选 + 已晋升 skills（frontmatter `source_run`）+ 未消费
  reflection（memory 中 `task_reflection` 条目）。

## 2. 聚类与综合（铁律边界）

- 聚类特征：goal 文本 + verify_cmd + 代码 token 相似度；有 embedder 用
  embedding（`llm_embed`），不可用降级 token 重叠（与 memory 同款降级阶梯）。
- 簇 ≥2 → 综合泛化候选；**单例候选也进 A/B**（顺手通电单 run 晋升）。
- 综合产物结构：
  - 代码段、verify 命令：**逐字复制自源材料**，每段标注 `source_run`；
  - "何时适用 / 教训（Pitfalls）"叙述层：模型（cheap 档）生成，可引用
    reflection 文本；
  - **硬防线**：综合器剥离模型输出中的一切 fenced code block —— 可执行内容
    永远不可能出自模型之手；模型调用失败 → 叙述层降级为模板文字（功能不死）。
- 预算：每晚最多 3 个整合单元（簇或单例统一计数，防失控烧 token）。

## 3. A/B 晋升与诚实降级

- EvalTask 从各源的 verify_cmd + 源 workspace 构造；workspace 已消失 → 跳过该源。
- 可用任务数 = 0 → 不晋升、候选保留、报告注明 `no_tasks_available` ——
  **无证据绝不写盘**。
- runner 用真 `EvalRunner`（worktree 隔离 + daemon 的 loop_factory；B 侧注入
  skill hint，A 侧不注入）。
- `promotion_gate.promote` 原样复用：B 严格 > A 才晋升、builtin 名字硬拒、
  晋升产物 `enabled: false`（沿用 install 的 user review gate）。
- 消费标记规则（防"夜夜建议同一批"死循环）：
  - 晋升或明确拒绝（A/B 跑完未过）→ 标记 `consumed`；
  - 源 workspace 已消失 → 也标记 `consumed`（带 reason，证据永远拿不到，
    重试无意义）；
  - 仅临时性失败（runner 构建失败、模型调用失败等）不标记，下晚重试。

## 4. 记忆整理

- 合并：同 scope 高相似 reflection → 留最新、use_count 累加（相似阈值在
  实现计划中定，默认保守 —— 宁可不合并不可误合并）。
- 归档：分数衰减到阈值以下（默认 0.2，可配置）→ 移入同目录 `archive.jsonl`。
- **永不硬删**；整理动作计入 Dream 报告。

## 5. Conductor / daemon / UX 接线

- `StandingOrder`、`ProactiveSuggestion`、`ProactiveSuggestionEvent` 增加
  `kind` 字段，默认 `"run"`（协议加法，向后兼容，golden test 同步）。
- daemon 启动时注册 `builtin-dream-nightly`（默认 03:00，cron-lite）；tick 时
  扫描材料，够料（≥1 簇或 ≥3 条未消费材料）才产生建议，空料静默。
- `requires_confirmation` 恒 True 不变；confirm 处理器按 `kind=dream` 路由到
  DreamPipeline（不走 `create_run`）。
- 新事件 `dream_progress` / `dream_report`（`protocol/events.py`）经 SSE 广播；
  报告落 `~/.argos/dreams/<date>.jsonl`。
- TUI：`/dream` 立即跑（同一确认流后执行）、`/dream status` 看上次报告。
- CLI twin：`argos dream`（惯例同 eval/skills/context）。

## 6. 错误处理

- 与 learning/ 同纪律：管道任何阶段异常 → log + 报告该簇 `skipped`，
  绝不拖挂 daemon 主服务、绝不抛回 caller。
- 模型叙述层失败 → 模板文字降级。
- E4 防火墙延续：self_verified 来源的材料绝不进入综合/晋升。

## 7. 测试与交付

- 测试风格延续：fake runner / scripted model；新事件 golden tests；daemon
  测试守 `ARGOS_NO_DAEMON=1` 与 xdist group 纪律；真子进程标 `@pytest.mark.slow`。
- 全量 80% 覆盖率闸门不动。
- 文档：`docs/dream.md`（一文档一特性）+ README 节 + CHANGELOG 条目。

## 明确不做（v1 边界）

- 不让模型写任何可执行内容（代码/命令）。
- 不做跨项目 skill 共享/上传。
- 不做空闲检测触发（只有 cron + 手动）。
- 不动单 run distill 的模板化设计。
- 记忆整理不做语义级改写，只做合并/归档。
