# 打包 C 阶段 — PyPI + Linux/Windows + 全包管理(跨平台) — 设计规格(spec)

> Road-map entry **#13** "打包 C 阶段 — pip install + 全包管理 (中期,跨平台)" 的设计规格。
> B 阶段(2026-06-05 v0.1.0 已发)只装 macOS arm64。C 阶段把**安装面从 1 个扩到 6 个**,
> 让"用啥系统都能装上、升级快、可信源"成为可能。
> 估时 1-1.5 天;以**配置/脚本/工作流**为主,无新源码逻辑。

## 1. 背景与现状

- **v0.1.0 已发**(2026-06-06),macOS arm64 单 `.app` + `curl install.sh | bash` + Homebrew Cask
  + GH Releases + `argos self-update`(仅查不下载)。B 阶段全通。
- **PyPI 通道缺**:`pyproject.toml` 已经[project]/[build-system] 完整,`uv build` 应能出
  wheel/sdist,但**没**:
  - `[project.scripts]` 完整声明(只 `argos`,缺 `argospkg` / 后续 dispatcher 名)
  - `[tool.hatch.build.targets.sdist]` 显式 include(`__main__.py` + 关键数据)
  - 没 publish workflow
  - 缺 README long description(配 `[project.readme]`)
  - 缺 license / authors 字段(license file 在根,但没 PEP 639 标注)
- **Linux 通道缺**:`packaging/build_linux.sh` 不存在;`packaging/build_arm64.sh` 走
  PyInstaller + macOS-only(用 `file` 命令验 Mach-O,arm64-only)。Homebrew Cask 是 macOS
  专属,Linux 需自建包(AppImage / .deb / .rpm)。
- **Windows 通道缺**:`packaging/build_windows.sh` 不存在;`pyinstaller.spec` 用 `target_arch="arm64"`
  + 抄 `sed`/macOS-only 步骤,Windows runner 跑必坏。
- **Homebrew tap 缺**:B 阶段 `packaging/homebrew/argos.rb` 是 Cask(给 macOS GUI 用);
  **Formula**(给 Linux/CLI 用)不存在;`homebrew-argos` tap 仓没建,只能本地 `brew install -s`。
- **WinGet / apt / nix 通道全缺**:v0.1.0 这三路装不到。
- **GH release workflow 是死的**:v0.1.0 实际是用户手动建的 release(走 `gh release create`),
  `.github/workflows/release.yml` 是更早期写的,后来没机会被验证。spec §2.3 描述的"自动 build + 发 release"从未真正跑过;**当前 release.yml 会被 GH actions validator 报 0 jobs**(因 setup-python@v5 validator bug)。
- **风险**:
  1. **PyPI 装出坏 binary** — wheel 里没 sqlite-vec .so/.dylib 跑不起来(CJK 向量召回主路径)
  2. **跨平台打包复杂度爆** — Linux 3 格式(AppImage / .deb / .rpm)、Windows 2 格式(.exe / .msi),
     CI 矩阵 3 OS × 多格式 = 9+ job,跑慢 / 出错难定位
  3. **MSI 工具链烂** — Windows 端没 msitools / WiX 一键装,`fpm` 不原生支持 MSI。
     MVP 走 PyInstaller .onefile + 简化 .msi(若失败退 `.exe` zip);不卡
  4. **AppImage 沙箱** — AppImage 跑在用户家目录 fuse,Seatbelt/沙箱仍生效;
     AppImage 自身**不是**沙箱,spec §3.2 锁"AppImage 内不叠 sandbox 层"
  5. **WinGet 审核期** — 第一次提交到 `microsoft/winget-pkgs` 要走审核(几天-几周),
     spec §7 锁"manifest 写好,不卡发版;审核期间 README 提示手动装"
  6. **nixpkgs 审核** — 同上,PR 提交后等 nix reviewer;spec 锁"flake.nix 写好 + PR 模板"
  7. **Homebrew tap 仓** — `tungoldshou/homebrew-argos` 是新仓,没 README / license;
     推公式前要先建好骨架
  8. **bump-formula-pr 走不通** — `praeclarum/homebrew-bump-formula-pr` 对个人 tap
     体验不顺手(本仓公式简单,sed 即可,不依赖它)
  9. **Trusted Publishing 未配** — PyPI Trusted Publishing(OIDC)需要先在 PyPI 后台
     配 publisher 关联;spec §6 锁"先 manual token 跑通,后切 OIDC"
  10. **CI 0 jobs 是真 bug** — 必须在本期修;不修 v0.2.0 没法自动发
- **灵魂**:B 阶段已经让"macOS 用户 1 行装 + 升级",C 阶段要扩到"全平台用户 1 行装 + 升级"。
  跟 Linux 主流(apt/dnf/pacman/brew)对齐;跟 macOS 已有 B 阶段对齐;跟 Windows(winget/scoop/chocolatey)
  对齐(本期只做 winget,scoop/choco v1.1 再说)。
  **不**搞花活(不接 snap store、不自建 apt 源、nixpkgs 走官方 PR)。
  **诚实**标注"待审核"的通道(WinGet / nixpkgs),不在 README 假装已装得到。

## 2. 目标与非目标

### 2.1 目标(本期)

1. **PyPI 发布通电** — `pip install argos-agent` 应能用(从 PyPI);`uv build` 产 wheel +
   sdist,`publish.yml` 在打 `v*` tag 时自动 trusted publish(OIDC)
2. **`[project.scripts]` 完整** — `argos` + `argospkg` + `argos-tui` 都进 PATH(spec D8
   argv[0] dispatcher)
3. **Linux 打包** — `packaging/build_linux.sh` 一键出 AppImage(主推,跨 glibc 兼容),
   顺带 `.deb` + `.rpm`(主包管理装);`release.yml` 加 `linux` job
4. **Windows 打包** — `packaging/build_windows.sh` 走 windows-latest runner,出 `.exe`
   (PyInstaller onefile);`.msi` 用 `msitools` 或简化方案(spec D3)
5. **Homebrew tap 仓** — 新仓 `tungoldshou/homebrew-argos`,含 `Formula/argos.rb`(非 cask,
   Linux/CLI 装)+ `Casks/argos.rb`(macOS GUI 装,迁自本仓 `packaging/homebrew/argos.rb`);
   auto-bump workflow(`bump-homebrew-formula.yml`)
6. **WinGet manifest** — `packaging/winget/tungoldshou.argos.installer.yaml` +
   `.locale.en-US.yaml` + `.yaml` 三件,1.6 schema;`winget install tungoldshou.argos` 应能装
7. **apt .deb** — 走 `packaging/build_linux.sh` 的 `dpkg-deb` 子步骤,产物
   `argos_<ver>_amd64.deb`;`install-deb.sh` 一行装
