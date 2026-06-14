# Argos v6 — 总设计「可托付的贾维斯」(Confidant)

> **实现状态：P0-P6 已全部实现，2026-06-12。**

> 一句话：**让任何人对着一句话说出意图，便宜模型也交付「机检证据背书、绝不撒谎、可回放可撤销」的结果 —— 一个会说"我不会"的自治伙伴。**
>
> 形态：headless 内核（argosd）+ 协议（ACP）+ 多客户端（TUI v3 已完成 / 桌面端预留）。
> 定稿：2026-06-11。设计来源：8 路子系统侦察审计 + 3 派架构提案 + 3 镜头评审团裁决
> （全档案见 `docs/superpowers/plans/2026-06-11-v6-recon-audits.json` 与 `2026-06-11-v6-design-panel.json`）。
> 本文取代 v5 产品定义的架构部分与「工厂」转型路线图（其契约引擎/证据包被吸收为本设计的验证梯子第二级）。

---

## 1. 产品重定向（用户指令，2026-06-11）

- **Jarvis 级超级智能体**：人为介入极少、高度自治。
- **目标用户是所有人**，不只是开发者 —— 自然语言进、人话出，易用是硬要求。
- **多形态**：TUI（v3 黑曜石之眼，视觉层不动）→ 桌面端（类 codex/Claude desktop），能操作电脑一切。
- **扩展机制全支持**：skills / 插件 / MCP，市面上有的都要有。
- **灵魂不变**：verify 硬门禁、三态判决、诚实协议、沙箱 broker —— 只能加强。

## 2. 灵魂：护城河在 v6 如何加强（而非稀释）

### 2.1 四件套升格为内核语义

护城河不是"功能"，是内核的**系统调用语义**：任何客户端、任何能力、任何自治触发器要产生副作用，
唯一路径是穿过 `CapabilityBroker`（egress → 审批 → 执行 → HMAC 回执），物理上绕不开。

### 2.2 `unverifiable` 是 wire-level 判决值

三态判决随协议序列化：客户端解析到 `unverifiable` 必须照实渲染，**没有把它粉饰成绿色的接口**。
诚实从系统提示约束升格为协议不变量。

### 2.3 验证梯子（回答"所有人方向最大的灵魂矛盾"）

非命令型任务大多无法预置 `verify_cmd`。v6 的答案不是回避，是**显式分级 + 诚实退路**：

| 级 | 证据 | 强度 | 来源 |
|---|---|---|---|
| L1 | 命令退出码（pytest/编译/lint） | 最强 | 现有 verify_gate |
| L2 | 产物断言（artifact_exists / schema / content_assert） | 强 | 吸收契约引擎 P1 |
| L3 | 外部状态核验（DOM 断言 / API **内容**回读） | 中 | Verify Strategy Generator |
| L4 | 截图/VLM 比对 | 弱（置信度低 → 降 unverifiable） | computer-use 配套 |
| L5 | 无机检证据 | **诚实 unverifiable** + Ledger 留痕 + 人话"请你过目" | 诚实协议 |

**反吸收红线（评审团明令）**：传输层成功 ≠ 任务正确 —— "API 返回 200" 不是验证证据
（发错人/发错内容仍 200）。L3 必须回读**内容**做断言，否则降 L5。

**产品话术**：护城河在非命令型任务上从「保证正确」退到「留痕可复盘」——这是能力边界，不是 bug，
而且是诚实卖点：验不了时不装绿，给你证据链和撤销按钮。

### 2.4 NL→Goal 翻译盲区（显式登记）

口语→Goal 的翻译若错（"删草稿"理解成"删全部"），verify 验的是翻译后的 Goal，验不出翻译本身。
对策：**意图确认回路** —— Intent 卡片回显人话（"我理解你要 X，对吗"），高风险/不可逆意图强制确认；
这是护城河上游的必要闸，不是可选 UX。

