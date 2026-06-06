# Changelog

All notable changes to Argos are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Skills 3-pack:on-demand 自检原语(`/verify` / `/security-review` / `/simplify`)。** 用户中途一键复跑 verify、提交前扫 secrets + dep 漏洞 + 危险 API、重构前看重复 / 复杂度 / 死代码。架构:`skills_runtime/` 模块(skill registry 单例 + `run_skill()` 编排 + 2 个 TUI event 接入);`builtin/` 子模块分离数据契约与具体 skill 实现;slash command 走 TUI `_dispatch_slash` + `_skill_cmd` 统一入口(同 `/lsp` 模式)。**3 个 skill**:`/verify` 薄包装 `Verifier.verify`(**D9/D13 关键 — 显式走 verify 入口不绕 `propose_verify`**,诚实:无 `verify_cmd` 配置 → verdict=n_a 引导用户配);`/security-review` 3-pass 编排(secrets 9 regex 含 `sk-ant-` 新增 + dep audit shell out 缺工具必报 error severity **D5 防假绿** + permission Python/JS-TS 危险 API)+ dedup + sort;`/simplify` 3-pass(token shingle 重复 + 复杂度 + 死代码启发)+ top-N 截断。**3 个 SKILL.md** 配方 + 3 skill 注册到 `~/.argos/skills_builtin/` 供 LLM 召回。TUI 活动栏 "Skill Catalog" / "Skill"(重排,避撞既有 `Skill` 标识)。`+110+ 测试`(3 pass 独立 + 3 整合 + 边界 + Pilot e2e);`COMMAND_HELP` 15→18;不引入新外部依赖;**不做(v1.1)**:`/lsp` 类子命令(`/security-review src/` 路径限定本期 v1 实装)、Web 仪表盘。**安全警示**:Pass 2 需用户自装 `pip-audit` / `npm` / `cargo-audit`(同 hooks spec D11 用户责任);`.env` / `.env.*` / `secrets.toml` / `*.pem` / `*.key` 跳过不扫(D4 user-controlled 秘密存储);测试代码 `eval` / `exec` 降级 info(避免误报)。

### Fixed
- **CHANGELOG/CLAUDE:slash 数从 15 同步到 18,补 skills 段。** 文档维护(spec §2.6)。

