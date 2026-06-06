# nixpkgs PR — 添加 argos-agent

## 摘要

将 [Argos](https://github.com/tungoldshou/argos) 加入 nixpkgs,作为
`pkgs/by-name/ar/argos-agent/default.nix`。

Argos 是一款自建 CodeAct loop 的 TUI 终端编码智能体,带 verify 硬门禁 + 诚实协议 + OS
沙箱。Python 3.12+ 即可跑。

## 测试

```bash
nix-build -A argos-agent           # 编译 + 装到 nix-store
nix-shell -p argos-agent --run "argos --version"   # 跑命令
nix-shell -p argos-agent --run "argos --selftest"  # 端到端 selftest
nix run nixpkgs#argos-agent        # 直接跑
```

## 已知 issue(本 PR 范围内)

- **依赖覆盖不全**:`ddgs` / `mlx-embeddings` / `sqlite-vec` / `playwright` /
  `trafilatura` 当前不在 nixpkgs(或在但版本不匹配)。本期 PR 用
  `buildPythonApplication` 简化版只引现成的 `smolagents` / `textual` / `httpx` / `numpy`。
  后续跟 nixpkgs reviewer 讨论走 `override` 或在 `pkgs/by-name/ar/argos-agent/` 加
  自建包。
- **MLX**:macOS-only 加速,Linux 不可用,不影响 nixpkgs x86_64-linux。
- **Smoke test**:`argos --selftest` 在 macOS 真 Seatbelt 沙箱跑;Linux 上
  `SeatbeltExecutor.spawn` 会失败但 catch 返 1(诚实失败,不假绿)。

## 提交

- 路径:`pkgs/by-name/ar/argos-agent/`
- 必含 3 件:
  - `default.nix`(本仓 `flake.nix` 的简化版,无 flake 输入)
  - `python.pkgs.txt` 或类似(在 `pkgs/development/python-modules/argos-agent/`)
  - 顶层 `pkgs/top-level/python-packages.nix` 加 `argos-agent = callPackage ../development/python-modules/argos-agent { };`

## 链接

- 仓库:https://github.com/tungoldshou/argos
- 规格:https://github.com/tungoldshou/argos/blob/main/docs/superpowers/specs/2026-06-07-packaging-c-design.md
- 用户文档:https://github.com/tungoldshou/argos/blob/main/docs/packaging-c.md
