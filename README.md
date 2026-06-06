# Argos — 终端超级智能体

一个独立的终端(TUI)超级智能体:**单个 Python 进程**,基于 Textual。它通过
Anthropic-Messages / OpenAI 兼容端点驱动**任意模型**(不绑定厂商),核心是一套**自建的
CodeAct 循环** + **verify 硬门禁** + **诚实协议** + **OS 沙箱执行器**。

项目灵魂:让便宜模型变得*可靠* —— 诚实协议 + verify 硬门禁,而不只是又一个模型套壳。

> 不只是编码智能体:Argos 是 **Claude Code + 通用 agent** 的合体 —— 在写代码之外,还能
> 联网检索、**开浏览器操控电脑**(导航/点按/填表/截图)、按需调技能(Skills)、对结构化任务
> 注入"必检约定"契约、经 **MCP** 扩展任意外部工具、**把大任务确定性 fan-out 给多个子 agent
> 并行**(Dynamic Workflows)。每一项能力都遵循同一条底线:**能验证才说完成,不行就如实说,绝不假装。**

## 快速开始

需要 Python 3.12+ 与 [uv](https://docs.astral.sh/uv/)。

```bash
uv sync
uv run argos              # 启动 Argos TUI
uv run argos setup        # 交互向导:接入任意模型(选 provider→填 key→连通+格式探针)
uv run argos --selftest   # 不连网整机自检(脚本模型跑四阶段,打印 verdicts)
uv run pytest -q          # 跑测试
```

无 API key 时 `argos` 会诚实落 demo 态(不假装能跑),并提示运行 `argos setup`。

## 安装

### 一键安装(macOS arm64)

```bash
curl -fsSL https://raw.githubusercontent.com/tungoldshou/argos/main/packaging/install.sh | bash
```

装到 `/Applications/Argos.app`,建 `/usr/local/bin/argos` 符号链接。

### Homebrew Cask(macOS arm64)

```bash
brew install --cask -s packaging/homebrew/argos.rb
```

(TODO:单建 `tungoldshou/homebrew-argos` tap 后改用 `brew install --cask argos`——见 #12 阶段。)

### 升级

```bash
argos self-update   # 提示新版本(不下载)
# 实际升级重跑 install.sh / brew upgrade
```

### 从源码

```bash
git clone https://github.com/tungoldshou/argos
cd argos
uv sync
uv run argos
```

## 架构

活引擎是 **framework-free** 的(不依赖 langchain/langgraph),唯一外部执行器是
smolagents 的沙箱 `LocalPythonExecutor`。

- **`argos_agent/core/`** — agent 大脑:自建 **CodeAct** 主循环(`loop.py`,
  plan→act→verify→report 四阶段不可跳)、5 层 harness、诚实栈(`honesty.py`)、模型协议
  适配(`protocols.py`,Anthropic + OpenAI 双协议)、模型分档(`models.py`)。
- **`argos_agent/sandbox/`** — OS 沙箱:macOS Seatbelt 执行器 + capability broker
  (特权动作边界:egress allowlist + 审批闸 + HMAC 回执)。
- **`argos_agent/tools/`** — 注入沙箱命名空间的 16 个工具:文件读写编辑搜索、白名单 shell、
  联网检索/正文提取、**浏览器计算机控制**(`browser_navigate/snapshot/click/type/screenshot`,
  见 `browser.py`,守护线程跑 sync Playwright,默认有头可见窗口)、**`mcp_call`**(经 `mcp_native.py`
  连 `~/.argos/mcp.json` 的 MCP server 扩展任意外部工具)、`propose_verify`(独立验证门)、
  `update_plan`(真 TODO 拆解)、`propose_workflow`(提议 Dynamic Workflow)。
- **`argos_agent/workflow/`** — Dynamic Workflows:声明式 `WorkflowSpec` + host 确定性引擎,
  agent 经 `propose_workflow` 提议,fan_out/pipeline/panel/loop_until/synthesize 五形态把任务
  并行派给隔离子 agent(独立沙箱/worktree,模型无关 per-agent),逐阶段验证、汇总回灌。
- **`argos_agent/memory/`** — SQLite + 向量召回(复用 active provider 的 embeddings,
  否则诚实退 FTS5 关键词,绝不偷调模型)。
- **`argos_agent/skills.py` / `contracts.py`** — 按 goal 召回的技能库(零模型关键词兜底)+
  结构化任务"必检约定"契约层(REST/DB/状态机/配置;非结构化不注入)。
- **`argos_agent/approval.py`** — 有副作用动作执行前的审批闸(默认确认,fail-closed)。
- **`argos_agent/tui/`** — Textual TUI 外壳:argos-night 主题、Markdown/语法高亮、
  右侧诚实活动栏(模型/进度/工具/签名回执/成本)、启动 logo、verdict 三态着色。
- **`tests/`** — pytest 测试套件。**`pyproject.toml`** — 单 Python 项目,`argos` 控制台入口。

## 打包

PyInstaller 打成**单个 arm64 binary**(`packaging/build_arm64.sh` → `dist/argos`)。
用 `dist/argos --selftest` + `python smoke_packaged.py` 验收。详见 `package-app` skill。

## 交互

### Plan mode

```bash
/plan
```

进入"只看 plan 不动手"模式,host 拼 markdown plan 文档(任务分解 / 涉及文件 / 风险 / 审批 4 段),
完成后弹审批 modal 让你挑 4 选项之一:

- `1` **Approve and start** —— 全权限,继续 act 阶段
- `2` **Approve and accept edits** —— 写/编辑类工具自动批,其他按现有审批流
- `3` **Keep planning** —— 继续 plan 阶段(不退出 plan mode)
- `4` **Refine** —— 提供补充上下文后重新 plan

期间 TUI 标题前缀 `[plan mode]` + 边缘光变色 + status_bar Mode 段同步;沙箱工具
(`write_file` / `edit_file` / `run_command` 等)被 dispatcher 拦截,不进沙箱。
对齐 Claude Code user-facing `EnterPlanMode` / `ExitPlanMode` 的"看 → 批 → 干"流。

### Hooks

在 `~/.argos/hooks.json` 配置 5 个生命周期点的自定义脚本(secret 扫描 / auto-format / 桌面通知 / 自定义验证 / metrics 上报)。对齐 Claude Code hooks 行为。

**示例**:

```json
{
  "version": 1,
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "write_file|edit_file",
        "hooks": [
          {"type": "command", "command": "~/.argos/hooks/audit-mutate.sh", "timeout": 5000}
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "write_file|edit_file",
        "hooks": [
          {"type": "command", "command": "ruff check {cwd}", "timeout": 30000}
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {"type": "command", "command": "osascript -e 'display notification \"Argos done\" with title \"Argos\"'"}
        ]
      }
    ]
  }
}
```

**命令**:
- `/hooks` — 列出当前生效配置
- `/hooks reload` — 重读 `~/.argos/hooks.json`

**⚠️ 安全警示**:hook = 用户脚本,与 agent **同权限**运行(不进 Seatbelt 沙箱);装第三方 hook 前请**审计源码**。PreToolUse 退非 0 = 阻塞工具调用;反喂消息经 agent 看到。

### LSP(语言服务器集成)

Argos agent 可调 6 个真语言服务器原语:`lsp_definition` / `lsp_references` / `lsp_hover` / `lsp_document_symbols` / `lsp_workspace_symbols` / `lsp_diagnostics`,从中大型项目里拿结构化代码情报(symbol 位置 / references / type 错),替代纯文本 grep + 全文读。

**配置**:`~/.argos/lsp.json`(`lsp.json` 不存在 → 走 built-in 默认单 python server;`pyright-langserver` 未装 → 该 server 自动 disabled + log 一行):

```json
{
  "version": 1,
  "servers": {
    "python": {"command": ["pyright-langserver", "--stdio"], "filetypes": [".py", ".pyi"]},
    "rust":   {"command": ["rust-analyzer"], "filetypes": [".rs"],
               "init_options": {"cargo": {"allFeatures": true}}},
    "typescript": {"command": ["typescript-language-server", "--stdio"], "filetypes": [".ts", ".tsx"]}
  }
}
```

**安装示例**: `pip install pyright` / `brew install rust-analyzer` / `npm i -g typescript-language-server typescript`

**命令**:
- `/lsp` — 列出当前生效 servers(状态 / filetype / diagnostics 计数)
- `/lsp reload` — 重读 `~/.argos/lsp.json`;不影响正在跑的 run(下个 `lsp_*` 起新规则)

**⚠️ 安全警示**:**LSP server 跑在沙箱(Sandbox)外,以你的账户权限运行**。`command` 数组直接 spawn 子进程;若装"看起来像 language server"实为木马的二进制,会跑用户全权限代码。**只配你审计过二进制的 command** —— 装第三方 LSP server 前请检查来源/源码。Argos 启动时 stderr 会显一行 `⚠ LSP server '<name>' running: <command>` 告警。

### Skills(自检原语 3 件套)

Argos 提供 3 个 on-demand 自检 slash —— 用户中途一键复跑,**不复用 agent 自己写的代码**:
- `/verify` —— 显式跑 `Verifier.verify`(D9/D13:用户路径,不走 agent 的 `propose_verify`);无 `verify_cmd` 配置时 verdict=`n_a` 并引导配
- `/security-review` —— 3 pass:secrets(9 regex 含 `sk-ant-`)/ 依赖漏洞(shell out to `npm`/`pip-audit`/`cargo-audit`)/ 危险 API(Python + JS/TS `eval`/`child_process`/`innerHTML`);缺审计工具必报 error(D5 防假绿)
- `/simplify` —— 3 pass:token shingle 重复块 / 函数体复杂度(> 15 分支 warning)/ 死代码启发;默认 top-10 截断

**⚠️ 安全警示**:
- `pip-audit` / `cargo-audit` **需用户自装**;缺 → 报 error severity(D5 假绿护栏),不静默跳
- `.env` / `.env.*` / `secrets.toml` / `*.pem` / `*.key` **跳过不扫**(user-controlled 秘密存储,误报多)
- 测试代码 `eval` / `exec` **降级 info**(避免误报测试 fixture)
- 这些 skill **只报不修**;改不改由你拍板(同 `/lsp` 模式)

### Long-running task + 后台 daemon(5+ 分钟任务)

`#5a` 落地,5+ 分钟任务不再"必须守着等"。所有 run 由独立 daemon 进程托管,持久化到 `~/.argos/runs/<id>.jsonl`(真相源 + checkpoint + SSE 事件流);`~/.argos/runs/index.json` 是缓存。

**键盘**:
- `Ctrl+B` — 后台化(正在跑 → `suspended`;立刻可开新目标,跨 session 续跑)
- `Esc` — 在下一个 step 边界暂停(`paused`;worker 真到 step 入口才阻塞,resume 接着 yield)
- `Esc Esc`(1.5s 内)— 取消
- `Ctrl+C` — 软中断(TUI 退;daemon 继续跑,run 持久化)

**启用 daemon**(`--with-daemon` 显式 opt-in,默认 False):
```bash
uv run argos --with-daemon
```

启动时弹 inline modal 让你挑 suspended run 续跑(若没有 → 直进 idle)。

**文件路径**(全部 0600 权限):
```
~/.argos/daemon.sock        # Unix socket(IPC)
~/.argos/daemon.pid         # daemon PID
~/.argos/daemon.log         # stderr/stdout
~/.argos/runs/<id>.jsonl    # 单 run 事件流(真相源)
~/.argos/runs/index.json    # 小状态索引(缓存)
```

**不启用 daemon 时**(默认):`Esc` 沿用旧行为(整 run cancel),无跨 session 续跑。

**不做(留 v1.1 / #5b)**:多 run 并行 + Run tabs + 多 TUI 实例互斥 + worktree-per-run + cost tracking per run。