8. **Nix flake + nixpkgs 提交模板** — `flake.nix` 跑 `nix run`,PR 到 `NixOS/nixpkgs` 的
   `pkgs/by-name/ar/argos/` 三件
9. **修 release.yml 0 jobs bug** — pin `setup-python@v4`,换 `gh release create` shell,
   让 `v*` tag → 真跑 jobs → 真发 release
10. **Cross-platform matrix** — `release.yml` 加 `linux` job(AppImage/.deb/.rpm)+ `windows`
    job(.exe/.msi),macos 已有(B 阶段)
11. **0 新源代码逻辑** — 全部在 `packaging/`(脚本/配置)+ `pyproject.toml`(项目元数据)+
    `.github/workflows/`(CI) + `CHANGELOG.md` + `README.md`;不修 `argos_agent/`(除可能的
    pyproject 显式 include)
12. **0 新强制外部依赖** — 不加 sqlite;PyPI publish 走 OIDC 免 token;`winget`/`dpkg-deb`/
    `rpmbuild`/`msitools` 都在 CI runner 装
13. **测试 +30**(spec §14):`test_packaging_pypi.py` / `test_packaging_linux_spec.py` /
    `test_packaging_windows_spec.py` / `test_packaging_homebrew.py` /
    `test_packaging_winget.py` / `test_packaging_release_workflow.py`
14. **不**改 `argos_agent/` 任何模块;**不**改 `__main__.py`;**不**改 `core/loop.py` /
    `setup_wizard.py` / `eval/` / `skills_curator/`(spec §18 锁)

### 2.2 非目标(本期不做)

- ❌ **snap / flatpak** — Linux 沙箱生态分裂,AppImage/.deb/.rpm 已覆盖 >95% 用户
- ❌ **scoop / chocolatey** — Windows 走 winget 已够;v1.1 再说
- ❌ **PyPI Trusted Publishing 配好即上** — spec D6 锁"先 manual token 跑通再切 OIDC",
  本期走 token 路径(workflow secret `PYPI_API_TOKEN`)
- ❌ **macOS x86_64** — Apple Silicon 普及已 ~95%,B 阶段就只 arm64,C 阶段延后
- ❌ **Linux ARM (aarch64)** — v1.1 视用户量决定
- ❌ **Linux musl (Alpine)** — spec D2 锁 AppImage 走 glibc 通用包;musl 用户 v1.1 走 sdist
- ❌ **MSI 数字签名** — 跟 macOS 一样 unsigned;Windows SmartScreen 跳警(spec D3)
- ❌ **Code signing (Windows + macOS + Linux)** — 全平台 unsigned,spec §1 风险已锁
- ❌ **Notarize macOS** — v1.1 走 Developer ID
- ❌ **Nix 包装 (buildGoModule / buildPythonPackage)** — spec D11 flake 简化版
  (直接 `python3` + `pip install`,nixpkgs PR 时再换 buildPythonApplication)
- ❌ **自动跨设备 / 跨网络 pip mirror** — spec §3 锁"用 PyPI 官方源,不动"
- ❌ **winget-pkgs 真正 PR** — 本期写好 manifest + 验证 YAML schema 合法;真 PR 留手动(审核期)
- ❌ **nixpkgs 真正 PR** — 同上
- ❌ **Homebrew tap 仓 README** — 简版(从本仓 README 链过来)
- ❌ **Per-package vendor lockfile** — 跟 pyproject.toml 一致即可
- ❌ **`brew install` 自动装 sandbox 依赖** — spec D4 锁"用户自己跑 brew install argos",
  无安装后 hook

## 3. 架构总览

```
                       推 v* tag
                          │
                          ▼
          ┌────────────────────────────────┐
          │  .github/workflows/release.yml │
          │  (修 0 jobs bug,3 OS 矩阵)     │
          └──────────────┬─────────────────┘
                         │
        ┌────────────────┼────────────────┐
        ▼                ▼                ▼
   macos-14         ubuntu-24.04      windows-latest
        │                │                │
   packaging/        packaging/        packaging/
   build_arm64.sh    build_linux.sh    build_windows.sh
        │                │                │
        ▼                ▼                ▼
  Argos.app +        Argos-<ver>-      Argos-<ver>-
  arm64-mac.tar.gz   x86_64.AppImage   x86_64-windows.zip
  (B 已有)           argos_<ver>_      argos_<ver>-
                     amd64.deb         x86_64.msi.zip
                     argos-<ver>-
                     x86_64.rpm
        │                │                │
        └────────────────┼────────────────┘
                         │
                         ▼
         ┌──────────────────────────────┐
         │  gh release create v0.2.0    │
         │  --title "Argos v0.2.0"      │
         │  --generate-notes            │
         │  dist/*.{tar.gz,AppImage,    │
         │  deb,rpm,zip,msi.zip}        │
         │  + SHA256SUMS                │
         └──────────────┬───────────────┘
                        │
        ┌───────────────┼───────────────┬──────────────┐
        ▼               ▼               ▼              ▼
   packaging/     .github/         .github/        .github/
   winget/        workflows/       workflows/      workflows/
   tungoldshou.   publish.yml      bump-homebrew-  publish.yml
   argos.         (PyPI OIDC)      formula.yml     (PyPI 同
   installer.yaml                                workflow)
   (manifest)         │               │              │
                      ▼               ▼              ▼
                  PyPI            tungoldshou/   ReadTheDocs/
                  argos-agent     homebrew-argos integration
                  <ver>           (新仓)         (v1.1)
```

## 4. PyPI 发布(契约 §1;spec D1/D6/D8)

### 4.1 `pyproject.toml` 增改