- **LSP 工具(语言服务器集成)—— 6 个真结构化代码情报原语。** `lsp_definition` / `lsp_references` / `lsp_hover` / `lsp_document_symbols` / `lsp_workspace_symbols` / `lsp_diagnostics`,给 agent 在中大型项目里替代 grep + 全文读;配置独立 `~/.argos/lsp.json`(built-in 默认启 pyright,用户没装不偷偷启动),坏配 → 全禁用 + splash banner;沙箱内 `tools/files.py` 一行不动,didChange 触发点**唯一**在 host loop 解析 code 块。LSP server 跑在 Seatbelt **外**(同 hooks),文档显式警示"第三方 LSP server = host 侧任意代码执行 vector"。+30 测试(含 slow 标记的真 pyright e2e)。工具数 15 → 21。**不做(v1.1)**:lsp_completion / codeAction / rename / formatting / live diagnostics gutter;`/lsp restart` 子命令;项目级 `.argos/lsp.json`。
- **Hooks 系统(对齐 Claude Code `~/.claude/hooks.json` 模型)。** 用户可在 5 个生命周期点挂任意 shell 脚本:PreToolUse / PostToolUse / Stop / UserPromptSubmit / SessionStart;配置文件独立 `~/.argos/hooks.json`(不与 config.json 混)。PreToolUse 返非 0 阻塞 sandbox 工具调用 + 反喂回模型(同 propose_verify 拒路径);PostToolUse / Stop 仅警告不卡 run;PreToolUse 超时**非阻塞**(诚实:超时 ≠ 拒,spec D4)。TUI `/hooks` 列出当前配置 + `/hooks reload` 实时重载;activity panel "Hook" 区段显 3 态(ok/fail/timeout);启动 splash 坏配置 banner。Hook 不进 Seatbelt(用户代码,同 CC);文档显式警示"hook = 用户脚本,与 agent 同权限"。+35~40 测试。**不做(v1.1)**:Notification / PreCompact / SessionEnd 事件;prompt / agent 类型 handler;项目级 `.argos/hooks.json`;hook 市场 / 签名 / dry-run / 重放。
- **Plan mode + `/plan` 命令(对齐 Claude Code user-facing Plan 切换)。** 用户可切到"只看 plan 不动手"模式:agent 进入 plan-only,host 拼 markdown plan 文档(任务分解/涉及文件/风险/审批 4 段),弹 `PlanModal` 4 选项审批(approve and start / approve and accept edits / keep planning / refine with feedback,数字键 1/2/3/4 绑定)。TUI 标题 `[plan mode]` 前缀 + 边缘光变色 + splash 标题前缀 + status_bar Mode 段。`EnterPlanMode` / `ExitPlanMode` 工具注册(15→17)。plan mode 期间沙箱工具(`write_file` / `edit_file` / `run_command` 等)被 dispatcher 拦截,返错误串,不进沙箱(spec §2.4)。`keep_planning` 把 loop 拉回 plan 阶段;`refine` 把 feedback 作 user message 注入。+24 测试(plan_mode 16 + render 5 + dispatcher 7 + tui_modal 4 + loop_plan_mode 3 / 部分有重叠)。不做(本期):Plan subagent / 浏览器 Ultraplan / 持久化 plan — v1.1。
- **打包 B 阶段:对齐 Claude Code native binary 安装体验。** ① `curl -fsSL https://raw.githubusercontent.com/tungoldshou/argos/main/packaging/install.sh | bash` 一行装到 `/Applications/Argos.app`(macOS arm64 only,SHA256 校验,友好错误);② Homebrew Cask formula(`brew install --cask -s packaging/homebrew/argos.rb`,本地路径,`#12` 阶段建 tap 仓);③ GitHub Actions release workflow(打 `v*` tag → macos-14 runner build + 上传 `Argos-<ver>-arm64-mac.tar.gz` + SHA256SUMS + 创建 release);④ `argos --version` flag(走 `importlib.metadata` 单源);⑤ `argos self-update` 子命令(启动时 7 天缓存 background check GitHub latest,发现新版**仅提示不下载**,用户主动跑升级)。packaging/VERSION 单源。+19 测试(version 2 + self_update 9 + self_update_cmd 3 + install_script 5 + release_workflow 4 / 部分依赖现有)。
- **Dynamic Workflows —— 确定性 fan-out 编排(对标 Claude Code,模型无关)。** Argos 现在能把可拆解的大任务**确定性地**派给多个子 agent 并行干、逐阶段验证、汇总回灌。底料是**声明式规格 + host 确定性引擎**(非让模型写编排代码——便宜模型可靠产 JSON 远胜于写对 orchestration 代码,正合"让便宜模型可靠"的灵魂):agent 在 CodeAct 里调 `propose_workflow({name, description, stages})`,host 在**异步态**(主循环空闲、非 exec_code 内)括号配平+`ast.literal_eval` 抽出规格 → 弹审批预览(`await gate.request`,异步态不死锁)→ `WorkflowEngine` 异步跑五形态。**破死锁核心**:`propose_workflow` 是"提议"而非"执行"(对齐已验证的 `propose_verify`)——agent 只提议、瞬间返回不阻塞,loop 在异步态审批+跑引擎,故审批不死锁、子 agent 事件实时进 TUI、Esc 可中断。**五形态**:`fan_out`(每项一 agent 并行)/`pipeline`(每项串过多阶段、阶段间无 barrier)/`panel`(N 票表决,对抗式 verify 通用化)/`loop_until`(累计到目标 or 连续空轮停,硬轮数上限防失控)/`synthesize`(汇总)。**模型无关**:每个子 agent 可指定任意 config profile —— 一堆便宜 worker 并行 + 某阶段用强模型当裁判。**子 agent 完整能力**:写文件+跑命令+各自 verify 门,独立 ModelClient/broker/Seatbelt 沙箱,AUTO 档(启动审批已覆盖意图),Seatbelt+egress 硬边界不变。**隔离**:`isolation: worktree` 给并行写 agent 独立 git worktree,改动**拆 worktree 前抓成 diff 回结果**(v1 不自动合并,供你审阅应用);`isolation: none` 写共享工作区直接落地;非 git 工作区诚实退共享+提示。**深度恒 1**(`allow_workflow` 贯穿 tools→executor→沙箱子进程→loop,子 agent 命名空间不含 propose_workflow,防递归爆炸)。**诚实降级**:规格非法/被拒/无引擎都诚实回灌不崩;子 agent 失败带其余结果继续(notes 如实记);cap 截断/worktree 退化/部分失败全经 notes 报,不静默。工具数 15→16。新增 `argos_agent/workflow/`(spec/result/worktree/subagent/engine)+ `WorkflowProposed/Progress/Done` 事件 + TUI 审批模态/进度树。约 50+ 新测试(spec 校验/五形态/隔离 RAII/深度护栏/loop 集成/取消/TUI/端到端铁证),全程真 Seatbelt 沙箱、ScriptedModel 离线确定性。
- **多行输入框 + slash 命令菜单 + Esc 打断(对齐 Claude Code 的输入交互)。** 真终端反馈四连改:
  ① **多行输入** —— 单行 `Input` 换成 `PromptArea`(基于 `TextArea`):Enter 提交整段;**行尾反斜杠 `\` + 回车 = 续行**(去掉反斜杠插入真换行、继续编辑,readline/shell 同款),多行粘贴原样进入,高度随行数自增长(1..8 行)。**为什么用反斜杠而非 Shift+Enter**:本项目禁用了 Kitty 协议(修过"打字不显示"的输入 bug),不能赌修饰键能被终端识别;反斜杠续行终端无关、确定可用。
  ② **slash 菜单** —— 打 `/` 即在输入框上方弹出命令列表(命令 + 中文说明,▸ 标首项),继续输入收窄,**Tab 补全**到首个匹配(`/he`→`/help `),Enter 跑完整命令;命令清单单一来源 `COMMAND_HELP`(/help 文案、菜单、补全不漂移)。
  ③ **Esc 打断当前任务** —— 取消正在跑的 run(模型推理/网络等 await 点即时停;**诚实**:卡在同步 `exec_code`(命令/浏览器占住事件循环)需等其返回,不假装能瞬杀同步子进程),收尾落明确的"⎋ 已打断"行;Esc 双用——slash 菜单开着时先收菜单(不打断);idle 时无副作用。
- **系统提示注入运行环境块(cwd/OS/日期),对齐 Claude Code 的 environment 段。** 此前系统提示零环境上下文,模型为了回答"在哪个目录"之类的事实只能现场跑 `os.getcwd()`/`pwd`(实测:一句"你在什么目录"烧了 3 个代码动作 + 近 200 秒,还撞 import 白名单吐 traceback)。现在 `_build_system` 在**可信安全段**(HONESTY 之后、untrusted 围栏之前)前置注入工作目录、操作系统、当前日期,并明示"以上为已知事实,无需用代码现场探测"。根治整类"用代码探环境"的无谓动作。+1 测试(断言环境块在安全段、含真实 workspace 路径、不进 untrusted 围栏)。
- **Anthropic 协议开启 prompt caching(此前缓存恒 0 命中,白付全价)。** `AnthropicProtocol.payload` 此前把 `system` 当普通字符串发,**从不打 `cache_control` 断点** → Anthropic 端永远不缓存,可 UI 又在读缓存统计(恒显"缓存命中 0 tok")。现在 system 作带 `cache_control: ephemeral` 的内容块发送。**为什么是最大省钱点**:系统提示(HONESTY + 工具文档 + 工作流契约,数 KB)是最稳、且**每个 CodeAct 步都原样重发**的前缀——一次多步 run(截图那种潜在 40 步)从第二步起即命中,直接砍掉重复的输入计费。**协议差异(诚实)**:OpenAI 兼容端(OpenRouter/DeepSeek/Ollama/vLLM)是**服务端自动缓存、不认此字段**,故 `OpenAIProtocol` 不打标记、保持 system 为纯消息;低于端点最小可缓存长度时 Anthropic 静默忽略(无害),不支持的兼容代理至多忽略该字段。+1 测试(Anthropic system 为带 ephemeral cache_control 的内容块、原文保留;OpenAI 路径锁死无标记)。
  +9 个测试(match_commands 前缀/参数门、Enter 提交清空、反斜杠续行、菜单显隐、Tab 补全、Esc 打断活跃 run + idle 无副作用 + 先收菜单)。作用域诚实:Pilot headless 测的是 handler 逻辑,真终端转义解码仍由进程级 Kitty 断言守。

### Changed
- **头部/启动画面标题去"诚实可靠的编码智能体",改"终端超级智能体"。** Argos 不只是编码 agent,而是 Claude Code + agent 的超级智能体;诚实仍是内核(HONESTY_SYSTEM/verify 门不变),但不必挂在标题上自我标榜。
- **右侧活动栏分格(此前各区块挤成一坨)。** `_Section` 之间的分隔线原用近黑 `$panel` 几乎不可见、且零间距 → 用户体感"全挤一起、看不出格子"。改:每块顶部 `$foreground-darken-3` 灰色分隔线 + 嵌在线上的**橙色粗体标题** + 块间留 1 行空白,渲染成清晰的"格子"。(注:`$text-muted` 是自定义主题变量,在 DEFAULT_CSS 的 border 解析期不可用,故分隔线用内置派生色 `$foreground-darken-3`。)另:活动栏"任务进度"区在没有真 TODO 拆解时显示的是 4 个工作阶段(plan/act/verify/report),**不是被限制成 4 条**;agent 调 `update_plan` 后会渲染全部子任务(不截断)。
- **浏览器默认改为【有头/可见】窗口(计算机控制本该让你看着它做)。** 此前 `BrowserController` 默认 `headless=True`,agent 调浏览器时不弹窗,用户会以为"根本没打开浏览器"(实测反馈)。现在默认开**可见 Chromium 窗口**,你能亲眼看着 agent 导航/点按/填表;无显示器/CI/SSH 环境可设 `ARGOS_BROWSER_HEADLESS=1` 强制无头。另加 `--disable-blink-features=AutomationControlled` 去掉 `navigator.webdriver` 自动化指纹,让真实站点(尤其 Google)少一点直接弹反机器人验证 —— **诚实**:不保证绕过 CAPTCHA,大站仍可能挑战自动化,命中时 agent 会如实换路(web_search,实测就是这么干的)。

### Fixed
- **改了代码却不声明验证可直接"完成" → 验证门形同虚设(H2 护城河洞)。** 弱模型只要从不调 `propose_verify`,就一路走"诚实非阻塞完成"标"未机检验证"收尾——门**从不强制**它验证。诚实但宽松:偷懒模型可全程跳过验证纪律,正面打脸"让便宜模型可靠"。修:act 循环 host 侧解析代码块,记录本轮是否真发生写操作(`write_file(`/`edit_file(`);宣布完成时若**改了代码却没声明有效验证命令** → 回灌**一次**催促它用 `propose_verify` 声明真验证(pytest/cargo test/ruff/mypy/tsc)。**只催一轮**(`verify_nudged` 兜底):仍不声明则照常走"未机检验证"诚实收尾,不无限催;**纯读/问答任务(无写操作)不触发**,避免误催。+2 测试(改代码无验证 → 催促恰回灌一次;纯读任务不催)。
- **`propose_verify` 接受永远通过的伪命令 → 假绿(H1 护城河洞)。** 弱模型可声明 `propose_verify('echo ok')`:`echo` 在白名单、退出码 0,verify 门据此返 `passed` 谎报"已验证通过"——一行绕过整个护城河。修:`_on_propose_verify` 拒登记 `_TRIVIAL_VERIFY_BINS`(echo/true/false/`:`/ls/pwd/cat/printf/head/tail/yes/whoami/date/env/sleep/test/`[`/dirname/basename 等永远通过、什么都不验证的命令),并回灌一次反馈让模型改用真正能判定对错的命令(pytest/cargo test/ruff/mypy/tsc)。伪命令不登记 → 落回"未机检验证"诚实路径,**不产生假绿**。**连带堵死 M1**:既然伪命令被拒,就无法用 `propose_verify('echo ok')` 覆盖掉先前声明的真命令(此前 `finditer` 取最后一个 → 可先真后假覆盖)。+2 测试(单元:echo/true/ls/pwd/cat/`:`/printf 不登记、pytest 照常登记;端到端回归:声明 echo ok 的 run 落 unverifiable 而非 passed)。
- **篡改检测在 project_mode 下是死代码 → 偷改测试可骗过 verify 门(头号护城河洞)。** verify 门的"篡改优先"判据(`Verifier.verify` 见 `detect_tampering()` 非空即判 `unverifiable`)是"防贿赂测谎仪"的核心,但它读的 `ctx.guarded` 要靠 `guard_files()` 先登记——而全仓 `guard_files()` **生产路径零调用**(只有测试在调,`runtime.py` 注释里说的 "server run 路径" caller 根本不存在)。后果:真实 run 里 `detect_tampering()` 永远返 `[]`,篡改分支**永不触发**;project_mode 下 `verify_dir==workspace`,agent 能直接改 verify 要跑的测试让它过、无人察觉,"防作弊"接线了没通电。修:新增 `runtime.guard_project_tests()`,`AgentLoop.run` 在 **project_mode 起 run 时(agent 动手前)** 自动快照工作区里【既有】的单个测试文件指纹(`test_*.py`/`*_test.py`/`*.spec.ts`/`*_test.go` 等,剪枝 `node_modules`/`.venv` 等重目录,cap 2000)。**语义**:改/删既有测试 → 判篡改 → verify 判 `unverifiable`(诚实标"无法独立验证、需人工复核",非硬失败);**写新测试不算篡改**(TDD 合法,诚实协议自己鼓励先写测试);改源码不算。快照早于任何 agent 动作 → 同时堵死"先改弱测试再 `propose_verify` 声明"那条绕过。沙箱模式靠 VERIFY_DIR 隔离,`guard_project_tests` 自返 0 不参与。+3 测试(既有测试快照只守单文件/重目录剪枝/新测试豁免 + 沙箱模式 no-op + loop 端到端接线:project_mode run 后改既有测试被 `detect_tampering` 抓)。
- **Anthropic prompt caching 此前从未启用(缓存恒 0 命中)。** 见上方 Added 段同名条目——`cache_control` 缺失导致 system 每步全价重发。
- **沙箱写非默认 workspace 被 Seatbelt 静默挡(潜伏 bug,工作流 e2e 暴露)。** `SeatbeltExecutor.spawn` 没给子进程注入 `ARGOS_WORKSPACE`,且 `seatbelt.spawn_child` 算了 `child_env` 却没传给 `Popen`(死代码)→ 子进程 `write_file` 牢笼按继承的默认 env 解析,写到非默认 workspace(子 agent worktree / `--project`)被 Seatbelt 拒成 `Operation not permitted`,但 loop 仍记 step done → **假绿**。此前仅因 `in_project` 测试 fixture 全局设了 env 才掩盖。修:executor 每次 spawn 给子进程 env 注入对的 `ARGOS_WORKSPACE`,seatbelt 把 `child_env` 真正 `env=` 进 Popen。
- **任意工具/模型文本含 `[...]` 时 TUI 直接崩(Rich markup 注入)。** 真终端实测:让 agent 用浏览器搜索,工具返回 `已点击 "input[value='Google Search']"`,其中 `[value='...']` / `[返回值]` 被 Textual 当**控制台 markup 标签**解析 → `MarkupError: Expected markup value` → 崩掉整个 TUI(worker 未捕获)。这不止浏览器:**任何含方括号的输出**(列表 `[1,2,3]`、类型注解 `list[str]`、正则、pytest 参数化用例名、用户输入)都会炸。根因:`UserMessage`/`SystemLine`/`CodeActionBlock` 结果区/活动栏 `_Section`/`VerdictBadge`/`StatusBar` 都是 `Static`,默认 `markup=True`。修:全部 `markup=False`(任意文本按纯文本渲染,`update()` 沿用 `_render_markup` 设置)。+3 回归测试(复现真崩溃路径:CodeResult.value_repr 含方括号经 `_apply_event`→`set_result` 渲染不崩 + 用户输入/系统行含方括号不崩 + 构造期 `_render_markup is False`)。

### Added
- **能力可见命令:`/help` `/tools` `/skills` `/mcp`(Claude Code 式可发现性)。** 新增超能力(浏览器/MCP/skills/契约)后,用户得能看见手上有什么。`/tools` 按组列全部 15 个工具(诚实:数量 = `ALL_TOOL_NAMES` 实长);`/skills` 列内置/导入技能库(说明"按任务自动召回");`/mcp` 列 `~/.argos/mcp.json` 已连接的 MCP 工具(未配置时诚实报"未配置 MCP",不谎报);`/help` 一行列出所有命令。+6 测试(解析 known + 经真 App/Pilot 分发断言 transcript 出现真实能力信息)。
- **原生 MCP 接入(stdio,无 langchain)—— Claude Code 招牌的可扩展性。** Argos 现在能连用户 `~/.argos/mcp.json` 里配置的 MCP server,把它们的工具暴露给 agent(经 `mcp_call(server, tool, arguments)`,工具数 14→15)。**为什么自己写**:旧 `mcp_client.py`(随死栈删)绑死 langchain-mcp-adapters,而活引擎 framework-free;MCP 的 stdio 传输就是按行分隔的 JSON-RPC(不是 LSP 的 Content-Length 框),同步实现很轻、且天然契合同步的 broker `_execute`(无 async-from-sync 难题)。**握手**:initialize → notifications/initialized → tools/list → tools/call,全同步行帧。**诚实**:① 默认**零预配** —— 没有 mcp.json/没有 server → 系统提示不注入任何 MCP 段、`mcp_call` 诚实报"未配置";② 单个 server 连接/握手失败 → 标记不可用、其余照常,绝不崩;③ 畸形 config 退空(等于零 MCP);④ 调用包真错误返回可读串,不假装成功。**不阻塞**:`McpManager.start_warming()` 在 `build_components` 起后台线程预热连接(npx server 启动慢也不卡 TUI/首轮响应),`tools_summary()` 非阻塞只读已就绪工具,`AppComponents.close()`+`atexit` 收掉 server 子进程。活动栏 MCP 区诚实显配置态('未配置'/'N 个已配置',不谎报连接数)。+9 个测试,**含跑真 stdio echo server 子进程的端到端往返**(initialize/tools/list/tools/call 真协议,非 mock)。

### Fixed
- **`--project` 模式 workspace 分叉(run_command 与 write_file 落不同目录)。** 真 `--project` 路径下:`write_file` 在沙箱子进程里写到项目目录(spawn workspace),但 `broker._execute` 调 `shell.run_command` 时**没传 workspace** → 回退到 import 期冻结的默认 `~/.argos/workspace`,导致 agent 写完文件、`run_command("python app.py")` 却在另一个目录跑、读不到刚写的文件(此前 changelog 标记的"已知遗留")。修:`CapabilityBroker` 增 `workspace` 字段,`build_components` 把 `ws` 传进去,`_execute` 的 run_command 用 broker 的 ws —— 与沙箱子进程同一个,彻底消除分叉(不依赖 host 是否进 runtime project 模式)。不传 workspace 时维持旧行为(回退 `shell._ws()`)。+2 回归测试(workspace 透传 / 缺省 None 向后兼容)。

### Added
- **计算机控制(浏览器自动化)—— 超越"编码+检索"的第一个超能力。** Argos 现在能真的开浏览器、导航、读渲染后页面、点按、填表、截图(`browser_navigate` / `browser_snapshot` / `browser_click` / `browser_type` / `browser_screenshot`,共 5 个 broker-gated 工具,工具数 9→14)。**关键工程**:Playwright 的 sync API 不能跑在 asyncio 事件循环线程里,而 broker `_execute` 恰恰跑在 loop 线程上(`exec_code` 同步阻塞 loop)——解法是 `browser.py` 的 `BrowserController` 起一条**守护线程**独占 sync Playwright + 持久 page,`_execute` 只投命令队列、阻塞取结果,真正的 Playwright 调用发生在 loop 线程之外。**诚实**:懒启动(第一次真用到才 launch chromium)、没装 chromium → 返回诚实错误串(提示 `playwright install chromium`)而非假装点过、每个动作 try/except 失败返回可读错误让模型换路、`atexit`+`AppComponents.close()` 收掉浏览器不残留 chromium。审批:读类(导航/快照/截图)low、写类(点击/填表)medium;不套出网白名单(浏览任意站点是浏览器本职)。提示里明确"纯静态正文优先 web_extract,需点按/填表/看渲染才用浏览器"。+10 个测试(fake page 测 _dispatch 全动作 / 线程化投递取结果 / 启动失败诚实降级 / broker 路由 / 风险表)。
- **Skills 与契约层真正接进活 loop(此前是死代码)。** 两份休眠资产此前都没接到 CodeAct 主循环:`loop.py` 的 `_build_system` 把 `format_untrusted(skill_bodies=[])` 写死成空 → **skill 召回从不进系统提示**;契约层(`contracts.py`,Argos 唯一有实测数据的差异化资产)更是从未被 loop 调用过。现在 `_build_system` 三段接线、顺序锁死(spec §12.1):① **安全段** = `HONESTY_SYSTEM` + 命中时的**结构化任务契约 checklist**(REST API / DB schema / 状态机 / 配置 / 通用;`contracts.contract_for(goal)` 关键词判定,非结构化任务如写作/分析**不注入**——实测契约对开放式任务有害);② **untrusted 围栏段** = 召回的 **skills**(`skills.recall(goal)`,零模型关键词兜底,独立于记忆库)+ 任务记忆。skills/contracts/memory 任一召回失败都诚实降级、不崩 run。新增 4 个 loop 级测试锁死:无 store.recall 时 skill 仍注入、结构化任务注入契约 + `[C1]`、非结构化任务退裸 HONESTY、安全段永在 untrusted 之前。

### Removed
- **砍掉全部死栈(旧 Tauri/Hermes sidecar 残留),让仓库与产品一致。** 打包 binary 早已 `exclude` `langchain/langgraph/fastapi/uvicorn`(活引擎是自建 framework-free CodeAct loop,仅依赖 smolagents 做沙箱执行器),但仓库里仍留着一整座**只经 FastAPI `server.py` 可达的闭岛**(`server`→`orchestrator`→`fanout`→`worker`/`planner`/`reducer`/`run_registry`)外加 `core/_legacy_agent.py`(LangChain `create_agent`)、根 `verify_gate.py`(LangGraph middleware)、`mcp_client.py`(LangChain MCP adapters)、`playwright_tools.py`(LangChain 工具)。这些被 ~30 个测试文件覆盖 = **完成度造假**(绿测覆盖 binary 根本不含的代码),直接违背项目"诚实"灵魂。本次:删 11 个死模块 + 清 `tools/__init__.py` 的 LangChain `ALL_TOOLS` 块 + 清 `core/__init__.py` 的 `_legacy_agent` 懒桥;删/改对应死测试(纯死的整删,测活不变量的如 path-cage/项目模式写/审批跨 loop 唤醒**改写到活 API**重新覆盖);从 `pyproject.toml` 移除 `langchain*`/`langgraph*`/`fastapi`/`uvicorn` 依赖并 `uv lock`/`uv sync`(连带清掉 tiktoken/sse-starlette/uvloop/watchfiles 等传递依赖)。另删早期实验残留:根 `main.py`(hello stub)/`probe.py`/`cost_ab.py`/`cost_decompose.py`、`scripts/swarm-*minimax.py`/`swarm-domain2.py`/`pzero-ab.mjs`、空 `agent_README.md`、`docs/.../hermes-*.md` 研究稿与 Tauri 期 `context-lens-demo-script.md`。验收:全量 `pytest` 454 通过、覆盖率 82.9%(≥80 门)、`argos --selftest` `verdicts=['passed'] → OK`、整包 import 无悬挂引用。**保留(休眠资产非残留)**:`contracts.py`(结构化任务"必检约定"——唯一有实测数据的差异化资产)、`isolation.py`、`skills.py`——均 framework-free,待接进活 loop。

### Changed
- **彻底去除 worker/premium 模型档位(贯彻"模型不绑定、无档位")。** 这套"便宜 worker 默认 + 验证失败升级到 Claude premium"是模型无关化之前的残留(且 `should_fallback` 级联是从不触发的死代码)。collapse 为**平等命名 profiles + 当前 active**:删 `PREMIUM_TIER`/`PREMIUM_KEY`/`--premium`;`WORKER_TIER`→`DEFAULT_TIER`(name `default`,旧 env 回退用,保留 `WORKER_KEYS` 别名);`ModelTierName` 由 `Literal["worker","premium"]` 改为自由 `str`;`build_components` 去 `premium` 参数、加 `model_override`;`argos --premium` → **`argos --model <name>`**(本次启动用指定 profile);TUI 活动栏/启动画面/上下文窗口统一走 `active_tier()`(`_display_tier()` 回退 `DEFAULT_TIER`);自动级联降为纯可选的 escalation profile(未默认启用)。另:去掉 `config.py`/`models.py` 里"默认就是 MiniMax"的误导注释——MiniMax 仅是历史预设之一,不代表绑定。

### Added
- **记忆向量语义召回:复用你配的 provider,不绑定 MiniMax。** 此前记忆召回其实已走 FTS5(`ArgosStore()` 没接 embedder),向量召回是休眠基建。现在改为**复用 active profile 的 provider embeddings**:OpenAI 协议 + 在 `argos setup` 配了 embedding 模型 → `OpenAIEmbedder` 打同一个 `<base_url>/embeddings`(复用同 key);否则(Anthropic 端无 embeddings / 没配 embedding 模型 / 无 key)→ `active_embedder()` 返 None → 记忆**诚实走 FTS5 关键词召回,绝不偷调模型**。`config.json` profile 加可选 `embedding_model` 字段;`argos setup` 在 OpenAI 协议下可选问 embedding 模型(留空=关键词)。注:chat 模型 ≠ embedding 模型,复用的是同 provider 的 embeddings 端点 + 单独的 embedding 模型名。**已知遗留**:`skills.py` 的 skill 召回仍直连 MiniMax `embo-01`(独立子系统,待同样改造)。
- **`/resume` 接成真的:重开窗口后续上上次会话。** 每次启动仍默认全新 session(故重开不自动记得上次);`/resume` 把当前会话切到**最近一次历史会话**,后续任务经 `get_messages` 带回其上下文(agent 记得上次干了啥)。无历史时诚实告知,不假装恢复。
- **`argos setup` provider 菜单支持方向键。** 真终端用 ↑↓ 选 + 回车确认(termios raw 模式 + 反显高亮,`finally` 必复原终端);非 TTY/管道/测试自动回退编号输入(保持 headless 可测,`ARGOS_NO_ARROW_SELECT=1` 可强制回退)。自填项(model/key/url)仍打字。

### Fixed
- **用户反馈四连修(滚动 / 标题 / 成本 / 多轮上下文)。** ① **滚动条滚不动** —— `Transcript` 此前每个流式 token / 系统行都无条件 `scroll_end`,用户向上翻历史被下一个事件即时拽回底部(体感=滚动条失效);改为 **stick-to-bottom**(仅当已停在底部时才跟随,`_stick_to_bottom` 距底 ≤2 行才到底);`ActivityPanel`(右侧活动栏)此前继承 `Vertical` 默认 `overflow-y: hidden`,内容超高被裁死、滚轮/拖拽全无效 → 改 `overflow-y: auto`。② **活动栏区块标题看不清** —— `_Section` 的 `border-title-color` 落到透明默认(`alpha=0`)叠深色背景=隐形;显式设 `$foreground`(亮白)+ bold。③ **成本恒 `$(N/A)`** —— `loop.py` 此前把 `cost_usd` 硬编码 `None` 从不调用已就绪的 `cost_of()`/`PRICING`(真 bug,非诚实无价);改为接入定价表算会话累计成本,**模型不在表里才回退 `None`**(诚实显 `$(N/A)`,而非 `cost_of` 对未知模型返回的失真 `$0.000`);新增 `ARGOS_LLM_PRICE_IN/OUT` 环境变量让自带模型(如 MiniMax-M3)填真实单价即可显成本(不填不编价)。④ **多轮"没串上下文"根因** —— 收尾仅在 `if text.strip():` 时持久化最终 assistant,某轮模型用**空 turn 宣布完成**则该轮只剩单边 `user(goal)`,连续多轮在 DB 堆出连续 `user` → 模型看不出是独立任务、记不住自己做过啥;改为**空答复也落占位 assistant**(`(本轮完成:…)`),保证跨轮 user/assistant 交替。回归:transcript 滚动位置保持 + 在底部跟随、活动栏可滚 + 标题不透明、已知模型算真成本 + 未知模型回退 None、空答复仍持久化 assistant(共 7 个新测试,非恒真式)。
- **屏幕上看不到任何对话(transcript 被压成 1 列宽)。** `ArgosApp` 此前**完全没有 CSS**,`Horizontal(transcript, cost-meter)` 退回 Textual 默认布局:空 `RichLog`(transcript)收缩到 `width=1`、`CostMeter` 撑满整宽并占据左上角 → 所有对话/流式文本/代码块其实都写进了 transcript,只是渲染在 1 列宽里**完全不可见**(几乎所有截图的"空屏"真因,且 Pilot 测试只查 widget 树不查几何故一直漏掉)。修:给 `ArgosApp` 加布局 CSS —— `#transcript { width: 1fr; height: 1fr }` 占满主区,`#cost-meter { width: 34 }` 固定窄栏靠右。实测尺寸从 width=1 → width=86,SVG 导出确认对话文本真渲染出来。回归:`test_transcript_fills_main_area_not_collapsed` 断言 transcript 宽度 ≥40 且 > 成本栏(headless 能量几何,守得住)。另:`models.py` 从 `message_delta` 抓 `input_tokens`(MiniMax 在此才给真值,`message_start` 常为 0),成本栏输入 token 不再恒 0。
- **真模式编码任务恒为 no-op + "回车像没反应"（CodeAct 格式不匹配 + 反馈缺失）。** 真打 MiniMax-M3(实测,非推断)发现:① M3 把工具调用吐成内联 JSON `{"name":"run_command",...}`,而 loop 的 `extract_code_block` 只认 ` ```python ` 围栏 → 首步即被当"已完成" → 0 actions、文件从不创建,且旧提示下 M3 还会**编造**"任务完成✅"+假输出(违诚实协议)。修:`honesty.py` 的 `HONESTY_SYSTEM` 加明确 CodeAct 契约(强制单个 ` ```python ` 围栏 + 例子 + 禁 JSON 工具调用 + 工具函数签名),实测 M3 立刻改吐围栏代码;真 e2e 验证默认 workspace 下 `write_file`+`run_command("python …")` 全链路跑通(exit 0,stdout=`hello from argos`),且 agent 在跑不通时**如实上报**而非假装完成。② 真 loop 从不发 `CostUpdate` → 状态栏 token/成本/墙钟永久 0:`models.py` 抓 SSE usage 帧到 `last_usage`,`loop.py` 每步发 `CostUpdate`(真 token 累计 + 真 elapsed,无单价则 `cost_usd=0` 诚实不编造)。③ 完成只翻 phase + 写进 DB 看不见的备注 → `loop.py` report 段发可见完成行(`✅ 完成。未机检验证` / `验证通过` / 升级提示)。④ 真模式回车到首 token 间无指示 → `app.py` 起手落"⏳ 已收到目标,思考中…"。⑤ `app.py` 一轮结束兜底 flush transcript,杜绝无换行尾段被 `append_token` 缓冲吞掉。回归:`tests/test_loop_codeact.py` 锁死 CodeAct 契约在提示里、loop 必发 CostUpdate(真 token+elapsed)、完成行可见。**已知遗留**:自定义 `--project` workspace 下 `run_command` 在沙箱子进程内解析到默认 `~/.argos/workspace`(与 `write_file` 分叉),致脚本跑不到自定义目录——默认 workspace 不受影响,待修。
- **输入框"打字完全不显示"（真实终端 Kitty 键盘协议）。** Textual 8.2.7（"The more Kitty Release"）默认启用 Kitty 键盘协议;部分终端宣称支持却误解析其转义流,导致可打印键送不到已聚焦的 Input(只负责渲染的 widget 如状态栏/成本计仍正常)——表现为光标在、敲键无字。`argos_agent/tui/__init__.py` 现默认 `TEXTUAL_DISABLE_KITTY_KEY=1`(放包 `__init__`,保证早于任何 textual 导入,因 `constants.DISABLE_KITTY_KEY` 在 import 时定格);`setdefault` 不覆盖显式设置,想 opt-in 回 Kitty 用 `export TEXTUAL_DISABLE_KITTY_KEY=0`。**诚实注记**:此前的 PTY/Pilot 复现"通过"是假绿灯——`run_test()` headless,`pilot.press()` 绕过 driver 真实输入管线,在设计上测不到这类终端层失败;新增 `test_kitty_keyboard_protocol_disabled_by_default`(进程级断言守默认)+ `test_kitty_disable_respects_explicit_user_optin`(尊重 opt-in),并在两个 Pilot 打字测试上标注作用域,杜绝再被当成"用户能打字"的证据。

### Security
- **Phase 3 对抗式安全审查修复（沙箱/broker/engine）。**
  - **C1（Critical）`run_command` 主机外泄洞封死**：曾在 host 侧无约束跑 subprocess（全网络 + 可读写 workspace 外），可被 `python3 -c "...urlopen(...read('~/.ssh/id_rsa'))"` 利用读密钥并外发。现三层防御：① **macOS Seatbelt 关进 executor 同款 profile —— 网络系统级 OFF、写仅 workspace+temp、读放宽**（OS 级真边界,非 arg-inspection）;② `run_command` 风险升 `high` 且在 AUTO（YOLO）档也强制逐个确认,永不静默执行 shell;③ 纵深 arg-inspection 拒 `python/node` 内联求值（`-c/-e/--eval/-` stdin）与 `npx` 任意包执行。遗留 LangChain `run_command` 工具改为委托同一受限实现（消除并存的第二个外泄洞）。**铁证**：`tests/test_run_command_confined.py` 证经 `run_command` 的外联得 `URLError: Operation not permitted`、越界写得 `PermissionError`、in-workspace 命令仍正常。**权衡（MVP 可接受）**：network OFF 下合法联网命令（`pip install` / `git fetch|push` / `npm install`）会被拒——这是安全默认值;"显式批准联网的命令"路径留作后续。
  - **I3 `web_search` 出口现 fail-closed 校验**：曾在 `_NETWORK_ACTIONS` 列出却从不校验;现解析活跃 provider 出口 host（Tavily=`api.tavily.com` / DDGS=`duckduckgo.com`），不在 `EgressPolicy.search_hosts` 即拒。
- **回执/重放正确性**：
  - **I2 per-step 回执**：`CapabilityBroker.take_receipt()`（返回并清空 `last_receipt`），loop 只在【本步新签了回执】时投 `ToolReceipt`，杜绝陈旧回执被每个 code-action 反复重投/张冠李戴。
  - **I4 broker-gating 铁证**：新增经 `broker.request(...)` 端到端 deny 路径测试（OBSERVE 档网络动作被拒、无 receipt，证 egress→approval→receipt 真把动作 gate 住）;`_execute` 加 docstring 红线,标明仅可经 `request()` 调用。
  - **M7 嵌套事件解码**：`deserialize_event` 把持久化的 `ToolReceipt.receipt` / `VerifyVerdict.verdict` dict 还原回 `Receipt`/`Verdict` dataclass（replay §5.8 拿真对象而非 dict）。
  - **M5/M6/M8**：升级措辞用真实尝试次数;`_validate_git` 意图显式化（子命令前全局选项=RCE 向量拒,子命令后局部旗标如 `git show --stat` 放行）;loop spawn 固定空命名空间 + assert 红线,防 model-controlled 数据进 `__authorized_imports__`（smolagents 把 `"*"` 当 allow-all）。

### Added
- **模型无关 + `argos setup` 向导(支持任何模型,不绑定)。** 三层解耦:① **协议适配层**(`core/protocols.py`)—— 抽出 `Protocol` 策略,`AnthropicProtocol`(`/v1/messages`)+ 新增 `OpenAIProtocol`(`/chat/completions`、Bearer、system 作首条消息、`stream_options.include_usage` 抓 usage、`prompt_tokens_details.cached_tokens` 抓缓存),`ModelClient` 按 `tier.protocol` 转交;覆盖云端各家 + OpenRouter + 本地 Ollama/LM Studio/vLLM/DeepSeek。② **声明式配置** —— `~/.argos/config.json`(平等命名 profiles + `active` 指针,**无"档位"**)+ `~/.argos/.env`(密钥明文 **0600**,`api_key_env` 引用,**密钥绝不进 config.json**);**无 config.json 时自动用旧 `ARGOS_LLM_*`/`VITE_*` env 合成单 profile**(现有用户零改动);加载 fail-closed(active 悬空/缺字段/protocol 非法/非正整数/json 畸形 → `ConfigError`);价格 `price_in/out` 可选(无则诚实 `$(N/A)`)。③ **`argos setup` 向导** —— 选 provider 预设(OpenAI/Anthropic/MiniMax/DeepSeek/Ollama/OpenRouter/自定义)→ 填 model/key/url → **连通+CodeAct 格式探针(真发请求,口径对齐真 loop 的 HONESTY_SYSTEM+extract_code_block,诚实评级 行/勉强/不行,如实警告"此模型默认不吐围栏")** → 可选深度 write+verify 探针(默认跳过)→ 自动分流写 .env(0600 原子写,无明文暴露窗口)/config.json;取代旧"无 key→cryptic env"路径。④ **`/model`** 列出 profiles 并切换 active(重启后生效)。**诚实**:无价不编价、密钥明文如实告知、探针真跑不假定、无 key 不假装能跑、UI 上下文%用实际模型窗口当分母。许可证方法论部分借鉴 obra/superpowers(MIT)。
- **agent 改进套件(借鉴 Claude Code)**:① **多轮上下文** —— `store.get_messages(session_id)` 还原对话线程,loop 跨轮全量重发 messages + app 每会话独立 `session_id`,每轮持久化最终 assistant 回答(说"继续"能记得上文);② **真验证门** —— agent `propose_verify(cmd)` 提议验证命令、harness 独立跑真退出码(propose-execute 隔离防作弊),`_actions >= 1` 守卫(没动手不算完成),TDD 诚实提示 + 召回注入顺序安全;③ **上下文用量显示** —— ActivityPanel "上下文" 区进度条 + 百分比(只算输入侧 token,反映当前窗口占用、非会话累计);④ **长上下文压缩** —— loop 接 `should_compress`,**上下文溢出反应式触发**(非数值阈值)`compact_messages` 摘要并重试(死配置 `compaction=True` 接活);⑤ **真 TODO 拆解** —— `update_plan` 工具 + `PlanUpdate` 事件,ActivityPanel 渲染真实 todo;⑥ **UI 诚实** —— 去掉内部"档位/tier"只显真实模型名、成本单价未知显 `$(N/A)` 而非假 `$0.000`、进行中阶段显 `…` 而非 `0.0s`、边缘光呼吸动画(终态告警色锁定不呼吸)。
- **TUI 重设计(方向 A 极简 Claude-Code 风)**:argos-night 暗色主题、Markdown+语法高亮(杀围栏漏出)、user/assistant/系统角色区分、思考 spinner、verdict 三态着色;右侧诚实活动栏(模型/任务进度/工具/已签名回执/成本+缓存命中,Skills·MCP 诚实空态);ARGOS 启动 logo 画面;工作态阶段映射边缘光(颜色=真 phase/verdict,idle 灭,全彩虹为可选 party 模式);Input 描边、回合分隔、窄屏折叠面板。
- **整机集成(Phase 6):** 装配层 `app_factory.py` 把 SQLite store / Seatbelt 沙箱 / capability broker / 模型分档 / Verifier / 自建 CodeAct loop 组装成 TUI 注入的 `loop_factory`(`AgentLoop` 暴露 `bus/store/sandbox/broker` 只读属性);`argos` 入口默认注入真 loop,无 key 时诚实落 demo 态(不假装能跑)。新增 CLI `--selftest`(不连网整机自检,打印 `verdicts=['passed'] → OK`)/`--project`/`--premium`/`--resume`。
- **五条可证伪铁证 e2e(spec §9,`tests/e2e/`):** ① 便宜模型错改被 verify bounce 拦住、修好才翻 `passed`;② kill 中途经 `ArgosStore.replay` 重建、`/resume`(replay+重跑)续上;③ 中文(CJK)经 `recall`/`search` 命中且 reason 可解释;④ 沙箱外泄防线(读 `~/.ssh` 允许但写不出 workspace + 非 allowlist egress fail-closed,macOS Seatbelt);⑤ verify-loop P50/P99 延迟基线 + 超时降级断言。+ 整机贯通 e2e:四阶段不可跳 + 一份事件三用(run==persist==replay 逐事件一致)。用确定性 `ScriptedModelClient`(不连真 LLM,CI 可离线复现);真 LLM 烟测 `probe_real_llm.py`(CI skip)。
- PyInstaller arm64 单 binary 打包(`packaging/argos.spec` + `build_arm64.sh` + `smoke_packaged.py` + smolagents/textual hooks),捆 sqlite-vec dylib,MLX 权重懒下载不进 binary,`console=True`(TUI 需终端)。
- 80% 覆盖门(`--cov-fail-under=80`,实测 84%);打包 hook / 沙箱子进程 / 旧 server 诚实排除(理由在 pyproject)。
- TUI 主屏接线(spec §4):TranscriptLog 流式对话、CodeActionBlock(代码+折叠输出)、DiffView 红绿 diff、VerdictBadge 三态(passed/failed/无法验证)、always-on StatusBar(phase/actions/tokens/cost/elapsed)、侧栏 CostMeter。
- 类型化事件桥 `tui/events.py` 的 `EventBus.close()` 哨兵 + Textual Worker 消费——一份事件三用(UI 渲染 = 持久化 = 重放)的 UI 出口。
- 4 级审批档位拨盘 `ApprovalLevel`(Observe/Propose/Confirm/Auto,`/yolo` 切 Auto);**另**审批弹窗 ApprovalModal 键盘速选 1=deny 2=once 3=session 4=always(DecisionKind,单次请求决定,与档位是两个维度)。Auto 档头部显示 ⏻ YOLO 标记(纯文本标识;终端着色为后续打磨项,当前不声称"亮红")。
- slash 命令 `/yolo /undo /clear /retry /status /model /resume /cost`(`tui/commands.py`)。
- **接线演示态(诚实标注)**:本阶段 UI 出口已就位但**尚未接真 loop**——默认 `argos`(及 `--demo-fail`)均由 FakeLoop/FailingFakeLoop 投脚本化假数据驱动(**非真实执行/验证**),故头部常驻 `DEMO` 标识、每轮起手 banner 声明;真 `AgentLoop` 待 Phase 6 经 `loop_factory` 注入(届时传 `demo=False`,标识消失)。`--demo-fail` 专门演示 escalation/error 诚实上报路径。
- 健壮性:`start_run` 的 `_produce` worker 捕获 loop 任何异常并降级为 `Error` 事件(诚实 ❌ 上报),绝不让未捕获异常击穿 TUI;单会话 busy 守卫防并发两轮 run 串台。
- 5 层 harness（spec §3）：verify 分级延迟（lint+受影响单测内联，integration 超时降级，三态 `Verdict` fail-closed，保留诚实 escalation）。
- 诚实栈：`HONESTY_SYSTEM` 迁入 `core/honesty.py` + untrusted 围栏注入顺序锁死 + 新 `StreamingContextScrubber`（跨 chunk 状态机防围栏标记泄露回 UI）。
- 模型分档：`ModelTier`/`ModelClient`（Anthropic-Messages 兼容端直连，`max_tokens` 按模型可配，替换硬编码 2048）；cascade 升级只由外部判据裁决。
- `CredentialPool`：least_used + exhausted-TTL 复活 + terminal-vs-transient 401 区分；`classify_error`（429/5xx/401/context-overflow → `ClassifiedError` 提示）+ jittered backoff。
- Tool Receipts：HMAC 签名回执（host 侧签，沙箱碰不到 key，agent 伪造不了），harness 接受"我做了 X"前核验。
- 可观测层：`stream_diag`（TTFB/chunks/异常链 4 层拍平）+ per-step cost（usage × pricing 表）。
- **Phase 4 5 层 harness 收口（Tasks 8–10）— 把 harness 智能真正接进引擎循环。**
  - **可观测 L5**（`argos_agent/core/observability.py`）：`stream_diag` 包流式生成器测 TTFB / chunk 数 / 异常链拍平（复用 `recovery.flatten_exception_chain` 挖 4 层真因）；`cost_of(usage, model)` 按 `PRICING` 表算 per-step 成本，**未知模型不瞎编价**（成本 0、token 仍如实计）。
  - **`Harness`**（`argos_agent/core/harness.py`）编排 L1–L5：`enter_phase`（阶段门 plan→act→verify→report 不可跳）、`run_verify_gate`（三态 Verdict + 超 `max_rounds` 投 `Escalation`）、`accept_receipt`（HMAC 核验回执，伪造则拒）。
  - **W2 接线**：`AgentLoop` 真正调用 `Harness` —— `enter_phase` 取代内联 `_phase`、`run_verify_gate` 取代内联 verifier 调用 + escalation、**`accept_receipt` 在投 `ToolReceipt` 前核验回执 HMAC**（§6.5）。loop 内不再保留并行的 phase/verify/receipt 逻辑（无死代码）。
  - **W3 接线**：loop 系统提示走 `compose_system(HONESTY_SYSTEM, untrusted=format_untrusted(skills, store.recall(goal)))`（store 带 recall 时）；流式 delta 过 `StreamingContextScrubber` 再投 `TokenDelta`（防模型把 untrusted 围栏吐回 UI 泄露）。**无可召回 store → 诚实降级 `HONESTY_SYSTEM` only**（不假装召回发生过）。
  - **诚实修正**：`Verifier.verify(None)`（没配 verify_cmd）现返 `unverifiable` 而非 `passed` —— 没有验证命令真的跑过就绝不声称成功（落实 HONESTY_SYSTEM 规则 1）。但无测任务必须能收尾：`Harness` 据 `verify_cmd is None` 把这种 `unverifiable` 当**诚实非阻塞完成**（不 bounce/escalate，report 诚实标 "未机检验证 (no test command)"）；配了 verify_cmd 却 `unverifiable`（篡改/超时）或 `failed` 才走 bounce/escalate。
- 引擎核心:自建 CodeAct `AgentLoop`（`argos_agent/core/loop.py`，替换 LangChain create_agent），四阶段 plan→act→verify→report 不可跳，抽 Python 代码块→沙箱执行→回灌，投 12 类型化事件并持久化（一份事件三用）。**端到端铁证**：`tests/test_e2e_loop_sandbox.py` 真 AgentLoop 驱动真 Seatbelt sandbox-exec 子进程，`write_file` 代码在 OS 沙箱内执行，文件真落盘 workspace（非 mock）。
- 诚实栈:`HONESTY_SYSTEM` 搬到 `argos_agent/core/honesty.py`，`format_untrusted` + `compose_system` 保证安全段永远在 untrusted 段之前（注入顺序锁死，spec §12.1）。
- Verifier 占位（契约 §9 锁#1 canonical 签名）:`argos_agent/core/verify_gate.py` — `Verifier.verify(verify_cmd, *, attempts=1) -> Verdict`，三态 fail-closed（passed/failed/unverifiable），内部处理篡改检测与 VERIFY_DIR 隔离，Phase 4 同名签名直接替换。
- `EventBus`（`argos_agent/tui/events.py`）:loop 与 TUI 的唯一交汇点，asyncio.Queue 事件桥，Phase 3 落地。
- **Phase 3 安全沙箱地基（Tasks 0–6）** — 立起 `argos_agent/sandbox/` 子包：`SandboxBackend` 协议 + `ExecResult` 值对象（契约 §5）；macOS Seatbelt deny-all profile（FS 只读写 workspace+temp，**网络系统级 OFF**）；`SeatbeltExecutor` 把 smolagents `LocalPythonExecutor` 跑在 `sandbox-exec` 子进程内，命名空间跨 code-action 存活；沙箱子进程 JSONL 协议 + broker RPC stub。**铁证（最关键）**：Task 6 测试故意授权 `os`/`pathlib`/`socket` import 绕过 smolagents AST 限制，断言 OS Seatbelt 真实拦截——FS 越界写得 `PermissionError: [Errno 1] Operation not permitted`；TCP connect 1.1.1.1:53 / DNS gethostbyname 得 `PermissionError: [Errno 1] Operation not permitted`——OS 级别拒绝，非 AST 层面。17 个新测试全绿，baseline 275 → 292 passed，零回归。
- 持久化地基：单文件 SQLite store（`argos_agent/memory/store.py`），七表（sessions/messages/events/messages_fts/memory/state_meta/schema_version），WAL + 写抖动重试 + 每 50 写 PASSIVE checkpoint。
- 类型化事件流（`argos_agent/tui/events.py`，12 个冻结事件）+ event sourcing：`append_event` 持久化、`replay(session_id)` 重放续跑（一份事件三用：UI/日志/续跑同源）。
- CJK 搜索双管：sqlite-vec 向量语义召回（主路径，对中文最稳健）+ FTS5 trigram 字面全文搜。
- 可解释召回 `recall()` 返回 `(记录, 为什么召回)`，如实标注相似度/verdict/模型；embedding 不可用时诚实降级字面匹配。
- source-agnostic embedding 抽象（`argos_agent/memory/embedding.py`）：默认本地 MLX（Jina v5-small，懒下载），失败回退现远程端点。
- 旧记忆迁移：`migrate_jsonl()` 一次性、非破坏、幂等地把 `~/.argos/memory.jsonl` 迁入 SQLite。
- 类型基石 `argos_agent/core/types.py`（VerdictStatus/Phase/DecisionKind/RiskLevel/ModelTierName/ApprovalLevelName），Phase 2-6 共用。
- **电脑操控 / Playwright Python SDK（第 7 步·最难关）** — 新加 4 个 LangChain 工具（`navigate` / `snapshot` / `click` / `type_text`）包装 Playwright Python SDK，让 Argos 能像人一样操控浏览器——**先结构后图形**：能读结构就读结构（准、省），读不到才退回"看截图+移鼠标"（本步不装、留接缝）。**探针换路径**：spec 探针已证 chrome-devtools MCP 时序不稳（`/tmp/control_probe3.py`：3 次重试都"Successfully navigated"但 `list_pages` 仍 about:blank——重试救不了，是 chrome-devtools server 自身状态同步 bug），转 b 路线用 Playwright Python SDK（`/tmp/pw_probe.py`：`page.goto` 真返 `status=200`、`page.url` 立即更新、`wait_for_selector("h1")` 同步等、`page.title()` 直接拿）。**审批闸守住写操作**：`navigate`（改地址+cookies=副作用）/`click`（risk=low）/`type_text`（risk=medium）走 `requires_approval`（与 `run_command` 同款 `@tool @requires_approval` 双装饰、coroutine 是审批 wrapper、invoke 真拦 gate）；`snapshot` 只读直接放行。**spec §2 红线兑现**：附真 venv 降级探针 `tests/computer_control_probe.py`（CI skip），跑 3 真实多步任务（navigate+snapshot / navigate+click+snapshot / navigate+type_text+snapshot），**任一写操作任务失败 → 改 `ENABLED_WRITE_TOOLS=False`、只留 `navigate`+`snapshot`**。诚实标注：单 browser / 单 context，**并发 run 同用会冲突**（工具描述里明示，不真锁）。前端零改。铁证：4 工具 invoke 行为 / 审批门真拦 invoke（3 测试） / Lazy init 失败兜底 / 降级 toggle / ALL_TOOLS 合集形状均独立单测覆盖。
- **拆大活 / 动态工作流（第 6 步）** — `POST /plan` 端点接收一个工程任务，planner 调 M3 强模型拆 2-5 摊成 `PlanSpec`（pydantic 硬契约，**M3 推理模型自动剥 `<think>` 块 + lenient JSON 提取**，探针确认 100% 跑出结构化 task），再 fan-out 给 N 个并发 worker（**自定义 `asyncio.gather` + `asyncio.Task(coro, context=copy_context())`——探针铁证 LangGraph Send 默认不复制 ContextVar，spec §4.3 红线兑现必须手包**）。每 worker 跑在自己隔离区（sandbox per-task 子目录 / project 模式 per-task worktree 分支 `argos/<session>-<task_id>`），复用第 5 步 `build_agent_with_gate` + checkpointer + 审批闸 + 验证门。**reducer 纯函数**看 N 个 verdict：全 pass → 出报告;部分 fail → "补"动作（最多 2 轮，planner 带失败 task 反馈再拆）→ 不死循环;planner 不可用（M3 缺 key）→ 显式 `plan:escalate` 事件，**不降级到 M2**（spec §4.3 红线）。SSE 事件：`plan:start` / `plan:tasks` / `task:start` / `task:verdict` / `plan:report` / `plan:escalate`;前端零改动。铁证：硬契约 / 强模型剥 thinking / fan-out 承重墙 / "补"回路 / planner escalate / 端到端编排 / 端点流形状均独立单测覆盖。
- **分身并行 / per-worker 隔离（第 5 步·承重墙）** — sidecar 从进程级单飞改成多分身同进程并发：`runtime` 当前上下文从裸全局改 `ContextVar[RunContext]`（探针确认 sync 工具经 LangChain executor 读到 per-task 值、并发零串台），每个 run 各写各的隔离区——sandbox 走 `~/.argos/runs/<session>/` 子目录，**project 模式走 git worktree（分支 `argos/<session>`，用户工作树不被动，review 分支再 merge）**，非 git 项目诚实降级"原地 + 该项目单飞"。并发由 `asyncio.Semaphore`（默认 4，`ARGOS_MAX_CONCURRENT` 可调）控，超额排队发 `queued` 事件，不吹"数百并发"。**中途被杀能恢复**：`AsyncSqliteSaver` checkpointer（`~/.argos/checkpoints.db`）+ per-run `thread_id` + 持久 run 档案（`~/.argos/runs.db`），`POST /run/{id}/resume` 从 checkpoint 续跑（探针证跨 saver 实例=跨重启可续）。事件流形状不变、前端零改动。铁证：ContextVar 并发隔离、两 run 各写各目录、worktree 生命周期、kill-resume、semaphore 排队均独立单测覆盖。
- **Skills 技能包 + 记忆回灌（第 4 步）** — 标准流程沉淀为带 frontmatter 的 markdown（`~/.argos/skills/`
  + 内置库），run 开始按 goal 向量检索 top-3 注入 system prompt；**已过验证的任务**同样按 goal
  向量召回 top-3，带 verdict/出处到 system prompt。向量走 MiniMax `embo-01`（`/v1/embeddings`，
  1536 维，本地磁盘缓存），失败降级到"无 recall"不崩。**安全不变量**：注入段明示
  "untrusted" 边界，`HONESTY_SYSTEM` 与安全段永远在它之前；**imported 技能驱动的有副作用动作
  = 同一审批闸**（共享 `approval.guarded_call` + `source: skill:<name>` 标 payload）；技能操作端点
  （`/skills/import`、`/skills/{name}/toggle`）走 sidecar 进程级 `_SKILL_GATE`，UX 与 run 内审批一致。
  端到端铁证：向量检索、middleware 拼接顺序、端点走闸均独立单测覆盖。
- **MCP 插座（第 3 步）** — 接入真正的 MCP 生态：`langchain-mcp-adapters` 客户端按 `~/.argos/mcp.json`
  连默认安全集（`chrome-devtools` 浏览器自动化 / `filesystem` / `github` 只读），拉回的工具按注解
  分类——只读放行、有副作用或未知一律 **fail-closed 过审批闸**（共享 `approval.guarded_call`，
  经 `gate_mcp_tool` 包装，弹窗 payload 标注 `source: mcp:<server>`）。逐 server 连接、任一失败
  优雅降级（不崩，其余仍可用），25s 连接超时；端点 `GET /mcp/servers` 暴露真实连接态，前端
  删掉假 MCP seed 改读它。dev-only（打包延后）。铁证：端到端真连 `npx` filesystem MCP，
  套闸后 `ainvoke` 经真实 schema 真写文件；分类对 14 个工具逐一校验；
  `approval_request` 在 MCP 工具阻塞时同样弹窗。

### Fixed
- **verify 硬门禁字节码陈旧假失败(集成铁证逼出的真可靠性 bug):** `Verifier` 跑验证子进程未禁字节码 —— agent 改源后,若改动同尺寸且赶在同一秒(mtime 秒级分辨率,如 `a - b`→`a + b`),pytest 复用陈旧 `.pyc` 对【旧字节码】下判,模型修好了却仍 `failed` → 假 bounce / 假升级。修:验证子进程 `PYTHONDONTWRITEBYTECODE=1`,每次现导当前源码,verdict 永远反映当前代码。
- **loop 持久化缺 session 行 → `replay` 失败:** loop 用调用方提供的 `session_id` 但 `create_session` 自生成 uuid、`append_*` 不 auto-create,replay 找不到 session。修:`ArgosStore.ensure_session(指定 id,幂等 INSERT OR IGNORE)`,loop 在 run 起始先落 session 行(resume 复用同一 session)。
- **Agent claimed it had no internet** even though web tools were wired up. The
  system prompt (`HONESTY_SYSTEM`) only advertised file/command tools, so the
  model "honestly" refused web queries (e.g. weather) instead of calling
  `web_search`. Prompt now lists all three tool classes (file / command / web)
  and instructs the model to search before saying it can't. Verified
  end-to-end: asking weather now triggers a real `web_search` call.
- **`/undo` `/retry` 是 stub 占位字符串** —— 此前点击只落 `"/undo 将在后续接线后生效。"`(陪了 ~24h),现在接真,描述去"待接线"。

### Added
- **审批闸（approval gate）** — 有副作用的工具（写文件 / 编辑文件 / 执行命令）执行前
  必须经用户显式确认：UI 弹模态、展示真实操作描述与参数、三个按钮（拒绝 / 允许一次 /
  本次会话总是允许，高风险隐藏"总是允许"）。默认 deny、超时 deny、无审批上下文 deny ——
  绝不偷偷放行。工具自声明（`@requires_approval` 装饰器套在 langchain `@tool` 内层，
  `functools.wraps` 保住参数 schema），后端按 `(session, call_id)` 经 SSE `approval_request`
  事件推送、`POST /run/{session_id}/approve` 回决定;审批 future 用 `call_soon_threadsafe`
  跨执行线程唤醒(否则交互审批在生产里会永久挂起)。端到端铁证:approve→工具真执行+文件落地;
  deny→拒绝串+零副作用;session-scope 批准跨轮免重复弹窗;timeout/无 gate 一律拒绝。
- **验证门防作弊**：受保护测试被改/增/删时判"无法验证"并诚实升级，不再被"偷改测试让它过"蒙混；指纹由 mtime/size 升级为内容 sha256。
- **`package-app` project skill** (`.claude/skills/package-app/`) — the build
  runbook for rebuilding the arm64 PyInstaller sidecar and repackaging the
  `.app`/`.dmg`, including the x86_64-venv trap and spec-parity rules.
- **Agent chat skeleton (Phase 1 of the chat-experience epic)** — two-column
  shell (left chat column max-width 760px centered, right side exposes the
  background memory brain), `react-markdown` + `remark-gfm` + `rehype-highlight`
  with custom code blocks (language label + copy button), `chatReducer` that
  merges SSE events into ordered `Block[]` per turn, `HonestyCard` for
  verify/escalation/tampering signals, collapsible `ActivityTrail` for tool
  steps, multi-line auto-grow `Composer` with `Enter` send / `Shift+Enter`
  newline and `onSlash`/`leftSlot`/`rightSlot` extension hooks for Phases 2/5/6,
  collapsible `TaskSetup` for verify/project/guard settings. `AgentPanel` is
  lazy-loaded so the main bundle stays at 278 KB / 95 KB gzip; the markdown
  stack (~348 KB) only loads when the user opens chat. See
  `docs/superpowers/specs/2026-06-02-agent-chat-redesign-design.md` and
  `docs/superpowers/plans/2026-06-02-agent-chat-skeleton.md`.
- **Real token streaming** — `agent.astream(..., stream_mode=["values","messages"])`
  emits a new `token` SSE event for each `AIMessageChunk` text delta; the
  `message` event is preserved as the authoritative finalization (frontend
  reducer uses it to overwrite any accumulated tokens and prevent drift).
  Reasoning-model `thinking` content is filtered out (`text_delta` helper).
  Verified end-to-end with a real LLM: 6 incremental `token` frames → 1
  `message` finalization → `done`.
- **Component test infrastructure** — `vitest` with `jsdom` + `@testing-library/react`
  + `@testing-library/jest-dom`; 28 new component tests + 11 reducer tests
  for the chat skeleton.
- **CSS tokens** — `--warn` / `--danger` / `--danger-strong` so the honesty
  cards, error blocks, and Composer stop button share one source of color truth.
- **`Highlight.js` dark theme** — 13-line handcrafted stylesheet matching the
  argos palette, paired with `rehype-highlight`.
- **TUI UX 欠账偿还(/undo /retry + read_file offset/limit + edit_file multi-replace)。** 三件一起做:
  ① `/undo` 还原本轮 run 起点的文件改动(`RunSnapshot` 拍 tar 快照到 `tempfile.gettempdir()/argos-snapshots/`,剪枝目录复用 `runtime.SNAPSHOT_PRUNE_DIRS`;run 中新建文件不删,失败逐条报不静默);② `/retry` 重发本 session 最后一条 user 消息(busy 时先 Esc 打断,空 session / store 不支持诚实报);③ `read_file` 加 `offset`(0-based 行号)/ `limit`(行数,None=EOF),去掉 8000 字符硬截断;④ `edit_file` 加 `all_occurrences=False` 默认(唯一匹配,True 多处替换,N≤1000)。系统提示新增 `_tool_signatures_block`,跟 `_env_context` 同位置(HONESTY 之后、untrusted 之前),列新签名防漂移。+21 测试(snapshot 7 + signature 2 + loop snapshot 2 + read_file 5 + edit_file 4 + undo 3 + retry 5;部分为追加)。

### Changed
- config 加 `ARGOS_*` 键（最高优先级），回退旧 `VITE_LLM_*` → `VITE_MINIMAX_*`，零破坏已配用户；组装 `WORKER_TIER`/`PREMIUM_TIER`/`WORKER_KEYS`。
- `.gitignore` now tracks `.claude/skills/` (shared project skills) while still
  ignoring local `.claude` state; root `/build/` ignored.
- `AgentEvent['type']` gained `'token'` for the streaming event; reducer and
  downstream rendering path handle the new event as a first-class stream.
- Project-guide `CLAUDE.md` now mandates Chinese as the user-facing reply
  language.
- **重大转向：删除 Tauri/React 桌面壳，Argos 重做成单 Python 进程的 Textual TUI 编码超级智能体**（设计见 `docs/superpowers/specs/2026-06-03-tui-superagent-design.md`）。
- Python 项目从 `agent/` 移到仓库根；新增 `argos` 命令入口与 Textual TUI 骨架。

### Removed
- `src/`（React UI）、`src-tauri/`（Tauri 壳）、前端构建工具链（vite/pnpm/tsconfig）、FastAPI sidecar 启动脚本 `run_server.py`。

## [0.1.0] — 2026-06-01

First packaged build (`Argos.app` + DMG, native arm64). Argos is a standalone
general-purpose agent (Tauri shell + Python LangGraph sidecar), pivoted from the
earlier Hermes-swarm prototype.

### Added
- **Standalone agent core** — LangGraph ReAct loop over a provider-agnostic LLM
  factory (any OpenAI/Anthropic-compatible endpoint; defaults to MiniMax).
- **Agent tools (7)** — `read_file`, `write_file`, `edit_file` (with
  whitespace-fuzzy fallback matching), `run_command` (whitelisted),
  `search_files`, `web_search` (DDGS free / Tavily upgrade), `web_extract`
  (trafilatura + LLM compression). File access caged to the workspace; web is
  read-only.
- **Honesty + verify guardrails** — honesty protocol in the system prompt,
  fail-closed verdict parsing, verify hard-gate with escalation and
  tamper-detection.
- **Multi-turn chat** — in-process session state with first-turn-locked setup,
  LRU eviction, single-flight run lock to prevent cross-session races.
- **MindGraph UI** — memory graph that grows from real task activity; brain
  re-anchors/re-fits on window resize while docked.
- **Settings** — provider/base/model/key form, language toggle (EN/中),
  packaged key injection (Settings → config file → Rust → sidecar env).
- **Packaging** — PyInstaller single-file sidecar bundled into the Tauri build;
  `pnpm tauri build` produces `.app` + `.dmg`.

### Changed
- Migrated off Hermes branding throughout the UI (center node, command bar,
  model labels); tool counts now reflect the real 7 tools instead of seed "60+".

<!-- dev 验收清单（依赖真实 LLM/sidecar，不进 CI）：

1. 起 dev sidecar，两个不同 session 同时 `/run`（curl 两条 SSE）→ 两条流并行推进、各写各的 `~/.argos/runs/<session>/workspace`，互不串台。
2. project 模式（指向一个 git repo）跑一轮 → 改动落在 `argos/<session>` 分支的 worktree，用户工作树不动；`git worktree list` 可见。
3. 起一个长 run，中途 `kill` sidecar → 重启 → `POST /run/<run_id>/resume` → 从 checkpoint 续跑到 done。
4. 把并发数压到 `ARGOS_MAX_CONCURRENT=1`，连发两轮 → 第二轮收到 `queued` 事件后排队、不丢。
5. 恶意 session_id（如 `../../etc`）会被 isolation 拒绝、发 `error` 事件、隔离根不逃出。
-->

<!-- dev 验收清单（依赖真实 M3 + 真 sidecar，不进 CI）：

1. 启 dev sidecar，`POST /plan {goal: "把所有 deprecated os.path.join 改写为 pathlib.Path"}` → 收到 `plan:start` → `plan:tasks(N=3-4)` → 多个 `task:start`/`task:verdict` 并行 → `plan:report{split,succeeded,failed,replan_rounds}`。
2. 故意构造一个失败 task（如 goal="改完跑一个不存在的命令"），观察"补"回路：planner 第二轮被调、`plan:tasks` 再次出现、终态 `replan_rounds ≥ 1`。
3. 删 `VITE_MINIMAX_KEY` env 重启 → 第一个 `plan:start` 后立即出 `plan:escalate`（不降级 M2）。
4. 用隔离目录排查工具：plan 跑完后 `ls ~/.argos/runs/<session>/tasks/<task_id>/workspace/` 看到各 task 独立落点。
-->

<!-- dev 验收清单（依赖真网络/真浏览器，不进 CI）：

1. 启 dev sidecar，跑 `tests/computer_control_probe.py`（去 skip）→ 3 任务全绿保留 click/type；任一 click/type 任务失败 → 改 `ENABLED_WRITE_TOOLS=False`、CHANGELOG 加降级条目。
2. 在聊天里问"用浏览器查 Argos 自己的 GitHub" → 收到 `navigate` 的审批弹窗 → 确认 → 看到 `snapshot` 自动跟进。
3. 问"打开一个表单页填个搜索词" → 收 `navigate` + `type_text` 两个审批 → 全确认 → 报告结果。
4. 检查侧车日志：browser launch 失败时 `ALL_TOOLS` 装配失败，警告但不掀翻 sidecar。
-->

[Unreleased]: https://github.com/tungoldshou/argos/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/tungoldshou/argos/releases/tag/v0.1.0
