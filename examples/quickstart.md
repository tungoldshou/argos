# Argos 快速体验

## 0. 装好并配 key

```bash
# macOS arm64(一行装)
curl -fsSL https://raw.githubusercontent.com/tungoldshou/argos/main/packaging/install.sh | bash

# 任何平台(从 PyPI)
uv tool install argos-agent
# 或 pip install argos-agent

# 配模型 + key(交互向导)
argos setup
# 选 provider → 填 key → 连通测试 → 保存
```

## 1. 第一次启动 TUI

```bash
argos
```

看到 `✳ LIVE` 状态 + 底部输入框 → 直接输入目标开始。

> ⚠️ 没配 key 时 TUI 会落 demo 态(`⚠ DEMO`),诚实标"无 API key",
> 不会假装能跑。配好 `argos setup` 后自动转 LIVE。

## 2. 看 best_of_n 故事(1 task, < 2min)

```bash
uv run python scripts/best_of_n_demo.py
```

跑一个简单 Python 任务(实现 `fib(n)` 满足 `fib(10)==55`),
N=1(单候选)和 N=3(3 个候选独立 worktree 选最好)各跑一遍。

期望:
- **常见情况**:N=1 失败,N=3 至少 1 个候选成功 → 看到 `🎯 best_of_n 价值显现`
- **简单任务**:N=1 一次就过 → 任务太简单看不出 N 价值,试更难的
- **429 限流**:N=3 候选全失败,error 含 `429 Too Many Requests` → 便宜模型 QPS
  不够(N=3 平行 = 3x 负载),换模型或加 per-candidate 退避(待 ship)

## 3. 跑完整 Terminal-Bench(4-6 task, ≈ 30min)

```bash
# 准备:克隆 TB 任务源(241 task,挑 4-6 个 supported 的)
git clone https://github.com/laude-institute/terminal-bench /tmp/tb-inspect

# 跑(走当前 active profile,即 `argos setup` 配的那个)
uv run python scripts/tb_pass_at_1_benchmark.py --tb-source /tmp/tb-inspect --n 3

# 想用环境变量里的模型(覆盖 active)就加 --use-env-override
uv run python scripts/tb_pass_at_1_benchmark.py --tb-source /tmp/tb-inspect --n 3 --use-env-override
```

输出示例(2026-06-09 实测 M3):
```
[bench] pass@1 (N=1) = 0.0%
[bench] pass@1 (N=3) = 100.0%
[bench] Δ  = +100.0pp
```

**这是产品核心故事**:便宜模型 + best_of_n = 强模型单跑的效果。

## 4. 故障排查

| 现象 | 可能原因 | 修法 |
|---|---|---|
| TUI 起来就是 `⚠ DEMO` | 没配 key | `argos setup` 配;或 export 对应 env var |
| `argos setup` 非交互挂 | stdin 不是 TTY(管道/CI) | 在真终端跑;或手工写 `~/.argos/config.json` + `~/.argos/.env` |
| TB bench 候选一直 hung | 上游模型限流 | 切模型(`argos setup` 选个);或加 bridge per-candidate timeout(待 ship) |
| 任务 verify 一直 unverifiable | 项目无 pytest/无可机检命令 | 让 agent 显式 declare `propose_verify`;或加测试 |
| 打包 .app 跑不了真模型 | Python 改了没重打 PyInstaller | `packaging/build_arm64.sh` 重打 → `tauri build` |

## 5. 进一步

- TUI 命令:输入 `/` 看所有 `/` 命令(setup / context / routing / skills / self-update)
- 配置:`~/.argos/config.json`(声明式)+ `~/.argos/.env`(密钥,0600 权限)
- 文档:`docs/` 下每个大功能一篇
- CHANGELOG:看 `CHANGELOG.md` 的 `[Unreleased]` 段