## 3. 总架构

```
                 ┌────────────────────────────────────────────────┐
  客户端(shell)   │  TUI(v3,不动视觉) │ 桌面端(Tauri+sidecar,预留) │ CLI │
                 └──────────────────┬─────────────────────────────┘
                                    │ ACP 协议(Unix socket + SSE;Event/Command/RPC;版本协商)
  ══════════════════════════════════╪═════════ 内核/客户端边界(进程隔离) ═════════
                 ┌──────────────────▼─────────────────────────────┐
                 │              argosd 内核(headless)              │
                 │ ┌─ 运行时 ────────────┐ ┌─ 认知面 ───────────┐ │
                 │ │ AgentLoop 四阶段     │ │ memory(+人物画像)   │ │
                 │ │ Harness 相位锁       │ │ routing(泛化类目)   │ │
                 │ │ Verifier 三态门+梯子 │ │ context / learning  │ │
                 │ │ Intent NL→Goal      │ └────────────────────┘ │
                 │ │ Conductor 自治调度   │ ┌─ 信任面 ───────────┐ │
                 │ └─────────┬───────────┘ │ Egress→审批→回执    │ │
                 │           ▼             │ Trust Dial L0-L4    │ │
                 │ ┌─────────────────────┐ │ HARD RULES(不可降级)│ │
                 │ │ CapabilityBroker    │◄┤ Ledger 行为账本     │ │
                 │ │ = 唯一副作用陷入口   │ └────────────────────┘ │
                 │ │ registry.dispatch() │                        │
                 │ └─────────┬───────────┘                        │
                 └───────────┼────────────────────────────────────┘
                             │ 沙箱 RPC(子进程)
                 ┌───────────▼────────────────────────────────────┐
                 │ SeatbeltExecutor(CodeAct) │ ComputerExecutor    │
                 │ userland 能力:tools/skills/插件/MCP/browser     │
                 │ → 全部以 Capability manifest 注册,必经 broker   │
                 └─────────────────────────────────────────────────┘
```

以下包均已落地（v6 P0-P6 完成）：`argos/protocol/`（事件+envelope+序列化 ABI）、`argos/capability/`
（统一注册表）、`argos/intent/`、`argos/ledger/`、`argos/conductor/`、
`argos/perception/`（computer-use 执行器）。`daemon/` 已提拔为内核装配主线。
`tui/events.py` 留 re-export shim。**不动**：`tui/widgets/`、`glow/theme/sync_output`（TUI 私有）、
`git_worktree.py`、Seatbelt 子进程协议、daemon 的 state_machine/store/index/sessions。

## 4. ACP 协议（Argos Client Protocol）

- **Envelope**：`{v, seq, kind, id, ts, session, run, data}`（seq 单调递增，供客户端检测丢帧/乱序）；黄金 JSON 快照测试防漂移。
- **三类帧**：Event（内核→客户端广播；现有 Event union 升格，serialize/deserialize 已存在且有测试）、
  Command（客户端→内核：create_run/cancel/pause/resume/approval_response/plan_decision/setup_apply…）、
  RPC（幂等查询：list_runs/context_snapshot/capabilities/health）。
  实现说明：v1 中 Command/RPC 不是独立帧类，而是对应 HTTP 端点（`POST /runs`、`POST /runs/{id}/cancel|pause|resume|plan_decision`、`GET /runs`、`GET /health` 等，见 `daemon/server.py`）；Event 经 SSE 流广播。
- **版本协商**（设计预留，v1 未实现）：首帧 `Hello{client_v, accepts}` → `Welcome{kernel_v, proto_v, capabilities}`；
  不匹配明确拒绝并说明（诚实原则延伸到协议层，不静默降级）。当前传输为普通 HTTP，无握手帧；版本只通过单向 `GET /version` 暴露。