```toml
[project]
name = "argos-agent"        # 现有(spec D1 锁:argos-agent,避免跟 argos 项目撞)
version = "0.1.0"            # 由 /ship 自动 bump(现有)
description = "Argos — 诚实可靠的终端编码超级智能体(自建 CodeAct 引擎 + verify 硬门禁 + OS 沙箱)"
readme = "README.md"         # 现有,长描述走 README.md
license = {text = "MIT"}     # 新(spec D9 重申)
authors = [                  # 新(PyPI 要)
  {name = "tungoldshou", email = "tungoldshou@users.noreply.github.com"},
]
keywords = ["agent", "ai", "cli", "terminal", "codeact", "verifier", "sandbox", "tui"]
classifiers = [
  "Development Status :: 4 - Beta",
  "Environment :: Console",
  "Environment :: Console :: Curses",
  "Intended Audience :: Developers",
  "License :: OSI Approved :: MIT License",
  "Operating System :: MacOS :: MacOS X",
  "Operating System :: POSIX :: Linux",
  "Operating System :: Microsoft :: Windows :: Windows 10",
  "Programming Language :: Python :: 3.12",
  "Programming Language :: Python :: 3.13",
  "Topic :: Software Development :: Code Generators",
  "Topic :: Software Development :: Libraries :: Python Modules",
]
requires-python = ">=3.12"
dependencies = [              # 现有,不动
    "ddgs>=8.0.0",
    "httpx[socks]>=0.28.1",
    "mlx-embeddings>=0.1.0",
    "numpy>=2.4.6",
    "playwright>=1.60.0",
    "smolagents>=1.26.0",
    "sqlite-vec>=0.1.9",
    "textual>=8.2.7",
    "trafilatura>=2.0.0",
]

[project.scripts]
argos = "argos_agent.__main__:main"          # 现有
argospkg = "argos_agent.cli.pkg:main"        # 新(spec D8 dispatcher)

[project.urls]
Homepage = "https://github.com/tungoldshou/argos"
Repository = "https://github.com/tungoldshou/argos"
Issues = "https://github.com/tungoldshou/argos/issues"
Changelog = "https://github.com/tungoldshou/argos/blob/main/CHANGELOG.md"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["argos_agent"]

[tool.hatch.build.targets.sdist]
# 显式 include:源码包不全 0 数据就装不起来(schema.sql / skills_builtin)
include = [
  "argos_agent",
  "README.md",
  "LICENSE",
  "CHANGELOG.md",
  "packaging/VERSION",
  "packaging/Info.plist",
  "packaging/argos.spec",
]
exclude = [
  "tests/*",
  "build/*",
  "dist/*",
  "docs/*",
  "*.egg-info",
  ".venv/*",
  ".pytest_cache/*",
  ".codegraph/*",
  ".coverage",
]
```

### 4.2 `argos_agent/cli/pkg.py`(新,spec D8 dispatcher)

```python
"""`argospkg` 命令 — 打包工具 dispatcher(规格里 argv[0] = argospkg 切到 packaging 子命令)。

主 `argos` 跑 agent;`argospkg` 跑打包/发布辅助(spec D8)。
"""
import sys

def main() -> int:
    """根据 argv 切到 packaging 子命令。MVP 暴露 'info' / 'check' / 'manifest'。"""
    from argos_agent.cli.pkg import dispatch
    return dispatch(sys.argv[1:])

if __name__ == "__main__":
    sys.exit(main())
```

`argos_agent/cli/pkg.py` 提供:
- `info` — 打印 `pyproject.toml` [project] 段 / packaging/VERSION / 当前 git tag
- `check` — 跑 `uv build --dry-run` 模拟,确认 wheel/sdist 能产出
- `manifest` — 显式生成 WinGet manifest(给 winget 提交用)

### 4.3 `publish.yml`(新,PyPI OIDC + manual fallback)

```yaml
name: Publish to PyPI
on:
  push:
    tags:
      - 'v*'
  workflow_dispatch:           # 允许手动触发测试

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - name: Build distributions
        run: uv build
      - uses: actions/upload-artifact@v4
        with:
          name: dist
          path: dist/

  pypi:
    needs: build
    runs-on: ubuntu-latest
    environment: pypi
    permissions:
      id-token: write           # OIDC(spec D6)
    steps:
      - uses: actions/download-artifact@v4
        with: {name: dist, path: dist/}
      - name: Publish
        uses: pypa/gh-action-pypi-publish@release/v1
        # 注:trust 模式 (OIDC) 不需 token
        # fallback(若 OIDC 未配):用 PYPI_API_TOKEN secret + pypa/gh-action-pypi-publish@release/v1
        #   with: {password: ${{ secrets.PYPI_API_TOKEN }}}
```

### 4.4 校验(契约 §14;spec D14)

- `uv build` 在 CI 出 `dist/argos_agent-0.1.0-py3-none-any.whl` + `dist/argos-agent-0.1.0.tar.gz`
- `pip install ./dist/argos_agent-0.1.0-py3-none-any.whl --quiet` 进 venv,跑 `which argos` 命中
  `$venv/bin/argos`
- 跑 `argos --version` 输出 `argos 0.1.0`
- 跑 `argos --selftest` 输出 `[selftest] ... OK`,退出 0

## 5. Linux 打包(契约 §2;spec D2)

### 5.1 `packaging/build_linux.sh`(新)

