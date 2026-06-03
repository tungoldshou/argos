# Changelog

All notable changes to Argos are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
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
- **Agent claimed it had no internet** even though web tools were wired up. The
  system prompt (`HONESTY_SYSTEM`) only advertised file/command tools, so the
  model "honestly" refused web queries (e.g. weather) instead of calling
  `web_search`. Prompt now lists all three tool classes (file / command / web)
  and instructs the model to search before saying it can't. Verified
  end-to-end: asking weather now triggers a real `web_search` call.

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

### Changed
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