- **新事件**：`PlanDecisionRequest`（去掉 TUI 对 loop 对象的直接引用，机制与 ApprovalRequest 同构）、
  `MemoryRecallEvent`（修 store 穿透）、`ComputerActionEvent`、`LedgerEntryEvent`。
- **Event 双层措辞**（设计预留，v1 未实现）：每个事件带 `plain`（人话）/`technical`（技术）两份渲染源；
  非开发者模式读 plain（"我检查过了，这步确实做成了 ✓"），开发者模式读 technical。TUI 视觉层零改动。
  （当前 `argos/protocol/events.py` 无 `plain`/`technical` 字段。）
- 传输：本地 Unix socket（沿用 DaemonHTTPServer）+ SSE fan-out；桌面端 sidecar 同 socket；
  未来远程必须加 token/HMAC 握手。

## 5. 能力模型：CapabilityRegistry

一切能力（tool/skill/plugin/MCP/computer/browser/hook）= 一个 manifest：

```python
Capability(
  name,              # = broker action 名(沿用字符串契约)
  kind,              # tool|skill|mcp|computer|browser|hook|plugin
  risk,              # 强制声明;缺失 = 注册期 fail-closed 报错
  reversible,        # bool | 由动作语义推导;喂 Ledger undo 与审批文案
  egress_hosts,      # 网络能力声明出网域名 → EgressPolicy 热更新(修 MCP 重启才生效)
  schema,            # 入参 JSONSchema(边界校验)
  verify_hint,       # 该能力产物如何机检 → 喂验证梯子 L2/L3(评审团:最务实的反 unverifiable 路径)
  visibility,        # 用户角色过滤(LSP 等开发者能力对普通人不可见)
  dispatch,          # host 侧执行
)
```

- `registry.register()` 一次写入 `_RISK`/egress/namespace/names —— **加能力=注册一个 manifest，
  不改四处**（写成硬回归测试）。`broker._execute` if/elif → `registry.dispatch()`。
- 顺手修真 bug：LSP 动作在 `_execute` 有分发却不在 `_RISK` 表（fail-closed 误拒）。
- 第三方供应链：ed25519 签名 + vet（skill-vetter 形态）+ source 标注；护城河三参数
  （risk/verify_hint/egress_hosts）缺失在注册期/加载期/执行期三道 fail-closed。
- skills 从"纯提示注入"升级为 callable capability（保留召回注入路径作为 prompt-skill 子类）。
- hooks 收编进审批面（用户代码仍沙箱外跑，但安装/启用要过审批 + 显著警告，不再裸跑）。

## 6. 信任面

- **审批跨进程**：`ApprovalGate` 的 `asyncio.Future` → `pending_approvals: dict[call_id, Future]`
  注册表 + ACP 路由（call_id 已有，是最小改动点）；多客户端批同一把锁。
- **Trust Dial L0-L4** 替代 `/yolo`：L0 每步问 / L1 危险才问 / L2 不可逆才问 / L3 同类批过放行 /
  L4 全自治。**HARD RULES 永不被拨盘降级**。升档建议必须显式警示（"你正在放宽某类权限"），
  防止训练用户无脑点允许。
- **HARD RULES 扩到非开发者域**：金融/转账/下单/发邮件/系统设置授权 → 强制 CONFIRM、永不自治执行
  （是"必须人确认"而非"完全禁止"——比竞品默认封锁更可用）。
- **行为账本 Ledger**：HMAC 回执沉淀为人话条目 + 撤销三态 —— 可逆动作挂 undo_token
  （复用 snapshot/worktree）；不可逆动作诚实标红"无法撤销"；**绝不假装 GUI 操作可整体回滚**。
  这是"敢放手因为能反悔"的信任地基，与诚实协议同构。
- **审批说人话**：`ApprovalRequest` 双轨 `human_reason`（默认显示："我要删掉 build 文件夹，
  可恢复，里面是自动生成的，允许吗？"）+ `technical_reason`（折叠详情）+ reversible 红绿灯。