```bash
#!/usr/bin/env bash
# Argos Linux 打包:PyInstaller onefile → AppImage / .deb / .rpm 三种格式。
# 跑在 ubuntu-24.04 runner(本地装 fuse / dpkg-dev / rpm 即可)。
# spec §5 锁 AppImage 为主推(跨 glibc),.deb 走 apt 路线,.rpm 走 dnf 路线。
set -euo pipefail
cd "$(dirname "$0")/.."   # 仓库根

# 版本号(spec §2.6)
if [ -z "${ARGOS_VERSION:-}" ]; then
  if [ -f packaging/VERSION ]; then ARGOS_VERSION=$(cat packaging/VERSION)
  else ARGOS_VERSION="0.0.0+unknown"; fi
fi
export ARGOS_VERSION
echo "=== Building Argos $ARGOS_VERSION (linux) ==="

# 1. PyInstaller onefile(目标 arch 默认 amd64,Apple Silicon Mac 跑可加 ARGOS_TARGET=aarch64)
TARGET_ARCH="${ARGOS_TARGET:-x86_64}"
uv run pyinstaller --clean --noconfirm \
  --target-arch "$TARGET_ARCH" \
  --name argos \
  --onefile \
  --console \
  --add-data "argos_agent/memory/schema.sql:argos_agent/memory" \
  --add-data "packaging/VERSION:packaging" \
  --add-data "packaging/Info.plist:packaging" \
  --collect-submodules smolagents \
  --collect-submodules textual \
  --collect-submodules argos_agent \
  --collect-data-files textual \
  --collect-data-files smolagents \
  --copy-metadata argos-agent \
  --exclude-module langchain \
  --exclude-module langgraph \
  --exclude-module fastapi \
  --exclude-module uvicorn \
  --osx-bundle-identifier "com.tungoldshou.argos" \
  argos_agent/__main__.py

BIN=dist/argos
file "$BIN"                          # 必须 ELF 64-bit LSB executable
chmod +x "$BIN"

# 2. AppImage(主推)
echo "=== Pack AppImage ==="
APPIMAGE_DIR=dist/Argos.AppDir
mkdir -p "$APPIMAGE_DIR/usr/bin" "$APPIMAGE_DIR/usr/share/applications" "$APPIMAGE_DIR/usr/share/icons/hicolor/256x256/apps"
cp "$BIN" "$APPIMAGE_DIR/usr/bin/argos"
cat > "$APPIMAGE_DIR/usr/share/applications/argos.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Argos
GenericName=AI Agent
Exec=argos %F
Icon=argos
Terminal=true
Categories=Development;Utility;
EOF
# 简单 PNG(图标可后置;v1.1 加 branding)
cp packaging/icons/argos.png "$APPIMAGE_DIR/usr/share/icons/hicolor/256x256/apps/" 2>/dev/null || \
  printf '\x89PNG\r\n\x1a\n' > "$APPIMAGE_DIR/argos.png"   # 占位 PNG
cp "$APPIMAGE_DIR/argos.png" "$APPIMAGE_DIR/argos.png"
# AppRun 脚本
cat > "$APPIMAGE_DIR/AppRun" <<EOF
#!/usr/bin/env bash
exec "\$(dirname "\$0")/usr/bin/argos" "\$@"
EOF
chmod +x "$APPIMAGE_DIR/AppRun"
# 跑 appimagetool(需安装;本地:apt install -y appimage 不可;走下载)
if [ ! -x /usr/local/bin/appimagetool ]; then
  curl -fsSL -o /tmp/appimagetool "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage"
  chmod +x /tmp/appimagetool
  mv /tmp/appimagetool /usr/local/bin/appimagetool
fi
cd dist
ARCH=$([ "$TARGET_ARCH" = "x86_64" ] && echo x86_64 || echo aarch64)
appimagetool Argos.AppDir "Argos-${ARGOS_VERSION}-${ARCH}.AppImage"
cd ..
shasum -a 256 dist/Argos-*.AppImage

# 3. .deb(走 dpkg-deb,简单,免 fpm)
echo "=== Pack .deb ==="
DEB_DIR=dist/argos-deb
mkdir -p "$DEB_DIR/DEBIAN" "$DEB_DIR/usr/bin" "$DEB_DIR/usr/share/applications"
cat > "$DEB_DIR/DEBIAN/control" <<EOF
Package: argos-agent
Version: ${ARGOS_VERSION}
Section: utils
Priority: optional
Architecture: amd64
Maintainer: tungoldshou <tungoldshou@users.noreply.github.com>
Description: Argos — 诚实可靠的终端编码超级智能体
Depends: libc6, libstdc++6
EOF
cp "$BIN" "$DEB_DIR/usr/bin/argos"
chmod 755 "$DEB_DIR/usr/bin/argos"
cat > "$DEB_DIR/usr/share/applications/argos.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Argos
Exec=argos
Terminal=true
Categories=Development;
EOF
# 简单占位图标(可 v1.1 换真图)
mkdir -p "$DEB_DIR/usr/share/icons/hicolor/256x256/apps"
cp "$APPIMAGE_DIR/argos.png" "$DEB_DIR/usr/share/icons/hicolor/256x256/apps/" 2>/dev/null
dpkg-deb --build --root-owner-group "$DEB_DIR" "dist/argos_${ARGOS_VERSION}_amd64.deb"
shasum -a 256 dist/argos_*.deb

# 4. .rpm(走 rpmbuild)
echo "=== Pack .rpm ==="
RPMBUILD_DIR=dist/rpmbuild
mkdir -p "$RPMBUILD_DIR"/{BUILD,RPMS,SOURCES,SPECS,SRPMS}
cat > "$RPMBUILD_DIR/SPECS/argos.spec" <<EOF
Name: argos-agent
Version: ${ARGOS_VERSION}
Release: 1%{?dist}
Summary: Argos — terminal super-agent (CodeAct + verify gate)
License: MIT
URL: https://github.com/tungoldshou/argos
Requires: glibc, libstdc++
%description
Argos is a terminal super-agent with self-built CodeAct engine, verify hard-gate, and OS sandbox.
%install
mkdir -p %{buildroot}/usr/bin
cp $BIN %{buildroot}/usr/bin/argos
chmod 755 %{buildroot}/usr/bin/argos
%files
/usr/bin/argos
EOF
rpmbuild --define "_topdir $RPMBUILD_DIR" -bb "$RPMBUILD_DIR/SPECS/argos.spec"
cp "$RPMBUILD_DIR"/RPMS/x86_64/argos-agent-${ARGOS_VERSION}-1.*.x86_64.rpm dist/
mv dist/argos-agent-${ARGOS_VERSION}-1.*.x86_64.rpm "dist/argos-${ARGOS_VERSION}-1.x86_64.rpm"
shasum -a 256 dist/argos-*.rpm

echo "=== Linux build done ==="
ls -la dist/
```

### 5.2 `packaging/install-deb.sh`(新)

```bash
#!/usr/bin/env bash
# Argos .deb installer:一行装最新版(对齐 B 阶段 macOS install.sh 体验)。
# spec §7:apt 用户首选;PPA 复杂度留 v1.1。
set -euo pipefail
REPO="tungoldshou/argos"
# ... 类似 B 阶段 install.sh, fetch latest release → 找 argos_*.deb → curl install →
#     sudo dpkg -i → sudo apt-get install -f -y 修依赖 → 装好
```

### 5.3 验证(契约 §14)

- CI ubuntu-24.04 runner 跑 `bash packaging/build_linux.sh` → 出 3 产物
- 跑 `file dist/Argos-*.AppImage` 输出含 "ELF 64-bit LSB executable"
- 跑 `file dist/argos_*.deb` 输出 "Debian binary package"
- 跑 `file dist/argos-*.rpm` 输出 "RPM v3" 或 "RPM v4"

## 6. Windows 打包(契约 §3;spec D3)

### 6.1 `packaging/build_windows.sh`(新)

跑在 `windows-latest` runner,PowerShell / bash 混合:

