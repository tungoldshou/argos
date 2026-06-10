# Argos TUI v2 重设计(定稿)

> 2026-06-10。用户拍板的方向(同日下午会话):经典两栏 + 智能底栏、暖橙 Tokyo-Night、
> Claude Code 式简洁、行内审批(否决居中 modal)+ 方向键导航 + 音效。细节全权委托。
> 本 spec 取代下午会话未落盘的 Section 1/6 草稿,为完整定稿。

## 0. 设计原则

1. **默认极简,细节按需**:主对话流只留"用户能读懂任务进展"的最小信息;
   运维细节(工具计数/hook/LSP/审批 log)进右栏,且右栏一次只显示当前阶段相关的一个视图。
2. **色彩纪律**:暖橙 `#E0AF68` 是唯一强调色(⏺/边框/标题/光标);绿/红只属于 verdict 与 diff;
   其余一律 muted `#565F89` / 散文白 `#C0CAF5`。诚实三态色相(绿/红/橙)绝不混淆。
3. **不再像"默认 Textual app"**:去掉 stock Header/Footer,自绘 1 行 TopBar;
   键提示并入状态栏右侧。
4. **交互在流内**:审批/计划决策渲染在对话流里(不是居中弹窗),方向键+数字双通道,
   到达时响铃。用户视线不离开对话流。
5. **渲染层重构,数据层稳定**:ActivityPanel/StatusBar/Transcript 的数据入口方法名与语义
   全部保留,只换渲染——把 ~30 个测试文件的翻修面压到 modal/视觉断言一圈。

## 1. 布局(经典两栏 + 智能底栏)

```
╭─ glow 边框(工作态呼吸光,保留) ─────────────────────────────╮
│ ✳ Argos v0.x · MiniMax-M3        [plan] [YOLO] [DEMO|LIVE] │  TopBar(1 行)
│ ┌──────────────────────────────────┬─────────────────────┐ │
│ │ Transcript(1fr)                  │ SmartPanel(32 列)    │ │
│ │  › 用户输入(muted)               │  ── 按阶段智能切 ──   │ │
│ │  散文(Markdown 亮白)             │  idle/plan/act/verify│ │
│ │  ⏺ 扁平代码/工具块               │  …当前视图正文…       │ │
│ │  ▌verify passed · pytest → 12 ok │  ─────────────────   │ │
│ │                                  │  ↑12.4k ↓3.1k $0.013 │ │
│ │                                  │  ctx ▓▓▓░░░░░░░ 34%  │ │
│ └──────────────────────────────────┴─────────────────────┘ │
│ › 输入目标,或 / 开始命令_                                    │  PromptArea(1-8 行)
│ ◇ plan · ⚙3 · ↑12.4k ↓3.1k · $0.013 · 4.2s    Esc打断 ^C退出│  StatusBar(1 行)
╰─────────────────────────────────────────────────────────────╯
```

- **去掉** `textual.widgets.Header` 与 `Footer`。TabStrip(daemon 多 run)保留在 TopBar 下,
  非 daemon 模式隐藏(现状)。
- 窄屏 `<90` 列:SmartPanel 折叠(沿用 HORIZONTAL_BREAKPOINTS)。
- glow 呼吸边框、三态终态锁色逻辑不动(签名特性)。

### 1.1 TopBar(新 widget `widgets/top_bar.py`)

单行 Static:左 `✳ Argos v{version} · {model}`(✳ 橙色);右侧徽标按需:
`[plan mode]`(靛蓝)、`⏻ YOLO`(橙)、`DEMO 脚本演示`(黄,诚实标识不可省)、
`⚠ 未配 key`(黄)。替代 sub_title 机制——`_compose_subtitle()` 改为驱动 TopBar。

## 2. 配色(theme.py 微调,不换色板)

argos-night 色板保持(用户已拍板暖橙 Tokyo-Night)。仅:

- 新增变量 `block-cursor-foreground/background` 对齐输入光标为橙;
- `boost` 留默认;不引入新色相。

## 3. Transcript 扁平化(Claude Code 式)

### 3.1 CodeActionBlock → 扁平块(无边框)

```
⏺ python · step 3                       ← 橙 ⏺ + muted 标签
  <syntax 高亮代码,2 空格缩进>            ← >8 行折叠为头 6 行 + "… +N 行"
  ⎿ ✓ 12 passed (0.8s)                  ← ✓ muted / ✗ 红;>12 行折叠保持现状
```

