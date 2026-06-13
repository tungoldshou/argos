# 打包 C 阶段 — PyPI + Linux/Windows + 全包管理(跨平台)

> Road-map #13 / spec `2026-06-07-packaging-c-design.md` 的用户文档。
> C 阶段把"用啥系统都能装上、升级快、可信源"做成现实,从 macOS arm64 only
> 扩到 6 个 OS 通道。

> **发布状态**: macOS arm64 已发布（v0.1.0）。Linux / Windows / PyPI / Homebrew tap / Nix 通道均为计划中，尚未正式发布。

## 各通道安装命令(按推荐顺序)

### 1. PyPI(任何平台,推荐)

```bash
pip install argos-agent        # 或 uv tool install argos-agent
argos --version                # 验证
```

`pip install` 安装两个入口点：`argos`（主命令）和 `argospkg`（打包辅助工具），均自动进 PATH。

### 2. macOS arm64(已发布 v0.1.0)

```bash
curl -fsSL https://raw.githubusercontent.com/tungoldshou/argos/main/packaging/install.sh | bash
# 或 Homebrew Cask:
brew install --cask -s packaging/homebrew/argos.rb
```

### 3. Linux 3 格式

```bash
# AppImage(主推,跨 glibc)
curl -fsSL https://github.com/tungoldshou/argos/releases/latest/download/Argos-X.Y.Z-x86_64.AppImage -o argos
chmod +x argos && ./argos --version

# .deb(apt 路线;Debian/Ubuntu/Mint)
curl -fsSL https://raw.githubusercontent.com/tungoldshou/argos/main/packaging/install-deb.sh | bash
# 或手动:
sudo dpkg -i argos_X.Y.Z_amd64.deb && sudo apt-get install -f -y

# .rpm(Fedora/RHEL/openSUSE)
sudo dnf install ./argos-X.Y.Z-1.x86_64.rpm   # 或 yum / zypper
```

### 4. Windows

```powershell
# WinGet(主推;待 winget 审核通过)
winget install tungoldshou.argos

# 或直接下 .exe zip
Invoke-WebRequest -Uri "https://github.com/tungoldshou/argos/releases/latest/download/Argos-X.Y.Z-x86_64-windows.zip" -OutFile argos.zip
Expand-Archive argos.zip
.\argos.exe --version
```

### 5. Homebrew tap(Linux CLI / macOS TUI (.app wrapper))

```bash
brew tap tungoldshou/argos
brew install argos           # Linux CLI:AppImage
brew install --cask argos    # macOS TUI (.app wrapper):.app bundle
```

### 6. Nix

```bash
# flake(本期简化版;v1.1 走 nixpkgs 完整版)
nix run github:tungoldshou/argos#argos
# 或:
nix profile install github:tungoldshou/argos#argos
```

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

- **PyPI**:`pip install --upgrade argos-agent` 或 `uv tool upgrade argos-agent`
- **macOS TUI (.app wrapper)**:`brew upgrade --cask argos`,或重跑 `install.sh`
- **Linux AppImage**:重下最新版替换原文件
- **.deb**:`sudo apt-get install --only-upgrade argos-agent`(若装过)
- **WinGet**:`winget upgrade tungoldshou.argos`
- **Nix**:`nix profile upgrade`

`argos self-update`(已存在):启动时 7 天缓存 background check GitHub latest,仅
**提示**新版本不下载;用户主动跑升级。

## 已知限制(spec §1 风险 / §15 风险 + 未来 v1.1)

- **PyPI wheel 不含 `argos-agent` 同名 Linux binary**:wheel 是源码包,装后走 `python -m
  argos.__main__`;Linux 上要单 binary 装用 AppImage/.deb/.rpm/brew。
- **WinGet 审核期**(首次提交到 `microsoft/winget-pkgs` 走审核,几小时-几天):
  期间 `winget install` 装不到,README 标"待审";直接下 .exe zip 兜底。
- **Nix 简化版依赖不全**:`ddgs` / `mlx-embeddings` / `sqlite-vec` / `playwright` /
  `trafilatura` 当前不在 nixpkgs(或在但版本不匹配);本期 flake 只引现成的
  smolagents / textual / httpx / numpy。v1.1 走 `buildPythonPackage` + override 完整化。
- **Code signing / notarize / SmartScreen 跳警**:**全平台 unsigned**(spec §1 风险 6)。
  Windows 上首次跑 .exe 弹 SmartScreen "未知发布者"警告,点"仍要运行"即可。v1.1 接 EV
  cert + Developer ID。
- **macOS x86_64 / Linux aarch64 / Linux musl (Alpine)**:本期不发;v1.1 视用户量决定。
- **apt PPA**:本期无(简化 .deb + install-deb.sh 兜底);PPA 上 Launchpad 复杂度高,
  v1.1 再说。

## CI 端到端

打 `v*` tag → GitHub Actions 走 `release.yml` 3 OS 矩阵:
1. `build-macos`(macos-14)→ 产 `Argos-X.Y.Z-arm64-mac.tar.gz`
2. `build-linux`(ubuntu-24.04)→ 产 AppImage / .deb / .rpm 3 件
3. `build-windows`(windows-latest)→ 产 .exe zip(可选 .msi)
4. `release` job → `gh release create` 一把发出,生成 SHA256SUMS

并行触发:
- `publish.yml` → `pypa/gh-action-pypi-publish@release/v1` 走 OIDC trusted publishing
- `bump-homebrew-formula.yml` → 推 tap 仓(需 `secrets.HOMEBREW_TAP_TOKEN`)
- `bump-winget-manifest.yml` → 同步本仓 `packaging/winget/` 3 件

## 故障排查

| 现象 | 原因 | 修法 |
|---|---|---|
| `winget install tungoldshou.argos` 装不到 | winget 审核未过 | 用 .exe zip 兜底;README 标"待审" |
| `nix run` 缺依赖 | nixpkgs 暂缺 | 用 pip install / brew install / AppImage 兜底 |
| `brew install argos` 报 404 | tap 仓没建好 | `brew tap tungoldshou/argos` 先建 |
| Windows SmartScreen 跳警 | unsigned | 点"仍要运行"(spec §1 风险 6) |
| `dpkg -i` 报依赖缺 | libc / libstdc++ 没装 | `sudo apt-get install -f -y` 修依赖 |
| AppImage 跑不起来 | fuse 缺 | `sudo apt install -y fuse libfuse2` |

## 链接

- Spec:`docs/superpowers/specs/2026-06-07-packaging-c-design.md`
- Plan:`docs/superpowers/plans/2026-06-07-packaging-c.md`
- macOS arm64 v0.1.0 用户文档:`packaging/install.sh` + `packaging/argos.spec` + README
- 上游项目:https://github.com/tungoldshou/argos