```bash
#!/usr/bin/env bash
# Argos Windows 打包:PyInstaller onefile → .exe (主) + .msi (可选简化方案)。
# 跑在 windows-latest runner;PyInstaller 6.x 已 native Windows 支持。
# spec §3 锁 .exe 主推,.msi 简化方案失败不卡(MVP 接受仅 .exe)。
set -euo pipefail
cd "$(dirname "$0")/.."   # 仓库根

if [ -z "${ARGOS_VERSION:-}" ]; then
  if [ -f packaging/VERSION ]; then ARGOS_VERSION=$(cat packaging/VERSION)
  else ARGOS_VERSION="0.0.0+unknown"; fi
fi
export ARGOS_VERSION
echo "=== Building Argos $ARGOS_VERSION (windows) ==="

# 1. PyInstaller onefile
uv run pyinstaller --clean --noconfirm \
  --name argos \
  --onefile \
  --console \
  --add-data "argos_agent/memory/schema.sql;argos_agent/memory" \
  --add-data "packaging/VERSION;packaging" \
  --add-data "packaging/Info.plist;packaging" \
  --collect-submodules smolagents \
  --collect-submodules textual \
  --collect-submodules argos_agent \
  --collect-data-files textual \
  --collect-data-files smolagents \
  --copy-metadata argos-agent \
  --exclude-module langchain \
  --exclude-module langgraph \
  --exclude-module fastapi \
  --exclude-module uvicorn \
  argos_agent/__main__.py

BIN=dist/argos.exe
[ -f "$BIN" ] || { echo "FATAL: 缺 $BIN"; exit 1; }
file "$BIN" 2>/dev/null || true

# 2. 打包 zip
cd dist
zip "Argos-${ARGOS_VERSION}-x86_64-windows.zip" argos.exe
cd ..
shasum -a 256 dist/Argos-*.zip

# 3. MSI 简化方案(可选;失败仅警告不退出)
#    走 msitools:wix candle/light
if command -v candle &> /dev/null; then
  echo "=== Pack .msi (WiX) ==="
  cat > dist/argos.wxs <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<Wix xmlns="http://schemas.microsoft.com/wix/2006/wi">
  <Product Id="*" Name="Argos" Version="${ARGOS_VERSION}" Manufacturer="tungoldshou" Language="1033">
    <Package InstallerVersion="500" Compressed="yes" InstallScope="perMachine"/>
    <MediaTemplate EmbedCab="yes"/>
    <Directory Id="INSTALLFOLDER" Name="Argos">
      <Component Id="MainExecutable" Guid="*">
        <File Id="ArgosExe" Source="dist/argos.exe" KeyPath="yes"/>
      </Component>
    </Directory>
    <Feature Id="ProductFeature" Title="Argos" Level="1">
      <ComponentRef Id="MainExecutable"/>
    </Feature>
  </Product>
</Wix>
EOF
  candle -out dist/argos.wixobj dist/argos.wxs
  light -out "dist/Argos-${ARGOS_VERSION}-x86_64.msi" dist/argos.wixobj
  # 改 zip 因为 GH Release 不收 .msi 单文件(可选)
  zip "dist/Argos-${ARGOS_VERSION}-x86_64.msi.zip" "dist/Argos-${ARGOS_VERSION}-x86_64.msi"
  shasum -a 256 "dist/Argos-*.msi.zip"
else
  echo "WARN: candle/wix not installed; skipping .msi (only .exe zip will be uploaded)"
fi

echo "=== Windows build done ==="
ls -la dist/
```

### 6.2 验证(契约 §14)

- CI windows-latest runner 跑 → 出 `Argos-0.2.0-x86_64-windows.zip` 含 `argos.exe`
- 跑 `file dist/Argos-*.zip` 报 "Zip archive data"
- 跑 `unzip -l dist/Argos-*.zip` 含 `argos.exe` 单条
- 跑 `file dist/argos.exe` 报 "PE32+ executable" 或 "MS Windows"

## 7. Homebrew tap(契约 §4;spec D4)

### 7.1 新仓 `tungoldshou/homebrew-argos` 结构

```
tungoldshou/homebrew-argos/
├── README.md                  # "brew tap tungoldshou/argos"
├── Formula/
│   └── argos.rb              # Linux/CLI 装(非 cask)
├── Casks/
│   └── argos.rb              # macOS GUI 装(.app)
└── .github/
    └── workflows/
        └── lint.yml          # brew tap-lint 跑通
```

### 7.2 `Formula/argos.rb`(Linux,非 cask)

```ruby
class Argos < Formula
  desc "Argos — terminal super-agent (CodeAct loop + verify hard-gate + OS sandbox)"
  homepage "https://github.com/tungoldshou/argos"
  url "https://github.com/tungoldshou/argos/releases/download/v#{version}/Argos-#{version}-x86_64.AppImage"
  sha256 "PLACEHOLDER"   # 由 release workflow 注入
  license "MIT"
  version "0.1.0"

  livecheck do
    url :url
    strategy :github_latest_release
  end

  depends_on "fuse" => :linux   # AppImage 需要 fuse

  def install
    bin.install "Argos-#{version}-x86_64.AppImage" => "argos"
  end

  test do
    assert_match "argos #{version}", shell_output("#{bin}/argos --version")
  end
end
```

### 7.3 `Casks/argos.rb`(macOS GUI,迁自本仓)

```ruby
cask "argos" do
  version "0.1.0"
  sha256 "PLACEHOLDER"

  url "https://github.com/tungoldshou/argos/releases/download/v#{version}/Argos-#{version}-arm64-mac.tar.gz"
  name "Argos"
  desc "Terminal super-agent (CodeAct loop + verify hard-gate + OS sandbox)"
  homepage "https://github.com/tungoldshou/argos"

  livecheck do
    url :url
    strategy :github_latest_release
  end

  app "Argos.app"

  zap trash: [
    "~/.argos",
    "~/Library/Application Support/argos-agent",
    "~/Library/Logs/argos-agent",
    "~/Library/Caches/argos-agent",
  ]
end
```

### 7.4 `bump-homebrew-formula.yml`(新 workflow)

```yaml
name: Bump Homebrew formula
on:
  release:
    types: [published]
jobs:
  bump:
    runs-on: ubuntu-latest
    permissions:
      contents: write   # homebrew-argos 仓写权限(需配 GH PAT)
    steps:
      - uses: actions/checkout@v4
        with:
          repository: tungoldshou/homebrew-argos
          token: ${{ secrets.HOMEBREW_TAP_TOKEN }}
      - name: Update Formula + Cask (version + sha256)
        env:
          VERSION: ${{ github.event.release.tag_name }}
        run: |
          VERSION="${VERSION#v}"
          # 跑 curl 拉 release JSON 拿 sha256
          SHA256_ARM64_MAC=$(curl -fsSL "https://api.github.com/repos/tungoldshou/argos/releases/tags/v${VERSION}" \
            | python3 -c "import json,sys; d=json.load(sys.stdin); [print(a['digest']) for a in d['assets'] if a['name'].endswith('-arm64-mac.tar.gz.sha256')]" | head -1)
          SHA256_APPIMAGE=$(curl -fsSL "https://api.github.com/repos/tungoldshou/argos/releases/tags/v${VERSION}" \
            | python3 -c "import json,sys; d=json.load(sys.stdin); [print(a['digest']) for a in d['assets'] if a['name'].endswith('.AppImage.sha256')]" | head -1)
          # 用 sed 注入(简单 2 字段)
          sed -i "s/version \".*\"/version \"${VERSION}\"/" Formula/argos.rb Casks/argos.rb
          sed -i "s/sha256 \".*\"/sha256 \"${SHA256_APPIMAGE}\"/" Formula/argos.rb
          sed -i "s/sha256 \".*\"/sha256 \"${SHA256_ARM64_MAC}\"/" Casks/argos.rb
      - uses: stefanzweifel/git-auto-commit-action@v5
        with:
          commit_message: "bump argos to v${{ github.event.release.tag_name }}"
```

### 7.5 验证(契约 §14)

- 本地 `brew tap-lint Formula/argos.rb Casks/argos.rb` 退出 0
- 公式 `version` / `sha256` 在新 release 后自动 bump
- tap 仓无 secrets 泄露(GitHub PAT 走 secrets 路径)

