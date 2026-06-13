# Argos「工厂」转型总路线图

> **[已取代 2026-06-11]** 本路线图被 v6 总设计取代：`docs/argos-v6-design.md`。
> 契约引擎（P1）与证据包思想被吸收为 v6 验证梯子 L2 与 Ledger 的组成部分，不再是独立主线。

> 目标形态(2026-06-11 对话定稿):**一个目标进来,一个验证过的交付物出去——任何模型,最短壁钟时间。**
> 流水线:目标 → 意图卡 → 契约化产物 DAG → 接口先行并行子代理 → verify-diagnose-retry →
> 端到端验收 → 证据包交付。设计核心:**每两级之间放验证闸,误差不往下传;自动化的是工厂,不是承诺。**
>
> 本文件是 7 个阶段的总图;每阶段一份独立实施计划(本目录),各自交付可工作软件。
> 阶段 1 的详细计划:`2026-06-11-phase1-contract-engine.md`。

## 目标架构

```
                       ┌─────────────────────────────────────────────┐
 goal ──► IntentCard ──► Contract(总) ──► ArtifactDAG(节点=产物+契约) │ P2  P1  P3
          (15s 确认闸)   │                    │ 接口冻结(P4)           │
                       ┌─┴────────────────────▼─────────────────────┐
                       │  并行子代理(worktree 隔离,按节点配给上下文)   │ P4
                       │  每节点:生成→契约检查→诊断→重试→升级(P5)     │
                       └─────────────────────┬───────────────────────┘
                          集成代理 → 端到端验收(对意图卡) → 证据包     │ P6
                                                                     
 横切:harness 深度自适应(P7,eval 数据驱动拆解粒度/闸门开关)
 不变量:三态判决/诚实协议/签名回执/沙箱 broker —— 原样保留,不许放松
```

## 模块地图(目标态)

| 模块 | 职责 | 阶段 |
|---|---|---|
| `argos/contracts/` | Check/Contract 类型、三态契约执行器、模型合成+fail-closed 解析 | P1 |
| `argos/intent/` | IntentCard、歧义面试(只问改变方案的问题)、确认闸 | P2 |
| `argos/planner/` | 产物 DAG 拆解(节点=产物+契约)、DAG 校验、预览渲染 | P3 |
| `argos/orchestrator/` | 接口冻结、worktree fan-out、节点上下文配给(改造现 workflow/) | P4 |
| `argos/ladder/` | 诊断→重试→换策略→换模型梯子;节点级 fail-with-evidence | P5 |
| `argos/delivery/` | 集成代理、端到端验收、EvidenceBundle、`argos verdict` | P6 |
| `argos/depth/` | 模型×任务类能力表(吃 eval 数据)→ 拆解粒度/闸门策略 | P7 |

保留复用:core/(loop/verify_gate/honesty)、sandbox/、permissions/、tui/(v2)、eval/、daemon/。
逐步退役:routing/ 的档位语义并入 P5 升级梯子;workflow/spec 并入 P3 产物 DAG。

## 阶段与验收

**P1 契约引擎**(基础,其余全依赖它)
交付:`contracts/` 包——4 种 Check(exit_code/artifact_exists/artifact_schema/content_assert)、
Contract 三态执行(复用 Verifier 白名单+隔离)、模型合成+fail-closed 解析;接进现有单 agent loop
(有契约走契约,无契约走旧 verify_cmd,行为不回退)。
验收:`uv run pytest tests/contracts/` 全绿;真 run 配 JSON 契约能产出三态 VerifyVerdict。

**P2 意图卡**
交付:`intent/` —— IntentCard(交付物形态/硬约束/验收检查/不做什么)、面试器(≤3 个选择题,
只问改变方案的)、确认闸(TUI 走 InlineChoice 复用,headless 走 `--yes`/超时默认)。
验收:模糊目标("做个博客")触发 ≤3 问;明确目标 0 问直出卡;卡确认后才合成契约。

**P3 产物 DAG 拆解**
交付:`planner/` —— ArtifactNode(产物+契约+依赖)、模型拆解+DAG 校验(无环/每节点有检查/
产物不重叠)fail-closed、预览渲染(复用 plan mode 审批管线)。
验收:中型目标拆出 3-8 节点 DAG,坏拆解(环/无检查节点)被拒绝并要求重拆而非带病放行。

**P4 接口先行并行**
交付:`orchestrator/` —— 接口冻结阶段(边界产物先生成:schema/文件归属/命名),按 DAG 依赖
fan-out 子代理(worktree 隔离,节点只拿自己契约+相邻接口,不拿全历史),事件流进 TUI 进度树。
验收:2 节点可并行任务壁钟 < 串行 70%;子代理上下文中无兄弟节点历史(配给铁证)。

**P5 修复梯子**
交付:`ladder/` —— 节点循环:契约检查失败 → 诊断(失败证据回喂,非裸重跑)→ 重试预算 →
换策略 → 换模型(任意模型注册即入梯)→ 仍败则节点标 failed 带证据上交,不拖死整体。
验收:注入必败节点,run 仍完成且交付物里该节点 failed+证据;诊断重试通过率 > 裸重跑(eval 对照)。

**P6 集成验收 + 证据包**
交付:`delivery/` —— 集成代理(拼装+冲突消解)、端到端验收(对 IntentCard 的总契约,非节点
检查之和)、EvidenceBundle(verdict 树+签名回执+diff/截图/引用+诚实缺口清单)、`argos verdict <run>`。
验收:端到端检查能抓住"节点全绿但整机不转";bundle 可独立校验签名。

**P7 harness 深度自适应**
交付:`depth/` —— 能力表(模型×任务类 verified 完成率,源=eval/results)、深度策略(强模型→
粗拆/减闸,弱模型→细拆/全闸)、策略可解释(`/depth` 显示为什么这么拆)。
验收:同一任务,强模型路径节点数 < 弱模型;强模型壁钟不高于其裸跑 +15%(反 Devin 病红线)。

## 顺序与风险

- 依赖链:P1 → (P2, P3) → P4 → P5 → P6 → P7;P2 与 P3 可并行。
- 每阶段必须独立可交付——P1 完成后单 agent 已获得"通用任务可验证"能力,即使后面全不做也值。
- 最大风险在 P4(并行集成质量)——接口冻结做不好,并行是负收益;P4 验收不达标就停在
  "DAG 串行执行"形态,仍是完整产品。
- 不变量红线:任何阶段不得放松三态/诚实/沙箱;深度自适应只许减闸门数量,不许把 failed 说成 passed。