## 7. 人话层（intent/）

- **Intent 预处理器**：口语 → Goal + 候选验证策略；缺关键信息主动澄清（只问改变方案的问题）；
  高风险意图强制确认回路（§2.4）。
- **报告人话化**：三态判决翻译 —— passed→"我检查过了，确实做成了"；failed→"没做成，这是原因"；
  unverifiable→"这件事我没法自动验证对错，老实告诉你，需要你看一眼"。
- slash 命令能力升内核 API（桌面端复用），TUI 命令面板只是其一个入口。

## 8. 认知面

- 记忆加**人物画像层**（偏好/习惯/环境约束："惯用中文"、"这台机器别跑 sudo"）+ 非代码 domain 事件。
- routing `categorize()` 从 8 类代码操作泛化到非代码任务类目（信息检索/文书/操作流），
  避免非代码任务全退化 default tier。
- embedder 解绑 MiniMax 硬编码 → 以 Capability 注册（MLX 本地作离线默认）。
- learning 蒸馏扩展到非 CodeAct 轨迹（浏览器/计算机操作序列）。

## 9. 自治面（conductor/）

- Scheduler（cron/间隔）+ Triggers（文件/事件）+ Standing Orders（人话立规矩，落 JSONL）。
- 自治 run **默认 worktree 隔离**（评审核实现状默认关）：半夜跑的活在隔离树里，验证过了才合并。
- 触发的 run 走完整护城河（同一陷入口），优先级队列 + 并发槽位沿用 daemon registry。
- 主动建议（ProactiveSuggestion）一键转 run，不擅自执行。

## 10. Computer Use（perception/）

- 分级推进：先浏览器内（复用 BrowserController/Playwright，可 per-run 隔离），
  后 OS 级（macOS Accessibility + 截图 + 输入）。
- `computer.*` 以 Capability 注册：高 risk、进 `_RISK`/egress/审批/回执四线管辖。
- **沙箱诚实性（结构性妥协，照实写）**：屏幕/鼠标是全局资源，Seatbelt 关不住 ——
  用"审批 + Ledger + 高 risk"治理，**不假装文件级隔离能挡屏幕操作**（沿用 project-mode 房规）。
- **VLM 验证红线**：截图比对是比退出码弱得多的验证基础，"VLM 误读弹窗 = 假 passed"是新假绿灯入口；
  置信度低一律降 unverifiable。

## 11. 桌面端（预留通道）

Tauri 壳 + argosd sidecar，同一 Unix socket 协议，内核零改动；
TUI 与桌面端订阅同一 run 的 SSE 实时同步。打包新增 client-only 规格。
（实施排最后阶段，协议与事件双层措辞从 P0 起就为它铺路。）

## 12. 工程事实清单（评审团逐条核实，实施必读）

1. ~~`runtime.py:65` **早已是 contextvars.ContextVar** —— 不要重写 per-run；
   真正要修的是 `_DEFAULT_CTX` 共享可变单例隐患（runtime.py:64 docstring 已警告）。~~
   **✅ 已完成（P1）**：`_DEFAULT_CTX` 已移除；`runtime.py` 全面切换至 ContextVar，每 run 独立上下文。
2. ~~真·进程单例需去全局的只有：`plan_mode` 模块布尔、`permissions.get_config/get_audit_log`、
   `McpManager`、`BrowserController`、`os.environ['ARGOS_WORKSPACE']` 副作用。~~
   **✅ 已完成（P1）**：上述全局单例已在 P1 内核通电中清除。
3. ~~`tui.events` 爆炸半径 = **52 个文件**（15 生产 + 37 测试），shim 必须保住全部 import 路径。~~
   **✅ 已完成（P0）**：`tui/events.py` re-export shim 已就位；爆炸半径实测约 40 个文件，全部 import 路径保住。