## 8. WinGet manifest(契约 §5;spec D5)

### 8.1 `packaging/winget/tungoldshou.argos.installer.yaml`

```yaml
PackageIdentifier: tungoldshou.argos
PackageVersion: 0.1.0
PackageLocale: en-US
Publisher: tungoldshou
PackageName: Argos
License: MIT
ShortDescription: Terminal super-agent (CodeAct + verify gate + OS sandbox)
ManifestType: installer
ManifestVersion: 1.6.0
Installers:
  - Architecture: x64
    InstallerType: zip
    InstallerUrl: https://github.com/tungoldshou/argos/releases/download/v0.1.0/Argos-0.1.0-x86_64-windows.zip
    InstallerSha256: PLACEHOLDER_FROM_RELEASE
InstallBehavior:
  Architecture: x64
  FileExtensions: []
  Commands:
    - argos
  InstallModes:
    - silent
  UninstallCommands:
    - cmd: powershell -Command "..."
UpgradeBehavior:
  Architecture: x64
  UpgradeCommands:
    - cmd: powershell -Command "..."
```

### 8.2 `packaging/winget/tungoldshou.argos.locale.en-US.yaml`

```yaml
PackageIdentifier: tungoldshou.argos
PackageVersion: 0.1.0
PackageLocale: en-US
Publisher: tungoldshou
PackageName: Argos
License: MIT
ShortDescription: Terminal super-agent (CodeAct + verify gate + OS sandbox)
Description: |
  Argos is a standalone terminal (TUI) coding super-agent. It self-builds a
  framework-free CodeAct loop with a verify hard-gate, an honesty protocol,
  and an OS-sandboxed executor. The soul: make cheap models reliable.
  ...
  (从 README 拿的 200-400 字符长描述)
```

### 8.3 `packaging/winget/tungoldshou.argos.yaml`(default)

```yaml
PackageIdentifier: tungoldshou.argos
PackageVersion: 0.1.0
PackageLocale: en-US
ManifestType: defaultLocale
ManifestVersion: 1.6.0
```

### 8.4 验证(契约 §14)

- `winget validate --manifest packaging/winget/tungoldshou.argos.installer.yaml` 退出 0
  (CI 装 `wingetcreate` 跑;或本地 `winget` 工具)
- SHA256 / URL 字段在新 release 后 `bump-homebrew-formula.yml` 同 workflow 同步 bump

## 9. Nix(契约 §7;spec D11)

### 9.1 `flake.nix`(新,简化版)

```nix
{
  description = "Argos — terminal super-agent";
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
  outputs = { self, nixpkgs }: let
    pkgs = nixpkgs.legacyPackages.x86_64-linux;
    pyPkgs = pkgs.python312Packages;
  in {
    packages.x86_64-linux.default = pyPkgs.buildPythonApplication {
      pname = "argos-agent";
      version = "0.1.0";
      src = ./.;
      propagatedBuildInputs = with pyPkgs; [ smolagents textual httpx numpy ];
      # 注:ddgs / mlx-embeddings / sqlite-vec / playwright / trafilatura 在 nixpkgs 不全,
      # 暂缺。v1.1 走 buildPythonPackage 替代 buildPythonApplication。
      doCheck = false;
      meta.mainProgram = "argos";
    };
    apps.x86_64-linux.default = {
      type = "app";
      program = "${self.packages.x86_64-linux.default}/bin/argos";
    };
  };
}
```

### 9.2 nixpkgs PR 模板

`docs/superpowers/nixpkgs-pr.md` 含:
- 摘要(Argos 是什么)
- 测试怎么跑(`nix-build -A argos-agent` / `nix run` / `argos --selftest`)
- 已知 issue:mlx-embeddings / sqlite-vec 在 nixpkgs 缺(等评审反馈)
- 链接:Argos 仓 / spec

### 9.3 验证(契约 §14)

- 本地 `nix flake check`(若 dev shell 有 nix;v1.1 真跑)

## 10. 修 release.yml 0 jobs bug(契约 §8;spec D10)

### 10.1 当前 bug

`actions/setup-python@v5` 在 2024 末-2025 初与 macos-14 偶发 validator 报 0 jobs;
`softprops/action-gh-release@v2` 偶发 token 解析失败。**修法**:
1. pin `actions/setup-python@v4`(修 0 jobs)
2. 换 `gh release create` via `run:` step(免 softprops 依赖)

### 10.2 修后结构

```yaml
name: Release
on:
  push:
    tags: [ 'v*' ]

permissions:
  contents: write

jobs:
  build-macos:
    runs-on: macos-14
    steps:
      - uses: actions/checkout@v4
        with: {fetch-depth: 0}
      - uses: actions/setup-python@v4       # pin v4 修 0 jobs
        with: {python-version: "3.12"}
      - uses: astral-sh/setup-uv@v4
      - name: Install deps
        run: uv sync
      - name: Build macOS arm64
        env: {ARGOS_VERSION: ${{ github.ref_name }}}
        run: bash packaging/build_arm64.sh
      - name: Pack macOS tarball + sha256
        env: {ARGOS_VERSION: ${{ github.ref_name }}}
        run: |
          VERSION="${ARGOS_VERSION#v}"
          cd dist
          tar czf "Argos-${VERSION}-arm64-mac.tar.gz" -C "Argos.app/.." "Argos.app"
          shasum -a 256 "Argos-${VERSION}-arm64-mac.tar.gz" > "SHA256SUMS"
      - uses: actions/upload-artifact@v4
        with: {name: dist-macos, path: dist/}

  build-linux:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v4
        with: {fetch-depth: 0}
      - uses: actions/setup-python@v4
        with: {python-version: "3.12"}
      - uses: astral-sh/setup-uv@v4
      - name: Install build deps
        run: |
          sudo apt-get update
          sudo apt-get install -y dpkg-dev rpm fuse wget
      - name: Build Linux (AppImage + .deb + .rpm)
        env: {ARGOS_VERSION: ${{ github.ref_name }}}
        run: bash packaging/build_linux.sh
      - uses: actions/upload-artifact@v4
        with: {name: dist-linux, path: dist/}

  build-windows:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
        with: {fetch-depth: 0}
      - uses: actions/setup-python@v4
        with: {python-version: "3.12"}
      - uses: astral-sh/setup-uv@v4
      - name: Build Windows (.exe + .msi)
        env: {ARGOS_VERSION: ${{ github.ref_name }}}
        run: bash packaging/build_windows.sh
      - uses: actions/upload-artifact@v4
        with: {name: dist-windows, path: dist/}

  release:
    needs: [build-macos, build-linux, build-windows]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/download-artifact@v4
        with: {pattern: dist-*, path: dist/}
      - name: Generate final SHA256SUMS
        working-directory: dist
        run: sha256sum -- * > SHA256SUMS
      - name: Create GitHub release (gh release create)
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          VERSION="${GITHUB_REF_NAME#v}"
          gh release create "v${VERSION}" \
            dist/*.{tar.gz,AppImage,deb,rpm,zip,msi.zip} \
            dist/SHA256SUMS \
            --title "Argos v${VERSION}" \
            --generate-notes \
            --repo "${{ github.repository }}"
```