去掉 `border: round` 盒子与 border_title;Syntax 主题保持 monokai。
折叠规则:代码超过 8 行只显示前 6 行 + `… +N 行`(完整代码在 run 存档里,TUI 不可点)。

### 3.2 VerdictBadge → 扁平行(保留三态铁律)

```
▌ verify passed · pytest -x → 12 passed          (绿,▌ 粗竖条前缀)
▌ verify FAILED · pytest -x → 2 failed           (红)
▌ 无法验证 · — → verify_cmd 未注册                 (橙)
▌ self-verified(较弱:系统自造测试) · cmd → detail  (黄,E4 防火墙保留)
```

去边框盒;`▌` 用状态色,正文同色。tampered 提示文案保留。
三态色相分明、self-verified 不冒充绿——不变量不动。

### 3.3 StartupSplash 紧凑化

ASCII logo 保留(品牌),其下压缩为两行:
`终端超级智能体 · v{version} · {model} · {✳ LIVE|⚠ DEMO|⚠ 未配 key}`
`输入目标开始 · / 命令 · Esc 打断 · ^C 退出`
坏配置 banner(hooks/lsp/permissions 已禁用)保留一行式。plan mode 前缀/切色保留。

### 3.4 ThinkingIndicator

braille spinner(⠋⠙⠹…)+ 标签 + 实时秒数:`⠹ 执行中… 4s`。橙色。

### 3.5 不变

UserMessage(`› ` muted)、AssistantMessage(Markdown)、SystemLine 着色、
回合间 Rule 虚线、_stick_to_bottom 智能跟随、markup=False 防崩约定——全部保留。

## 4. 行内审批 InlineChoice(交互核心,替代 3 个 ModalScreen)

新 widget `widgets/inline_choice.py`,挂进 Transcript 流内(mount_block):

```
▌ ⚠ 审批请求 [medium] — [soft rule: ask git push]      ← 风险色竖条 + 标题
│ git push origin main
│ 动作: run_command · 参数: {...}
│ ▸ 1. 本次允许                                        ← ▸ 光标行(橙)
│   2. 本会话允许
│   3. 总是允许
│   4. 拒绝
│ ↑↓ 选择 · ↵ 确认 · 数字直选 · Esc 拒绝
```

- **键路**:↑/↓ 移动 ▸;Enter 确认;`1-4` 直选;Esc=安全默认(deny/保持挂起语义按场景)。
- **音效**:mount 时 `app.bell()`(终端铃,用户明确要求的提示音)。
- **焦点**:挂起时 InlineChoice 夺焦(can_focus=True);决策后自毁为一行结果
  `审批:run_command → once`(muted),焦点还给 PromptArea(输入草稿不丢)。
- **队列**:app 持 FIFO;同屏最多一个活动 InlineChoice,前一个决策后再 mount 下一个。
- **三个场景复用同一 widget**:
  1. **工具审批**(原 ApprovalModal):选项 once/session/always/deny,顺序如上
     (把"拒绝"放第 4 位,数字键语义改为 1=once——旧 modal 是 1=deny;
     新排序对齐 Claude Code"默认安全向前走",Esc 仍是 deny 逃生口)。
     secret 命中副标题保留。回调 `gate.respond(call_id, decision)` 不变。
  2. **计划决策**(原 PlanModal):选项 = approve_start/approve_only/refine/discard;
     选 refine 时就地展开一行反馈输入(Enter 提交,Esc 收起回选项)。
     回调 ExitPlanMode 原子语义不变(校验失败不 set event)。
  3. **工作流审批**(原 WorkflowApprovalModal):preview 正文 + approve/deny 两项。
- AUTO(YOLO)档行为不变:不渲染,直接放行。
- 删除文件:`approval_modal.py`、`plan_modal.py`、`workflow_approval_modal.py`。

## 5. SmartPanel(右栏智能切,重写 activity_panel.py)

类名/文件名保留 `ActivityPanel`(压测试翻修面),内部改为**视图模型**:

- **数据入口全部保留**(签名不变):`on_phase/on_plan/on_receipt/on_cost/on_context/
  on_hook_fired/on_lsp_server_event/on_lsp_diagnostic_event/on_approval_decision/
  on_run_summary/reset_run/snapshot_text` + skill run 入口。
