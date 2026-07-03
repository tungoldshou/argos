# Packaging backlog — deferred binary/package-manager channels

> Road-map #13 / spec `2026-06-07-packaging-c-design.md` 的后台记录。
> 首发安装面已收敛到 PyPI / `uv tool` 和 source checkout；本页记录推迟的
> binary/package-manager 工作，不作为公开安装指南。

> **发布状态**: 旧 GitHub `v0.1.0` release/tag 已删除；当前首发目标是
> TestPyPI → PyPI 的 Python package 路径。macOS / Linux / Windows /
> Homebrew tap / WinGet / Nix 均为 deferred backlog。

## 首发安装面

```bash
curl -fsSL https://raw.githubusercontent.com/tungoldshou/argos/v0.1.1/install.sh | bash
```

等价手动命令:

```bash
uv tool install argos-agent    # 或 pip install argos-agent
argos setup
argos
```

如果 `argos` 不在 PATH,先跑 `uv tool update-shell` 并重开 shell。

源码 checkout 仍是贡献者和预发布验证路径:

```bash
git clone https://github.com/tungoldshou/argos
cd argos
uv sync
uv run argos setup
uv run argos
```

## Deferred packaging backlog

These channels are intentionally not launch blockers:

- macOS app tarball and one-line installer
- Linux standalone assets
- Windows standalone assets
- Homebrew tap
- WinGet manifest submission
- Nix flake / nixpkgs work

Keep their scripts and manifests as draft release engineering assets until the
PyPI path is stable and a real user need justifies each additional channel.

## 各通道对应产物(release 资产)

| 资产 | 通道 | 跑在 |
|---|---|---|
| `Argos-X.Y.Z-arm64-mac.tar.gz` | macOS TUI (.app wrapper) | macos-14 (GitHub Actions) |
| `Argos-X.Y.Z-x86_64.AppImage` | Linux AppImage | ubuntu-24.04 |
| `argos_X.Y.Z_amd64.deb` | apt 路线 | ubuntu-24.04 |
| `argos-X.Y.Z-1.x86_64.rpm` | dnf 路线 | ubuntu-24.04(rpmbuild) |
| `Argos-X.Y.Z-x86_64-windows.zip` | Windows 主推 | windows-latest |
| `Argos-X.Y.Z-x86_64.msi.zip` | Windows 可选(简化方案) | windows-latest (WiX) |
| `SHA256SUMS` | 校验 | (3 OS 矩阵统一) |

## 升级

- **PyPI**:发布后 `pip install --upgrade argos-agent` 或 `uv tool upgrade argos-agent`

`argos self-update`(已存在):启动时 7 天缓存 background check GitHub latest,仅
**提示**新版本不下载;用户主动跑升级。

## 已知限制(spec §1 风险 / §15 风险 + 未来 v1.1)

- **PyPI wheel 不含平台原生 binary**:wheel 是 Python 包,装后走 `argos` console script。
- **WinGet / Homebrew / Nix 审核和维护成本**:首次上线不承担这些通道；后续按用户需求逐个开放。
- **Code signing / notarize / SmartScreen 跳警**:**全平台 unsigned**(spec §1 风险 6)。
  二进制分发恢复前不作为公开安装路径。
- **macOS x86_64 / Linux aarch64 / Linux musl (Alpine)**:本期不发;v1.1 视用户量决定。
- **apt PPA**:本期无;PPA 上 Launchpad 复杂度高, v1.1 再说。

## CI 端到端

手动触发 `publish.yml` → 发布到 TestPyPI 预演。
打新的 `v*` tag → `publish.yml` 发布正式 PyPI。

`release.yml` 是手动 binary workflow，等二进制渠道恢复时再触发；不要让它阻塞 PyPI 首发。

## 故障排查

| 现象 | 原因 | 修法 |
|---|---|---|
| package-manager channel unavailable | deferred backlog | Use PyPI/uv tool or source checkout |
| Windows SmartScreen 跳警 | unsigned | 点"仍要运行"(spec §1 风险 6) |

## 链接

- Spec:`docs/superpowers/specs/2026-06-07-packaging-c-design.md`
- Plan:`docs/superpowers/plans/2026-06-07-packaging-c.md`
- Draft binary packaging scripts:`packaging/`
- 上游项目:https://github.com/tungoldshou/argos