## 11. 错误处理

| 错误 | 处理 |
|---|---|
| `uv build` 失败(依赖不全 / metadata 错) | 拒 publish,exit 1 |
| `twine check dist/*` 失败(metadata 警告) | 警告日志,exit 0(spec D12 锁 metadata warn 不卡) |
| OIDC 未配(没在 PyPI 后台 enable publisher) | fallback 走 `PYPI_API_TOKEN` secret;workflow 注释明示两路径 |
| Linux build 失败(ubuntu runner fuse 不可用) | 跳 AppImage 仅出 .deb/.rpm;日志 warn |
| Windows build 失败(wix 没装) | 仅出 .exe zip;spec D3 锁 .msi 可选 |
| `appimagetool` 下载失败 | 跳 AppImage;日志 warn |
| `dpkg-deb` 失败(依赖符号链接) | exit 1(无法 .deb) |
| `rpmbuild` 失败(rpm spec 错) | exit 1 |
| Homebrew bump workflow 失败(SHA256 拉不到) | exit 1(GH 通知) |
| WinGet manifest schema 非法 | `winget validate` 退出非 0,CI fail |
| Nix flake check 失败(本地无 nix) | 跳(spec §9.3 锁 v1.1 真测) |
| `gh release create` 失败(token 不足) | exit 1;GH 通知 |
| Cross-OS 跑某 job 失败 | 拒发 release(needs 失败) |
| Winget 提交审核期 spec 不全 | README 标"待 winget 审核";不让用户 winget 装失败 |
| Nixpkgs PR 审核期不合并 | README 标"待 nixpkgs 合并";提供 `nix run` workaround |

## 12. 测试(spec §14)

### 12.1 文件清单(7 文件,+ ~30 测试)

| 文件 | 覆盖 | 估测 |
|---|---|---|
| `tests/test_packaging_pypi.py` | pyproject.toml 字段 / scripts / sdist include / uv build dry-run | 8 |
| `tests/test_packaging_linux_spec.py` | build_linux.sh 必含步骤 + apt/dpkg/rpm 命令在 ubuntu 装好 | 4 |
| `tests/test_packaging_windows_spec.py` | build_windows.sh 必含步骤 + pyinstaller onefile 命令 | 3 |
| `tests/test_packaging_homebrew.py` | Formula/argos.rb 字段 + Casks/argos.rb 字段 + bump workflow 模板 | 5 |
| `tests/test_packaging_winget.py` | manifest 三件齐 + schema 合法字段(不调真 winget 工具) | 4 |
| `tests/test_packaging_release_workflow.py` | release.yml v4 pin + jobs 矩阵 + gh release create 命令 | 3 |
| `tests/test_packaging_install_scripts.py` | install-deb.sh 必含 + SHA256 校验 | 3 |

### 12.2 端到端铁证

- **PyPI**:本地 `uv build` 出 wheel + sdist;`pip install ./dist/*.whl` 进 venv;`which argos`
  命中;`argos --version` 0.1.0;`argos --selftest` 退出 0
- **Linux**:CI runner 真跑 `bash packaging/build_linux.sh` → 3 产物 file 类型正确;
  至少 AppImage 可跑(本机 FUSE 不一定,但 `chmod +x` + `file` 验)
- **Windows**:CI runner 真跑 → 1 产物 zip 含 argos.exe
- **Release workflow**:`tag v0.2.0-rc1` 跑 dry-run,验证 jobs 跑通(真 release 留手动 / 走 /ship)

### 12.3 既有 1622 测试 0 破坏

- 不动 `argos_agent/` 任何源文件
- 不动 `__main__.py`(除 `[project.scripts]` 已有 `argos`,本期待加 `argospkg` 走 dispatcher)
- 不动 `core/loop.py` / `setup_wizard.py` / `eval/` / `skills_curator/`
- 不动 `pyproject.toml` 既有字段(只加 `license` / `authors` / `keywords` / `classifiers` /
  `urls` / `[project.scripts]` 加 `argospkg` / `[tool.hatch.build.targets.sdist]` 显式 include)

## 13. 风险与未来

- **风险 1**:PyPI 装出 bad binary — wheel 漏 data 文件 → 跑 `argos --selftest` 失败;spec §4.4 锁
  install + selftest 双检
- **风险 2**:Linux 跑 fuse 失败(AppImage) — 用户系统没 fuse;**友好错误**(spec §11)+ v1.1
  接 flatpak/snap 兜底
- **风险 3**:WiX 装失败(.msi) — spec D3 锁"简化 .msi 失败不卡",仅 .exe zip
- **风险 4**:WinGet 审核期 1-2 周 — README 标"待审",提供 .exe 直链兜底
- **风险 5**:nixpkgs 审核期几周-几月 — 同上
- **风险 6**:OIDC 配错 → publish 失败 — fallback 走 token 路径
- **风险 7**:Homebrew tap 仓 GH PAT 泄露 — secret 走 repo-level 加密;v1.1 接 GitHub App
- **风险 8**:跨 OS 矩阵 CI 跑 30+ 分钟 — release 频率低,可接受;v1.1 接 cache 加速
- **风险 9**:`bump-formula-pr` 公式冲突 — 本期走 sed 简单注入;v1.1 走 `praeclarum/homebrew-bump-formula-pr`
- **风险 10**:`argos_agent/cli/pkg.py` 加 dispatcher 影响 main 启动速度 — 仅在 `argospkg`
  命令路径走,主 `argos` 启动 0 影响
- **未来 v1.1**:
  - Linux aarch64 / musl(Alpine)
  - macOS x86_64
  - flatpak / snap
  - scoop / chocolatey
  - code signing + notarize(macOS / Windows)
  - nixpkgs buildPythonApplication 完整版
  - homebrew-bump-formula-pr 自动化
  - Per-OS smoke test 端到端(spec §12.2 仅 file 类型检,真跑 AppImage 留 v1.1)

## 14. 决策记录(D1-D20)