- **渲染改为 4 视图,按阶段自动切换**(用户拍板"智能切"):
  | 视图 | 触发 | 内容 |
  |---|---|---|
  | idle | 启动/run 结束 | 模型+档位、key/live 态、Run 概览、Skill/MCP 计数、上轮 verdict |
  | plan | phase∈{plan} | TODO 清单(有)或 4 阶段计时(无) |
  | act | phase∈{act} | 进行中 TODO 项、工具计数、最近 5 回执、审批计数+最近 3 条、hook/LSP **仅异常**行 |
  | verify | phase∈{verify,report} | verdict 现况、verify_cmd、4 阶段耗时表、本轮审批汇总 |
- **常驻 footer**(所有视图):`↑in ↓out [tier] $cost` + `ctx ▓▓░ N% [used/window]`
  (cost/context 任何时刻可见——钱与上下文是用户始终关心的两件事)。
- **手动 pin**:`Ctrl+O` 循环 auto→plan→act→verify→idle→auto;视图标题行显示
  `── act ──`(auto)/`── act ⚲ ──`(pinned)。
- 诚实空态保留:每块无真实数据显"(无)/未配置",绝不预填。
- `snapshot_text()` 聚合**全部视图**的数据文本(不只当前视图)——/cost 回显与测试断言不受
  视图切换影响。

## 6. 输入区 & 状态栏

### 6.1 SlashMenu 方向键导航

- 输入 `/` 列出命令(现状);**新增**:↑/↓ 在菜单内移动 ▸ 高亮,Tab/Enter 补全**选中项**
  (现在只能补第一项);Esc 收起。PromptArea 在菜单可见时把 ↑/↓/Enter 转发给菜单。
- 多行输入、`\`+回车续行、高度自增 1-8 行——保留。

### 6.2 StatusBar 去噪

```
◇ plan · ⚙3 · ↑12.4k ↓3.1k · $0.013 · 4.2s · ctx 34%        Esc打断 · \↵换行 · ^C退出
```

- 阶段字形随 phase:◇ plan(靛蓝)/ ✦ act(橙)/ ✦ verify(橙)/ ◇ report、idle 灰。
- `ctx N%`:≥80% 红色加粗(替代现在的尾部 ●)。
- **daemon run badges(⏵/⏸/⏹)只在 daemon 模式渲染**——非 daemon 不再显示 `⏵0 / ⏸0 / ⏹0` 噪声。
- 右侧常驻键提示(替代 stock Footer)。
- reactive 字段与 set_* 方法签名不变。

## 7. 迁移与文件清单

| 动作 | 文件 |
|---|---|
| 新增 | `widgets/top_bar.py`、`widgets/inline_choice.py` |
| 重写渲染 | `widgets/activity_panel.py`(视图化)、`widgets/code_action.py`、`widgets/verdict_badge.py`、`widgets/splash.py`(紧凑)、`widgets/thinking.py`(spinner)、`widgets/status_bar.py`(去噪+键提示)、`widgets/prompt.py`(SlashMenu 导航) |
| 改装配 | `app.py`:compose 去 Header/Footer + TopBar;_handle_approval/_handle_plan_rendered/_handle_workflow_proposed 改 InlineChoice + FIFO;PhaseChange 通知 panel 切视图;新绑定 Ctrl+O |
| 删除 | `widgets/approval_modal.py`、`widgets/plan_modal.py`、`widgets/workflow_approval_modal.py` |
| 主题 | `theme.py` 光标变量 |

### 测试策略

- modal 测试(test_tui_approval / test_tui_plan_modal / workflow 审批相关)改写为
  InlineChoice 行为测试:↑↓+Enter、数字直选、Esc、bell 调用、gate.respond 回传、FIFO。
- ActivityPanel 测试:数据入口断言不动;视图切换新增 test;snapshot_text 聚合语义保留。
- StatusBar/Splash/CodeActionBlock/VerdictBadge 测试:更新渲染断言(三态/self-verified/
  tampered 不变量必须仍有测试钉死)。
- 新增:test_top_bar、test_inline_choice、test_smart_panel_views。
- 全量 `uv run pytest` 通过(coverage 门 80% 以全量为准;当前主干本身有 11 个既有失败 +
  78.68% 覆盖,与本次无关,以"不新增失败、TUI 子集全绿"为本次验收口径,并尽量顺手提升)。

### 不在本次范围

- 事件契约(`events.py`)、loop/broker/gate 的任何行为语义;
- daemon 协议、TabStrip 交互(沿用);
- 诚实不变量的任何放松(DEMO 标识、三态、self-verified、空态)——只许变好看,不许变诚实。
