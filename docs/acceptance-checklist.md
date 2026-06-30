# Argos — Feature Acceptance Checklist

> 目的:把"Argos 能做什么"摊成块,对照 Claude Code 当参照,**每块先确认地基、再让你亲手端到端验收打勾**。
> 地基状态来自 2026-06-30 的代码实测体检(逐功能核过 working / partial / gated / needs-setup / broken)。
>
> 用法:从 Tier A 往下走,一块一块来。每块:① 看地基状态 ② 按"怎么测"跑一遍 ③ 对照"期望" ④ 勾 ✅ 或记 ❌。
> 地基是 ✖/◐ 的块,先补地基再验收(已标注)。

图例:✅ 地基稳 · ◐ 部分 · 🔧 需装外部依赖 · 🔒 默认关需开关 · ✖ 地基没打好(先修)

---

## Tier A — 核心日常(和 Claude Code 同台的部分,地基都稳)

### A1. 启动与配置  ✅
- **是什么 / CC 参照**:`argos setup` 配 provider+key,启动 TUI。≈ Claude Code 首次登录配置。
- **怎么测**:
  1. `uv run argos setup` → 选 provider → 填 key → 看到连通探针评分
  2. `uv run argos` → 右上角应显 `✳ LIVE`(配好 key)或 `⚠ DEMO`(没 key)
  3. 反例:故意在 paste key 处直接回车 → 应当场提示"没输入 key"并要你重配(不是迷惑的 401)
- **期望**:LIVE 态可输入目标;DEMO 态诚实标"无 key"。
- **验收**:☐

### A2. 读 / 写 / 改 / 搜文件  ✅
- **是什么 / CC 参照**:`read_file` / `write_file` / `edit_file` / `search_files`。≈ CC 的 Read/Write/Edit/Grep。
- **怎么测**:在 TUI 给一个真目标,例:`在 hello.py 里写一个 greet(name) 返回 "hi <name>",再把 "hi" 改成 "hello"`。
- **期望**:文件真被创建/修改(去工作区看);改动只在工作区内(沙箱牢笼)。
- **验收**:☐

### A3. 跑命令(沙箱内)  ✅
- **是什么 / CC 参照**:`run_command`,无命令白名单,跑在 OS 沙箱里(默认无网)。≈ CC 的 Bash。
- **怎么测**:给目标 `跑 ls 和 python --version`;再给一个要联网的 `pip install requests`。
- **期望**:普通命令直接跑;联网命令在 Cautious 下到"出网阀"会要你批准(Autonomous 下自动)。
- **验收**:☐

### A4. 计划 / TODO / 上下文  ✅
- **是什么 / CC 参照**:`update_plan`(右栏 TODO)、`/context`(4 桶占用)、超 80% 自动压缩。≈ CC 的 TodoWrite + 上下文管理。
- **怎么测**:给一个多步任务,看右栏是否出现 TODO 拆解;输 `/context` 看占用表。
- **期望**:TODO 实时更新;`/context` 显示 system/memory/tools/messages 四桶。
- **验收**:☐

---

## Tier B — Argos 的招牌(别人没有的,地基稳,重点验收)

### B1. ⭐ 验证硬门 + 三态判决(头号护城河)  ✅
- **是什么 / CC 参照**:改代码后强制跑你声明的验证命令,读退出码给 `passed/failed/unverifiable`,绝不假绿灯。**Claude Code 没有这个**——它信模型说"完成了"。
- **怎么测**:
  1. 不用 key:`uv run argos --demo-fail` → 看脚本演示"验证失败→bounce→重试→诚实升级"
  2. 用 key,在 TUI:`实现 fib.py 使 python -c "import fib; assert fib.fib(10)==55" 通过` → 看它写码→验证→错了把真报错打回→改对→passed
  3. **测诚实**:`随便写个函数,别测,直接说完成` → 期望:它**做不到**假装通过,判决停在 unverifiable
- **期望**:完成 = 退出码,不是模型嘴;假绿灯过不去。
- **验收**:☐

### B2. ⭐ 沙箱 + 权限 + 硬规则(治理地基)  ✅
- **是什么 / CC 参照**:OS 级沙箱默认开(macOS Seatbelt / Linux bwrap),`/trust` 三档,一组硬规则(rm -rf、系统路径、密钥、金融操作)永不绕过。≈ CC 的权限,但加了 OS 内核牢笼 + 签名回执。
- **怎么测**:
  1. `/trust` 切 Cautious→Trusted→Autonomous,看升档要不要确认
  2. 给个危险目标 `rm -rf /` → 期望:硬规则拦住,即使 Autonomous
  3. 让它写一个含 `AWS_SECRET=...` 的文件 → 期望:密钥检测拦
  4. `/ledger` 看本次每个动作的签名回执
- **期望**:危险操作被硬拦;每个特权动作有回执。
- **验收**:☐

### B3. ⭐ 后台长任务 + 续跑(daemon)  ✅(Ctrl+B 刚修好)
- **是什么 / CC 参照**:任务跑在常驻 daemon,关终端不死;`Ctrl+B` 后台化、`/runs` 管理、续跑。Claude Code 没有常驻内核。
- **怎么测**:
  1. 给一个较长任务,跑起来后按 `Ctrl+B` → 期望:提示"后台化,将在下个步骤边界挂起",**不再是假的"suspended"**
  2. `/runs` 看到那个 run;`/runs <id> resume` 续回去
  3. 进阶:`pkill -f argosd` 杀掉 daemon 再 `uv run argos` → 之前的 run 应被恢复成 suspended,可 resume