4. ~~`RunWorker.__init__` 已收 `loop_factory`（worker.py:51）但**零 caller** —— P1 通电就是接这根线。~~
   **✅ 已完成（P1）**：`loop_factory` 已在 daemon/server.py 中接入，约 4 处调用点全部通电。
5. `serialize_event/deserialize_event/_KIND_TO_CLASS`（tui/events.py:299-321）已存在且有
   round-trip 测试 —— 协议 ABI 是升格不是发明。
6. ~~真 bug：LSP 动作（lsp_definition 等）在 `_execute` 有分发、不在 `_RISK` 表。~~
   **✅ 已修复（P2）**：`capability/builtins.py` 已将 LSP 动作以 `kind="lsp"` 注册入 CapabilityRegistry，broker dispatch 路径一致。
7. 测试基线 ~3000 个（`grep -rh "def test_" tests/ | wc -l` 取实时计数）、覆盖率门 80%（全量跑）；PyInstaller re-exec 约束不变。

## 13. 实施路线（P0-P6，每阶段独立可交付、基线不破）

> **✅ 全部阶段已完成（2026-06-12）。** 以下表格保留为历史参考记录。

| 阶段 | 交付 | 验收 |
|---|---|---|
| **P0 协议层** | `protocol/` 包成立：events 物理搬家 + shim、EventEnvelope、黄金 JSON 快照测试 | 全量测试绿；行为零变更；52 文件 import 不破 |
| **P1 内核通电** | RunWorker 接进 create_run；plan_mode/permissions/MCP/browser 去全局；`_DEFAULT_CTX` 修复；workspace per-session 注入 | `POST /runs` 真跑 run 出事件流;两个 run 并发不串台 |
| **P2 能力注册表** | `capability/` 包：manifest + registry + 适配现有全部能力；broker dispatch 化；LSP risk bug 修复 | "加能力只注册 manifest 不改四处"硬回归测试;工具数来自 registry |
| **P3 跨进程审批 + 账本 + TUI 客户端化** | ApprovalGate pending registry + ACP 路由；PlanDecisionRequest；Ledger v1（人话条目+undo 三态）；TUI 默认走 daemon 协议（inline loop 留 fallback） | TUI 隔协议批准一个真审批;Ledger 可回放;undo 真还原 |
| **P4 人话层 + 信任拨盘 + 验证策略** | intent/ NL→Goal+确认回路；Event plain/technical；Trust Dial L0-L4；Verify Strategy Generator（梯子 L2/L3 + 诚实退路） | 非开发者跑通一个非代码任务全程人话;无策略任务诚实 unverifiable+留痕 |
| **P5 自治面** | conductor/：Scheduler/Triggers/Standing Orders；自治 run 默认 worktree；优先级调度 | 定时任务夜跑隔离树,验证过才合并;HARD RULES 自治下不放行 |
| **P6 Computer use + 桌面端通道** | perception/ 浏览器级 computer-use + OS 级探索；非开发者域 HARD RULES；桌面壳脚手架 | computer 动作四线管辖;VLM 低置信度降 unverifiable;桌面壳连上 argosd 收到事件流 |

依赖链：P0 → P1 → P2 → P3 → (P4, P5 可并行) → P6。
每阶段完成即提交；测试基线全绿是阶段放行条件。

## 14. 已知风险（诚实标注）

- **Verify Strategy Generator 是 v6 最不确定的赌注**：生不出可靠机检命令时大量任务退化
  unverifiable。退路已设计（L5 留痕 + 人话请过目），但体验上"Argos 老说不确定"的风险真实存在。
- 跨进程审批引入分布式状态（客户端断连时 pending 悬挂）—— 需要超时 + 默认拒绝兜底。
- daemon-first 牺牲"单进程跑起来"的简单性 —— inline fallback 保留到桌面端阶段再评估。
- 自治放大一切漏洞的爆炸半径 —— worktree 默认隔离 + HARD RULES + 低默认档是三道闸。