| # | 决策 | 选项 | 拍板 | 理由 |
|---|---|---|---|---|
| D1 | PyPI 项目名 | `argos` / `argos-agent` / `argospkg` | **`argos-agent`** | 跟现有 `pyproject.toml` 一致;PyPI 上 `argos` 已被占(用户已自查) |
| D2 | Linux 通用格式 | AppImage / .deb / .rpm / snap / flatpak | **AppImage 主推 + .deb + .rpm** | AppImage 跨 glibc 通用;.deb 走 apt 路线(>50% Linux 用户);.rpm 走 dnf 路线(>15%);snap/flatpak 沙箱生态分裂,留 v1.1 |
| D3 | Windows MSI 工具链 | WiX (candle/light) / Inno Setup / msitools / NSIS | **WiX 简化方案(失败仅警告,只 .exe zip)** | msitools 装麻烦;WiX 简版能用;Inno Setup 需 Windows-only 工具,GitHub Actions windows-latest 默认有 WiX 3 |
| D4 | Homebrew tap 仓 | 个人 / 组织 | **个人(`tungoldshou/homebrew-argos`)** | 跟用户 GitHub 账号一致;无 org 成本 |
| D5 | WinGet 提交策略 | 手动 PR / 自动(wingetcreate) | **手动 PR + 自动生成 manifest** | 自动提交要 fork `microsoft/winget-pkgs`,复杂度高;manifest 写好,真提交一次走手动 |
| D6 | PyPI 发布认证 | Manual token / Trusted Publishing (OIDC) | **OIDC 主推 + token fallback** | OIDC 不需 secret 轮换;`actions/setup-python@v4` 已配 `id-token: write` |
| D7 | Multi-arch 范围 | macOS arm64 only / x86_64 + arm64 / Linux aarch64 | **macOS arm64 + Linux x86_64** | macOS x86_64 极少用户(<5%);Linux aarch64 极少(RPi 4GB 用户);v1.1 视情况 |
| D8 | `argv[0]` dispatcher | `argos` (主) / `argospkg` (打包工具) / `argos-tui` (TUI 强制) | **`argos` + `argospkg` 双 script** | 主 `argos` 跑 agent;`argospkg` 跑打包工具(spec §4.2);`argos-tui` 留 v1.1(本期 TUI/CLI 已在同一 main) |
| D9 | License | MIT / Apache-2.0 | **MIT** | 现有 LICENSE 文件是 MIT;PyPI classifiers 配 "MIT License" |
| D10 | sdist 是否含 README | 含 / 不含 | **含** | PyPI readme 渲染需;spec §4.1 [project.readme] 已配 |
| D11 | Nix 包装 | `buildPythonApplication` (nixpkgs 标准) / 直接 `python3` + `pip install` | **buildPythonApplication 简化版** | 走标准可被 nixpkgs 收;v1.1 完整化 |
| D12 | Twine check 警告 | fail / warn-only | **warn-only** | PyPI 偶尔加新 warning;metadata 改改就好 |
| D13 | Homebrew tap license 文件 | 不需要 / MIT | **MIT** | 跟主仓一致 |
| D14 | `pyproject.toml` [project] license | `text = "MIT"` / `file = "LICENSE"` | **`text = "MIT"`** | PEP 639 推荐 text;file 路径要 fullpath 解析;简化 |
| D15 | `[project.scripts]` 顺序 | argos 排首位 | **是** | 主命令最常用 |
| D16 | `bump-formula` workflow 触发 | push tag / release published | **release published** | 拿 SHA256 需 release 资产确定 |
| D17 | winget 提交 | 自动 / 手动 | **手动(本期待审核)** | PR 复杂;manifest 写好即可 |
| D18 | Linux AppImage 图标 | 占位 PNG / 真 branding | **占位 PNG** | 品牌素材 v1.1 补;AppImage 跑得起来即可 |
| D19 | macOS release asset 重命名 | `Argos-X.Y.Z-arm64-mac.tar.gz` (现) / `Argos_X.Y.Z_arm64.dmg` (homebrew 兼容) | **保持现命名** | 现有 install.sh / cask 已绑定;改即破 |
| D20 | .msi 可选 | 出 / 不出 | **出(简化方案,失败仅警告)** | Windows 用户 MSI 体验好;失败退 .exe zip 兜底 |

## 15. 实施任务(对应 plan)

8-10 任务,1 任务 = 1 commit,完整 TDD(配置/脚本/工作流为主,TDD 落到 manifest 字段+workflow
结构 assertion):

1. `pyproject.toml` 增 `license` / `authors` / `keywords` / `classifiers` / `urls` / `[project.scripts].argospkg` / `[tool.hatch.build.targets.sdist]` 显式 include
2. `argos_agent/cli/pkg.py` 新 dispatcher(`info` / `check` / `manifest`)+ `[project.scripts]` 验证
3. `packaging/build_linux.sh` 新 — PyInstaller + AppImage + .deb + .rpm
4. `packaging/build_windows.sh` 新 — PyInstaller + .exe zip + .msi(可选)
5. `packaging/install-deb.sh` 新 — .deb 一行装
6. `packaging/homebrew-tap/` 新(本仓内,等同 `homebrew-argos` 仓内容)— `Formula/argos.rb` + `Casks/argos.rb` + README
7. `.github/workflows/bump-homebrew-formula.yml` 新 + `bump-winget-manifest.yml` 联动
8. `packaging/winget/tungoldshou.argos.{installer,locale.en-US,yaml}` 三件 + `winget validate` CI 步
9. `flake.nix` 新 + nixpkgs PR 模板 + README 段
10. `.github/workflows/release.yml` 修 0 jobs bug + 加 linux/windows job + gh release create
11. `.github/workflows/publish.yml` 新 — PyPI OIDC + manual token fallback
12. 文档 + CHANGELOG + README + acceptance

## 16. 不触动清单(契约 §9 锁)

- **不**改 `argos_agent/` 任何 .py(除新加 `cli/pkg.py` 一文件)
- **不**改 `__main__.py`(`[project.scripts].argos` 已有,不动 main;`argospkg` 走新 dispatcher)
- **不**改 `core/loop.py` / `setup_wizard.py` / `eval/` / `skills_curator/` / `context/` / `routing/` /
  `daemon/` / `memory/` / `sandbox/` / `tools/` / `lsp/` / `skills_runtime/` / `permissions/` /
  `hooks/` / `mcp_native.py` / `browser.py` / `tui/`(spec §18 锁)
- **不**改既有 `pyproject.toml` `[project]` `name` / `version` / `description` / `dependencies`
- **不**改既有 `[project.scripts].argos`
- **不**改既有 `packaging/build_arm64.sh` / `install.sh` / `Info.plist` / `argos.spec` / `homebrew/argos.rb` / `VERSION`
- **不**改 `CHANGELOG.md` 既有 `## [0.1.0]` 段(只往 `## [Unreleased]` 加)
- **不**改 `README.md` 既有"什么是 Argos"段(只加新通道段)
- **不**加 sqlite / **不**加新强制外部依赖
- **不**接 code signing / notarize / SmartScreen 跳警
- **不**真提交 winget-pkgs / nixpkgs PR(留手动)
- **不**建 `tungoldshou/homebrew-argos` 仓(留手工;spec §7 锁"manifest 写好")
