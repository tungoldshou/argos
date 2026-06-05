# Argos — 终端超级智能体

一个独立的终端(TUI)超级智能体:**单个 Python 进程**,基于 Textual。它通过
Anthropic-Messages / OpenAI 兼容端点驱动**任意模型**(不绑定厂商),核心是一套**自建的
CodeAct 循环** + **verify 硬门禁** + **诚实协议** + **OS 沙箱执行器**。

项目灵魂:让便宜模型变得*可靠* —— 诚实协议 + verify 硬门禁,而不只是又一个模型套壳。

> 不只是编码智能体:Argos 是 **Claude Code + 通用 agent** 的合体 —— 在写代码之外,还能
> 联网检索、**开浏览器操控电脑**(导航/点按/填表/截图)、按需调技能(Skills)、对结构化任务
> 注入"必检约定"契约、经 **MCP** 扩展任意外部工具。每一项能力都遵循同一条底线:**能验证才说
> 完成,不行就如实说,绝不假装。**

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

## 架构

活引擎是 **framework-free** 的(不依赖 langchain/langgraph),唯一外部执行器是
smolagents 的沙箱 `LocalPythonExecutor`。

- **`argos_agent/core/`** — agent 大脑:自建 **CodeAct** 主循环(`loop.py`,
  plan→act→verify→report 四阶段不可跳)、5 层 harness、诚实栈(`honesty.py`)、模型协议
  适配(`protocols.py`,Anthropic + OpenAI 双协议)、模型分档(`models.py`)。
- **`argos_agent/sandbox/`** — OS 沙箱:macOS Seatbelt 执行器 + capability broker
  (特权动作边界:egress allowlist + 审批闸 + HMAC 回执)。
- **`argos_agent/tools/`** — 注入沙箱命名空间的 15 个工具:文件读写编辑搜索、白名单 shell、
  联网检索/正文提取、**浏览器计算机控制**(`browser_navigate/snapshot/click/type/screenshot`,
  见 `browser.py`,守护线程跑 sync Playwright,默认有头可见窗口)、**`mcp_call`**(经 `mcp_native.py`
  连 `~/.argos/mcp.json` 的 MCP server 扩展任意外部工具)、`propose_verify`(独立验证门)、
  `update_plan`(真 TODO 拆解)。
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