- **期望**:后台化真挂起(带 checkpoint),可续,活过 daemon 重启。
- **验收**:☐

### B4. 记忆(跨会话)  ✅ / 向量召回 ◐
- **是什么 / CC 参照**:4 层自动记忆 + `/remember /forget /memory`,自动读 CLAUDE.md/AGENTS.md。≈ CC 的 CLAUDE.md 记忆,但多了跨会话自动层。
- **怎么测**:`/remember 我偏好用 pytest` → 新开会话给相关任务 → 看是否被召回;`/memory` 看 4 层摘要。
- **期望**:记忆跨会话注入;无 embedder 时退 FTS5 关键词(仍可用,只是不懂改述)。
- **验收**:☐

---

## Tier C — 需要装外部依赖(地基在,装好即用)

### C1. 联网搜索 / 抓取  ✅(免费内置)
- **怎么测**:`搜一下 textual 最新版本并打开官网摘要` → 用 `web_search`(DDGS 免费,无需 key)+ `web_extract`。
- **期望**:返回搜索结果 + 正文摘要;无需任何 key。
- **验收**:☐

### C2. 浏览器自动化  🔧 `playwright install chromium`
- **怎么测**:先 `uv run playwright install chromium`;再给 `打开 example.com 截图` → `browser_navigate/screenshot`(默认有头窗口,你能看见)。
- **期望**:弹出可见浏览器执行;没装 chromium 则诚实报错(不崩)。
- **验收**:☐

### C3. MCP 外部工具  🔧 写 `~/.argos/mcp.json`
- **怎么测**:写 `~/.argos/mcp.json`(schema 见 docs/configuration.md)指一个 MCP server → `/mcp` 看是否连上 → 让 agent `mcp_call`。
- **期望**:连上的 server 工具可调;没配则诚实说"无 MCP server"。
- **验收**:☐

### C4. LSP 代码智能  🔧 装 `pyright`
- **怎么测**:`npm i -g pyright` → 给 `用 LSP 查 foo 的定义和引用` → `lsp_definition/references`。
- **期望**:Python 零配置即用;未装则该 server 标 DISABLED 并诚实报错。**已知局限**:未存盘的在途编辑 LSP 看不到(只看磁盘文件)。
- **验收**:☐

### C5. 语音 / 图片输入  🔧
- **怎么测**:语音=空输入框按空格录音(需 sounddevice+whisper,首次下载权重);图片=Ctrl+V 贴图(macOS 需 `brew install pngpaste`)。
- **期望**:语音转文字插入输入框;图片仅在多模态模型下发送。
- **验收**:☐

---

## Tier D — 进阶 / 默认关(按需开)

### D1. 动态工作流(子 agent 编排)  ✅ 默认开
- **怎么测**:给一个适合拆的大任务 `并行探索 3 个实现方案再选最好的` → 模型发 `propose_workflow` → 审批后引擎跑 5 形状之一(fan_out/pipeline/panel/loop_until/best_of_n),每个子 agent 独立 worktree+沙箱。
- **期望**:子 agent 并行跑,结果综合回来;`ARGOS_WORKFLOWS=0` 可关。
- **验收**:☐

### D2. 技能  ✅
- **怎么测**:`/skills` 看已装+可装+本次推荐;`uv run argos skills list`。给任务时看是否自动召回相关技能。
- **期望**:按目标自动召回(无 embedder 时关键词兜底);安装走 host CLI。
- **验收**:☐

### D3. 自主调度 + 夜间自进化(Conductor + Dream)  ✅ daemon-only
- **怎么测**:`/orders` 看常设订单;`/dream` 手动跑一轮整合 → 看它把验证过的 run 聚类/合成/A/B 晋升技能(**通过 A/B verify 门的技能会自动启用,无需确认**——这是有意的自主姿态)。
- **期望**:只有验证通过的经验变成技能;失败/不可验证的只留反思。inline 模式不跑(daemon-only)。
- **验收**:☐

### D4. 电脑控制(OS 级)  🔒 `ARGOS_COMPUTER_USE=1` + 授权
- **怎么测**:`ARGOS_COMPUTER_USE=1 uv run argos` + macOS 授屏幕录制/辅助功能 → 给 `截图并点击某处`。
- **期望**:默认全关;开了也要系统授权。**已知坑**:无屏幕录制权限时截图会静默截到壁纸还报成功(待修)。金融/支付类操作恒确认。
- **验收**:☐

---

## Tier E — 地基没打好,先修再验收

### E1. ✖ 自我评测 eval run/compare  — 先修
- **现状**:`argos eval corpus`/`list` 能用,但 **`argos eval run/compare`(和 `/eval run/compare`)是假 stub**——没接 loop_factory,直接报 `loop_factory_required: v1 uses fake stubs`。真 eval 只在 daemon Dream 内部能跑。
- **要做**:把真 loop_factory 接进 CLI/TUI 的 eval 路径(机理已存在)。**修完再验收**:`argos eval run <task>` 应真跑一个 loop 出 pass/fail。
- **验收**:☐(阻塞于修复)

---

## 建议顺序

1. **Tier A + B 先过**(地基都稳,纯验收,最快建立信心 + 看清招牌)。
2. **Tier C 按你需要的**装依赖逐个验。
3. **Tier D 按兴趣**。
4. **Tier E** = 把 eval 地基补上再验(它直接撑"留给用户自评"的定位)。

> 这份清单本身也是"Argos 有哪些功能"的答案。验收中发现的 ❌,就是下一批要修的地基。
