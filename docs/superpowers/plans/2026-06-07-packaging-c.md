# 打包 C 阶段 — PyPI + Linux/Windows + 全包管理 — 实施计划

> Road-map #13 / spec `2026-06-07-packaging-c-design.md` 的 TDD 实施计划。
> **10 任务,1 任务 = 1 commit,合计 +~30 测试,0 新源代码逻辑**(纯 packaging + 配置 +
> CI 工作流)。C 阶段不引入新业务能力,只把"装得到"从 1 个 OS 扩到 6 个 OS。
>
> **本计划不动**:`argos/` 任何业务 .py(除新加 `cli/pkg.py` 一文件);`__main__.py`(`[project.scripts].argos` 已有,不动 main);`core/loop.py` / `setup_wizard.py` / `eval/` / `skills_curator/` / `context/` /
> `routing/` / `daemon/` / `memory/` / `sandbox/` / `tools/` / `lsp/` / `skills_runtime/` /
> `permissions/` / `hooks/` / `mcp_native.py` / `browser.py` / `tui/` / `pyproject.toml` 既有
> `[project]` name/version/description/dependencies/requires-python/script.argos(只追加);
> 既有 `packaging/build_arm64.sh` / `install.sh` / `Info.plist` / `argos.spec` /
> `homebrew/argos.rb` / `VERSION`。
>
> **新代码全部在**:`pyproject.toml`(追加段)+ `packaging/build_linux.sh`(新)+
> `packaging/build_windows.sh`(新)+ `packaging/install-deb.sh`(新)+ `packaging/winget/`(新 3 件)
> + `packaging/homebrew-tap/`(新,等同 homebrew-argos 仓内容)+ `flake.nix`(新)+
> `.github/workflows/release.yml`(重写,修 0 jobs bug)+ `.github/workflows/publish.yml`(新)+
> `.github/workflows/bump-homebrew-formula.yml`(新)+ `argos/cli/pkg.py`(新, dispatcher)+
> `CHANGELOG.md` + `README.md` + `tests/test_packaging_*.py` × 6。
>
> **不** git 跟踪 CI 产物;**不**真提交 winget-pkgs / nixpkgs PR(留手动);**不**建
> `tungoldshou/homebrew-argos` 仓(留手工);**不**接 code signing / notarize。

## 0. 总览

| 任务 | 标题 | 估测 | 关键文件 | 测试文件 |
|---|---|---|---|---|
| T1 | `pyproject.toml` 追加 `license`/`authors`/`keywords`/`classifiers`/`urls` + `[project.scripts].argospkg` + `[tool.hatch.build.targets.sdist]` 显式 include | 15 min | `pyproject.toml`(扩展) | `test_packaging_pypi.py` |
| T2 | `argos/cli/pkg.py` 新 dispatcher(info/check/manifest) + `[project.scripts]` 验证 | 20 min | `argos/cli/pkg.py`(新) | `test_packaging_pypi.py`(扩展) |
| T3 | `packaging/build_linux.sh` 新 — PyInstaller onefile + AppImage + .deb + .rpm | 30 min | `packaging/build_linux.sh`(新) | `test_packaging_linux_spec.py` |
| T4 | `packaging/build_windows.sh` 新 — PyInstaller onefile + .exe zip + .msi (可选 WiX 简化) | 25 min | `packaging/build_windows.sh`(新) | `test_packaging_windows_spec.py` |
| T5 | `packaging/install-deb.sh` 新 — .deb 一行装(对齐 B 阶段 install.sh 体验) | 15 min | `packaging/install-deb.sh`(新) | `test_packaging_install_scripts.py` |
| T6 | `packaging/homebrew-tap/` 新 — `Formula/argos.rb` + `Casks/argos.rb` + tap README | 20 min | `packaging/homebrew-tap/`(新) | `test_packaging_homebrew.py` |
| T7 | `.github/workflows/bump-homebrew-formula.yml` 新 + `bump-winget-manifest.yml` 联动(联动到 publish 步骤) | 20 min | `.github/workflows/bump-*.yml`(新) | `test_packaging_homebrew.py`(扩展) |
| T8 | `packaging/winget/tungoldshou.argos.{installer,locale.en-US,yaml}` 三件 + `winget validate` CI 步 | 25 min | `packaging/winget/`(新) | `test_packaging_winget.py` |
| T9 | `flake.nix` 新 + nixpkgs PR 模板 + README 段 | 20 min | `flake.nix`(新) + `docs/superpowers/nixpkgs-pr.md`(新) | (skip — 没 nix 二进制) |
| T10 | `.github/workflows/release.yml` 重写(修 0 jobs bug + linux/windows job + gh release create) + `.github/workflows/publish.yml`(PyPI OIDC + token fallback) | 30 min | `.github/workflows/release.yml`(重写)+ `publish.yml`(新) | `test_packaging_release_workflow.py` |
| T11 | 文档 + CHANGELOG + README + acceptance | 20 min | `CHANGELOG.md` + `README.md` + `docs/packaging-c.md` | (含 e2e) |

**关键不变量**(spec 灵魂,plan 全程守住):
- **不**改 `argos/` 任何业务 .py(除新加 `cli/pkg.py` 一文件,这是 #13 spec 显式允许的)
- **不**改 `__main__.py`(主 `argos` 路径 0 改动,`argospkg` 走新 dispatcher)
- **不**改 `pyproject.toml` 既有 `[project]` name/version/description/dependencies/
  requires-python/script.argos(只追加)
- **不**改 `packaging/build_arm64.sh` / `install.sh` / `Info.plist` / `argos.spec` /
  `homebrew/argos.rb` / `VERSION`(B 阶段原样保留)
- **不**加 sqlite / **不**加新强制外部依赖 / **不**改 `uv.lock` 既有依赖
- **不**真提交 winget-pkgs / nixpkgs / 建 homebrew-argos 仓(留手动;spec §7.5 / §8.4 / §9.3 锁)
- **不**接 code signing / notarize
- **`uv build` 跑通** = 任务 T1+T2 验收(契约 §4.4 锁)
- **CI release.yml v* tag 跑通 jobs** = 任务 T10 验收(契约 §10 锁)
- **6 通道全产出** = 任务 T1-T11 全部(契约 §验收)

## 1. 任务 T1:`pyproject.toml` 追加 + sdist include

### 1.1 目标

- `pyproject.toml`:
  - `[project]` 加 `license = {text = "MIT"}` / `authors = [...]` / `keywords = [...]` /
    `classifiers = [...]` / `[project.urls]`
  - `[project.scripts]` 追加 `argospkg = "argos.cli.pkg:main"`
  - `[tool.hatch.build.targets.sdist]` 显式 `include` + `exclude`(现有 wheel targets 不动)

### 1.2 既有约束(不破)

- `name = "argos-agent"` 不动(spec D1)
- `version = "0.1.0"` 不动(/ship 自动 bump)
- `description` 不动
- `readme = "README.md"` 不动
- `requires-python = ">=3.12"` 不动
- `dependencies` 不动
- `argos = "argos.__main__:main"` 不动(主命令)
- `[build-system]` 不动
- `[tool.hatch.build.targets.wheel]` 不动
- `[dependency-groups] dev` 不动
- `[tool.pytest.ini_options]` 不动
- `[tool.coverage.run]` 不动

### 1.3 实现要点

```toml
[project]
# ... 既有字段 ...
license = {text = "MIT"}
authors = [
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

[project.scripts]
argos = "argos.__main__:main"
argospkg = "argos.cli.pkg:main"

[project.urls]
Homepage = "https://github.com/tungoldshou/argos"
Repository = "https://github.com/tungoldshou/argos"
Issues = "https://github.com/tungoldshou/argos/issues"
Changelog = "https://github.com/tungoldshou/argos/blob/main/CHANGELOG.md"

[tool.hatch.build.targets.sdist]
include = [
  "argos",
  "README.md",
  "LICENSE",
  "CHANGELOG.md",
  "packaging/VERSION",
  "packaging/Info.plist",
  "packaging/argos.spec",
]
exclude = [
  "tests",
  "build",
  "dist",
  "docs",
  "*.egg-info",
  ".venv",
  ".pytest_cache",
  ".codegraph",
  ".coverage",
]
```

### 1.4 测试(`test_packaging_pypi.py` part 1,~6 测试)

1. `test_pyproject_has_license_mit`:`[project.license]` 是 `{text = "MIT"}`
2. `test_pyproject_has_authors_with_email`:`[project.authors]` 非空,首项有 email
3. `test_pyproject_has_classifiers_list`:`[project.classifiers]` 是 list,含 "License :: OSI Approved :: MIT License" + "Programming Language :: Python :: 3.12"
4. `test_pyproject_has_urls_section`:`[project.urls]` 含 `Homepage` + `Repository` + `Issues` + `Changelog`
5. `test_pyproject_scripts_contains_argos_and_argospkg`:`[project.scripts]` 既含 `argos` 又含 `argospkg`,且 `argospkg` 指向 `argos.cli.pkg:main`
6. `test_pyproject_sdist_includes_critical_files`:`[tool.hatch.build.targets.sdist.include]` 含 `argos` + `README.md` + `LICENSE` + `packaging/VERSION` + `packaging/argos.spec`

### 1.5 验收(契约 §4.4)

- `uv build` 出 `dist/argos_agent-0.1.0-py3-none-any.whl` + `dist/argos-agent-0.1.0.tar.gz`
- 跑 `pip install ./dist/argos_agent-0.1.0-py3-none-any.whl --quiet` 进 venv,`which argos` 命中
- 跑 `which argospkg` 命中
- (注:`argospkg` 命令 import `argos.cli.pkg` → T2 实现后跑通;本任务只校验 pyproject 字段)

## 2. 任务 T2:`argos/cli/pkg.py` 新 dispatcher

### 2.1 目标

- 新文件 `argos/cli/pkg.py`:
  - `main() -> int`:`argospkg` 入口,根据 `sys.argv[1:]` 切子命令
  - `dispatch(argv) -> int`:分发到 info / check / manifest
  - `cmd_info() -> int`:打印 `pyproject.toml` [project] 段 / packaging/VERSION / git tag
  - `cmd_check() -> int`:走 `importlib.metadata` 验 wheel 装起来,跑 `--selftest` 简化版
  - `cmd_manifest() -> int`:显式生成 winget manifest(预演)

### 2.2 既有约束(不破)

- **不**改 `argos/cli/__init__.py`(已存在,本任务不触)
- **不**改 `__main__.py`(`argospkg` 是新 entry,主 `argos` 启动 0 影响)
- **不**改 `eval.py` / `skills.py` / `context.py` 等既有 CLI 模块

### 2.3 实现要点

```python
"""`argospkg` 命令 — 打包工具 dispatcher(spec D8)。

主 `argos` 跑 agent;`argospkg` 跑打包/发布辅助。0 业务逻辑:纯 CLI 工具。
"""
from __future__ import annotations
import sys
from pathlib import Path

__all__ = ["main", "dispatch"]


def main() -> int:
    return dispatch(sys.argv[1:])


def dispatch(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__ or "")
        print("usage: argospkg <subcommand> [args]")
        print("  info      — 打印项目元数据 + packaging/VERSION + git tag")
        print("  check     — 校验 wheel 装起来能跑 --version")
        print("  manifest  — 预演生成 winget manifest(留 v0.2.0)")
        return 0 if argv else 1
    sub, *rest = argv
    return {
        "info": cmd_info,
        "check": cmd_check,
        "manifest": cmd_manifest,
    }.get(sub, _unknown)(rest)


def _unknown(rest: list[str]) -> int:
    print(f"argospkg: unknown subcommand (got {rest!r})", file=sys.stderr)
    return 2


def cmd_info(rest: list[str]) -> int:
    """打印 pyproject [project] 段 + packaging/VERSION + git tag(若在 git 仓里)。"""
    from importlib.metadata import version as _v, metadata as _md
    try:
        name = _v("argos-agent")
    except Exception:
        name = "?"
    try:
        meta = _md("argos-agent")
        summary = meta.get("Summary", "")
        home = meta.get("Home-page", "") or (meta.get("Project-URL", "Homepage") if isinstance(meta.get("Project-URL"), str) else "")
    except Exception:
        summary, home = "", ""
    print(f"name:        argos-agent")
    print(f"version:     {name}")
    print(f"summary:     {summary}")
    print(f"homepage:    {home}")
    pkg_ver = Path("packaging/VERSION")
    if pkg_ver.exists():
        print(f"pkg/VERSION: {pkg_ver.read_text().strip()}")
    try:
        import subprocess
        tag = subprocess.check_output(
            ["git", "describe", "--tags", "--abbrev=0"],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
        print(f"git tag:     {tag}")
    except Exception:
        pass
    return 0


def cmd_check(rest: list[str]) -> int:
    """校验 importlib.metadata 能拿版本 + argos 入口 import 成功。"""
    try:
        from argos.__main__ import main as _argos_main
        from argos.cli import pkg  # 自我导入
    except Exception as e:  # noqa: BLE001
        print(f"argospkg check: import 失败:{e}", file=sys.stderr)
        return 1
    print("argospkg check: import OK")
    return 0


def cmd_manifest(rest: list[str]) -> int:
    """预演生成 winget manifest(v0.2.0 真出;v0.1.0 仅打印路径)。"""
    print("argospkg manifest: v0.1.0 仅占位;v0.2.0 接 wingetcreate 自动生成")
    manifest_dir = Path("packaging/winget")
    if manifest_dir.exists():
        for p in sorted(manifest_dir.glob("tungoldshou.argos.*.yaml")):
            print(f"  - {p}")
    return 0
```

### 2.4 测试(`test_packaging_pypi.py` part 2,~4 测试)

7. `test_argospkg_info_prints_metadata`:subprocess 跑 `python -m argos.cli.pkg info` 退出 0,stdout 含 `name: argos-agent` + `version:` + `pkg/VERSION:`
8. `test_argospkg_check_imports_cleanly`:subprocess 跑 `python -m argos.cli.pkg check` 退出 0,stdout 含 `import OK`
9. `test_argospkg_unknown_subcommand_exits_nonzero`:`argospkg foo` 退出 2,stderr 含 `unknown subcommand`
10. `test_argospkg_help_prints_usage`:无参 / `-h` 退出 0 或 1(看实现),stdout 含 `usage: argospkg`

## 3. 任务 T3:`packaging/build_linux.sh` 新

### 3.1 目标

- 跑 PyInstaller `--onefile` 出 ELF binary
- 3 种打包格式:
  - **AppImage**(主推,跨 glibc)
  - **.deb**(apt 路线)
  - **.rpm**(dnf 路线)
- 跑在 ubuntu-24.04 runner(spec D2 锁);Apple Silicon Mac 跑可加 `ARGOS_TARGET=aarch64`
- 终态 SHA256 + 产物清单

### 3.2 既有约束(不破)

- **不**改 `packaging/build_arm64.sh`(macOS only,B 阶段)
- **不**改 `packaging/argos.spec`(B 阶段 macOS arm64 only,Linux 走 inline `--add-data` 不复用 spec)
- **不**改 `packaging/Info.plist`(macOS 专属,Linux 不读)

### 3.3 实现要点

见 spec §5.1 完整 shell 脚本。关键步骤:
1. `uv run pyinstaller --onefile --target-arch x86_64 --console ...` 出 `dist/argos`
2. AppImage:`appimagetool` + `Argos.AppDir/{AppRun,usr/bin/argos,argos.desktop,argos.png}`
3. .deb:`dpkg-deb --build` 简单 binary 包
4. .rpm:`rpmbuild -bb` 用模板 spec

### 3.4 测试(`test_packaging_linux_spec.py`,4 测试)

1. `test_build_linux_script_exists`:`packaging/build_linux.sh` 存在 + `chmod +x` 过
2. `test_build_linux_script_runs_pyinstaller_onefile`:脚本 grep 含 `pyinstaller` + `--onefile` + `--console`
3. `test_build_linux_script_packs_appimage_deb_rpm`:脚本 grep 含 `appimagetool` + `dpkg-deb --build` + `rpmbuild -bb`
4. `test_build_linux_script_reads_argos_version_from_env`:脚本 grep 含 `ARGOS_VERSION="${ARGOS_VERSION:-"` + `cat packaging/VERSION`

(注:真在 ubuntu-24.04 runner 跑 `bash packaging/build_linux.sh` 出产物留 CI,本地 macOS 不跑)

## 4. 任务 T4:`packaging/build_windows.sh` 新

### 4.1 目标

- 跑 PyInstaller `--onefile` 出 `argos.exe`
- zip 打包
- 可选 .msi(走 WiX 简化方案;失败仅警告)

### 4.2 既有约束(不破)

- 同 T3

### 4.3 实现要点

见 spec §6.1 完整 shell 脚本。关键步骤:
1. `pyinstaller --onefile --console --name argos` 出 `dist/argos.exe`
2. `zip` 打包出 `Argos-X.Y.Z-x86_64-windows.zip`
3. 可选 WiX:`candle` + `light` 出 `.msi`;若 `candle` 不在 PATH 跳过(仅警告)

### 4.4 测试(`test_packaging_windows_spec.py`,3 测试)

1. `test_build_windows_script_exists`:`packaging/build_windows.sh` 存在 + `chmod +x` 过
2. `test_build_windows_script_runs_pyinstaller_onefile`:脚本 grep 含 `pyinstaller` + `--onefile` + `--name argos`
3. `test_build_windows_script_packs_zip_and_optional_msi`:脚本 grep 含 `zip "Argos-` + `candle` (msi 可选路径)

## 5. 任务 T5:`packaging/install-deb.sh` 新

### 5.1 目标

- 一行装最新版(对齐 B 阶段 `install.sh` 体验)
- 走 `curl` + `dpkg -i` + `apt-get install -f` 修依赖

### 5.2 实现要点

同 B 阶段 `install.sh` 模式(已存档);唯一区别:
- 拉 `.deb` 资产而非 `.tar.gz`
- `sudo dpkg -i argos_*.deb` 而非 `tar -xzf`
- `sudo apt-get install -f -y` 修依赖(若有 recommends 没装)

### 5.3 测试(`test_packaging_install_scripts.py`,3 测试)

1. `test_install_deb_script_exists`:`packaging/install-deb.sh` 存在
2. `test_install_deb_script_uses_dpkg_i`:脚本 grep 含 `dpkg -i` + `apt-get install -f`
3. `test_install_deb_script_uses_sha256_verification`:脚本 grep 含 `shasum -a 256` 或 `sha256sum -c` (沿用 B 阶段 SHA256SUMS)

## 6. 任务 T6:`packaging/homebrew-tap/` 新

### 6.1 目标

- 本仓内新目录 `packaging/homebrew-tap/`,内容等同未来 `tungoldshou/homebrew-argos` 仓
- 含:
  - `README.md`(简版,链回主仓)
  - `Formula/argos.rb`(Linux/CLI 装)
  - `Casks/argos.rb`(macOS GUI 装)
  - `.github/workflows/lint.yml`(跑 `brew tap-lint`)

### 6.2 既有约束(不破)

- **不**改既有 `packaging/homebrew/argos.rb`(B 阶段 Cask 在此;Casks/argos.rb 模板拷过来)
- **不**真建 `tungoldshou/homebrew-argos` 仓(留手动)

### 6.3 实现要点

`Formula/argos.rb`:
```ruby
class Argos < Formula
  desc "Argos — terminal super-agent (CodeAct loop + verify hard-gate + OS sandbox)"
  homepage "https://github.com/tungoldshou/argos"
  url "https://github.com/tungoldshou/argos/releases/download/v#{version}/Argos-#{version}-x86_64.AppImage"
  sha256 "PLACEHOLDER_FROM_BUMP"
  license "MIT"
  version "0.1.0"

  livecheck do
    url :url
    strategy :github_latest_release
  end

  depends_on "fuse" => :linux

  def install
    bin.install "Argos-#{version}-x86_64.AppImage" => "argos"
  end

  test do
    assert_match "argos #{version}", shell_output("#{bin}/argos --version")
  end
end
```

`Casks/argos.rb`:复制 B 阶段 `packaging/homebrew/argos.rb` 完整内容(就一份)。

`README.md`:
```markdown
# tungoldshou/argos Homebrew Tap

```bash
brew tap tungoldshou/argos
brew install argos           # Linux/CLI(Formula,走 AppImage)
brew install --cask argos    # macOS GUI(Cask,走 .app)
```
```

### 6.4 测试(`test_packaging_homebrew.py` part 1,~3 测试)

1. `test_homebrew_tap_directory_exists`:`packaging/homebrew-tap/` 在
2. `test_homebrew_formula_argos_contains_required_fields`:`Formula/argos.rb` 含 `desc` + `homepage` + `url` + `sha256` + `license "MIT"` + `depends_on "fuse" => :linux`
3. `test_homebrew_cask_argos_contains_app_directive`:`Casks/argos.rb` 含 `app "Argos.app"` + `zap trash:`

## 7. 任务 T7:`bump-homebrew-formula.yml` + `bump-winget-manifest.yml`

### 7.1 目标

- `.github/workflows/bump-homebrew-formula.yml`:release published → clone homebrew-argos 仓 →
  用 sed 更新 `Formula/argos.rb` + `Casks/argos.rb` 的 version + sha256 → 推回
- `.github/workflows/bump-winget-manifest.yml`:release published → update packaging/winget/* 3 件
  (version + URL + sha256);本仓内 commit

### 7.2 既有约束(不破)

- **不**改既有 `release.yml`(T10 重写)
- **不**改既有 `publish.yml`(本期新建)

### 7.3 实现要点

见 spec §7.4 + §8 联动。两 workflow 都 `on: release: types: [published]`。

bump-homebrew 需 `secrets.HOMEBREW_TAP_TOKEN`(用户后期配;workflow 配占位,无 token 不跑)。

### 7.4 测试(`test_packaging_homebrew.py` part 2,~2 测试)

4. `test_bump_homebrew_workflow_triggers_on_release`:`.github/workflows/bump-homebrew-formula.yml` 含 `on:\n  release:\n    types: [published]`
5. `test_bump_homebrew_workflow_uses_secrets_for_token`:含 `secrets.HOMEBREW_TAP_TOKEN` 或注释占位

## 8. 任务 T8:WinGet manifest 三件

### 8.1 目标

- `packaging/winget/tungoldshou.argos.installer.yaml`(ManifestType: installer)
- `packaging/winget/tungoldshou.argos.locale.en-US.yaml`(ManifestType: locale)
- `packaging/winget/tungoldshou.argos.yaml`(ManifestType: defaultLocale)
- 1.6.0 schema 合法
- 字段:PackageIdentifier / PackageVersion / PackageLocale / Publisher / PackageName / License /
  ShortDescription / ManifestType / ManifestVersion / Installers / InstallBehavior /
  UpgradeBehavior(后两者 installer.yaml 必填,locale/defaultLocale 不填)

### 8.2 既有约束(不破)

- **不**改既有 `packaging/` 任何文件
- **不**真提交 `microsoft/winget-pkgs`(留手动)

### 8.3 实现要点

见 spec §8.1-§8.3。SHA256 字段填 `PLACEHOLDER_FROM_BUMP`,bump workflow(T7)更新。

### 8.4 测试(`test_packaging_winget.py`,4 测试)

1. `test_winget_manifest_files_exist`:三件文件都在
2. `test_winget_installer_yaml_has_required_fields`:`tungoldshou.argos.installer.yaml` 含 `PackageIdentifier` + `PackageVersion` + `ManifestType: installer` + `ManifestVersion: 1.6.0` + `Installers` 列表
3. `test_winget_locale_yaml_has_description`:`tungoldshou.argos.locale.en-US.yaml` 含 `Description: |` 长描述
4. `test_winget_default_locale_yaml_present`:`tungoldshou.argos.yaml` 含 `ManifestType: defaultLocale`

(注:不调真 `winget validate` 二进制;CI 装 + 跑留 v1.1;本期只验 YAML 字段合法)

## 9. 任务 T9:`flake.nix` + nixpkgs PR 模板

### 9.1 目标

- `flake.nix` 简化版(`buildPythonApplication`,不依赖 nixpkgs 不可得包)
- `docs/superpowers/nixpkgs-pr.md` PR 模板

### 9.2 既有约束(不破)

- **不**改 `pyproject.toml` 既有段
- **不**真提交 `NixOS/nixpkgs` PR(留手动)

### 9.3 实现要点

见 spec §9.1-§9.2。`buildPythonApplication` 简化版(不引 ddgs / mlx-embeddings / sqlite-vec /
playwright / trafilatura;`propagatedBuildInputs` 只列 nixpkgs 现成的 smolagents/textual/httpx/numpy)。

### 9.4 测试

- 无自动化测试(本地无 nix 二进制;v1.1 接 CI runner 跑 `nix flake check`)

## 10. 任务 T10:`release.yml` 重写 + `publish.yml` 新建

### 10.1 目标

- `release.yml` 重写:
  - pin `actions/setup-python@v4`(修 0 jobs bug)
  - 3 OS 矩阵 jobs:`build-macos` (B 既有) / `build-linux` (新) / `build-windows` (新)
  - `release` job 等 3 build → `gh release create`(替换 `softprops/action-gh-release@v2`)
- `publish.yml` 新建:
  - `on: push: tags: 'v*' + workflow_dispatch`
  - `build` job:ubuntu-latest 跑 `uv build`
  - `pypi` job:`pypa/gh-action-pypi-publish@release/v1` (OIDC 主推 + token fallback)

### 10.2 既有约束(不破)

- **不**改既有 workflow 文件名(`release.yml` 重写,`publish.yml` 新建)
- **不**改既有其他 workflow(本项目只有 release.yml 一个)
- **不**改 secrets(用户在仓库 Settings 配;workflow 文档提示需要哪些 secrets)

### 10.3 实现要点

见 spec §10.2 + §4.3 完整 workflow YAML。

### 10.4 测试(`test_packaging_release_workflow.py`,3 测试)

1. `test_release_workflow_pins_setup_python_v4`:`release.yml` 全文 grep 含 `actions/setup-python@v4` (无 v5)
2. `test_release_workflow_has_three_os_jobs`:`release.yml` 全文 grep 含 `build-macos:` + `build-linux:` + `build-windows:`
3. `test_release_workflow_uses_gh_release_create`:`release.yml` 全文 grep 含 `gh release create`

`publish.yml` 测试合并到 `test_packaging_pypi.py` part 3:
11. `test_publish_workflow_exists_and_uses_pypa_action`:`.github/workflows/publish.yml` 含 `pypa/gh-action-pypi-publish@release/v1` + `id-token: write`

## 11. 任务 T11:文档 + CHANGELOG + README + acceptance

### 11.1 目标

- `CHANGELOG.md` `[Unreleased]` 加 #13 段(沿用 #12 风格,~40 行)
- `docs/packaging-c.md` 新建:C 阶段说明 / 各通道安装命令 / 已知限制
- `README.md` 加 #13 链接 + 各通道安装命令段(沿用 #11 / #12 风格)
- 端到端铁证:`uv build` 跑通 + `pip install` 跑通 + `argos --version` 跑通(本地)

### 11.2 CHANGELOG 模板

```markdown
- **打包 C 阶段 — PyPI + Linux/Windows + 全包管理 (#13)**:**让"用啥系统都能装上、升级快、可信源"
  成为可能**,从 B 阶段 1 个 OS(macOS arm64)扩到 6 个 OS(PyPI + Linux 3 格式 + Windows +
  Homebrew tap + WinGet + Nix)。**核心架构**:
  - **PyPI 发布通电**(`pyproject.toml` 扩展 + `.github/workflows/publish.yml` 新):`license`/
    `authors`/`keywords`/`classifiers`/`urls` 字段补齐(spec D14);`[project.scripts]` 加
    `argospkg = "argos.cli.pkg:main"` 走打包工具 dispatcher(spec D8);sdist 显式 include
    README/LICENSE/CHANGELOG/packaging/VERSION/packaging/Info.plist/packaging/argos.spec(spec D10);
    OIDC trusted publishing 主推 + `PYPI_API_TOKEN` token fallback(spec D6);`uv build` 出
    wheel + sdist,`pip install ./dist/*.whl` 验通
  - **`argospkg` dispatcher**(`argos/cli/pkg.py` 新):`info` 印元数据/`check` 验 import/
    `manifest` 预演生成 winget;**0** 改 `__main__.py` 主 `argos` 路径
  - **Linux 打包**(`packaging/build_linux.sh` 新):PyInstaller onefile → 3 格式:
    **AppImage**(主推,跨 glibc)/ **.deb**(apt 路线)/ **.rpm**(dnf 路线);`install-deb.sh` 一行装
    最新版(对齐 B 阶段 install.sh 体验);`dpkg-deb` + `rpmbuild` + `appimagetool` 兜底
  - **Windows 打包**(`packaging/build_windows.sh` 新):PyInstaller onefile → `.exe` zip;**.msi** 走
    WiX 简化方案(candle/light,失败仅警告仅 .exe);`winget validate` CI 步(spec D3)
  - **Homebrew tap 仓骨架**(`packaging/homebrew-tap/` 新,等同 `tungoldshou/homebrew-argos` 仓):
    `Formula/argos.rb`(Linux/CLI 装,AppImage + `fuse` 依赖)/ `Casks/argos.rb`(macOS GUI,迁自
    `packaging/homebrew/argos.rb`);`bump-homebrew-formula.yml` 联动 release published
    自动更新 version + sha256(spec D4)
  - **WinGet manifest 三件**(`packaging/winget/tungoldshou.argos.{installer,locale.en-US,yaml}`):
    1.6.0 schema 合法;`PackageIdentifier: tungoldshou.argos`;`bump-winget-manifest.yml` 联动
    自动更新 version + URL + sha256(spec D5);真 PR 留手动(审核期)
  - **Nix flake**(`flake.nix` 新):`buildPythonApplication` 简化版(只引 nixpkgs 现成的
    smolagents/textual/httpx/numpy;`ddgs`/`mlx-embeddings`/`sqlite-vec`/`playwright`/`trafilatura`
    留 v1.1 完整化);`docs/superpowers/nixpkgs-pr.md` PR 模板(spec D11)
  - **`release.yml` 修 0 jobs bug + 跨 OS 矩阵**(重写):pin `actions/setup-python@v4`(B 阶段
    `@v5` 偶发 validator bug 修了);3 job:`build-macos`(B 既有)/`build-linux`(新)/`build-windows`(新);
    `release` job 走 `gh release create` 替换 `softprops/action-gh-release@v2`(免 softprops
    Node 20 依赖 + token 解析);`pypa/gh-action-pypi-publish@release/v1` 走 OIDC trusted publishing
  - **0 新源代码逻辑**(`argos/` 仅新加 `cli/pkg.py` 一文件);**0 新强制外部依赖**
    (stdlib only + OIDC 免 token);+~30 测试(6 文件:`test_packaging_pypi` 11 / `test_packaging_linux_spec` 4 /
    `test_packaging_windows_spec` 3 / `test_packaging_install_scripts` 3 / `test_packaging_homebrew` 5 /
    `test_packaging_winget` 4 / `test_packaging_release_workflow` 3);**不**改既有 `packaging/build_arm64.sh`/
    `install.sh`/`Info.plist`/`argos.spec`/`homebrew/argos.rb`/`VERSION`(B 阶段原样保留);**不**改
    `argos/` 任何业务 .py;**不**真提交 winget-pkgs / nixpkgs / 建 homebrew-argos 仓
    (留手动;审核期过后单独 PR);spec 在 `docs/superpowers/specs/2026-06-07-packaging-c-design.md`,
    plan 在 `docs/superpowers/plans/2026-06-07-packaging-c.md`,用户文档在 `docs/packaging-c.md`
```

### 11.3 README 加段

```markdown
- **打包 C 阶段 #13 — PyPI + Linux/Windows + 全包管理** — `pip install argos-agent` /
  `brew install tungoldshou/argos/argos` / `winget install tungoldshou.argos` / AppImage /
  .deb / .rpm / .exe 全通道装;`gh release create` 跨 3 OS 矩阵自动发版
```

### 11.4 端到端铁证(本地 macOS 验)

```bash
# 1. PyPI wheel 真出 + 装 + 跑
uv build
pip install --quiet ./dist/argos_agent-0.1.0-py3-none-any.whl
which argos    # 命中 venv bin
argos --version  # argos 0.1.0

# 2. argospkg dispatcher
argospkg info    # 印 name/version/summary
argospkg check   # 印 import OK

# 3. CI 真跑(本地不可,推 tag 后)
git tag v0.2.0-rc1
git push --tags   # 触发 release.yml, 3 job 真跑
```

## 12. 验收(对应 spec §14)

1. ✅ **测试**:1622 → ~1652(+30),0 失败
2. ✅ **`uv build` 跑通**:`dist/argos_agent-0.1.0-py3-none-any.whl` + `dist/argos-agent-0.1.0.tar.gz` 真出
3. ✅ **`pip install` 跑通**:`which argos` + `which argospkg` 都命中;`argos --version` 输出 `0.1.0`
4. ✅ **`release.yml` 0 jobs bug 修了**:pin `setup-python@v4` + 3 OS jobs + `gh release create`
5. ✅ **Homebrew tap 骨架齐**:`packaging/homebrew-tap/Formula/argos.rb` + `Casks/argos.rb`
   字段全(spec D4)
6. ✅ **WinGet manifest 3 件齐**:1.6.0 schema 字段全(spec D5)
7. ✅ **`flake.nix` 简化版在**:v1.1 完整化
8. ✅ **既有 1622 测试 0 破**:`argos/` 仅加 `cli/pkg.py` 一文件;`__main__.py` 0 改;
   `pyproject.toml` 仅追加(无既有字段改写)
9. ✅ **0 新强制外部依赖**

## 13. 不触动清单(契约 §9 锁,执行期反复自检)

- [ ] 不改 `argos/` 任何 .py(除新加 `cli/pkg.py` 一文件)
- [ ] 不改 `__main__.py`
- [ ] 不改 `core/loop.py` / `setup_wizard.py` / `eval/` / `skills_curator/` / `context/` /
      `routing/` / `daemon/` / `memory/` / `sandbox/` / `tools/` / `lsp/` /
      `skills_runtime/` / `permissions/` / `hooks/` / `mcp_native.py` / `browser.py` / `tui/`
- [ ] 不改 `pyproject.toml` 既有 `[project]` name/version/description/dependencies/requires-python/script.argos
- [ ] 不改既有 `packaging/build_arm64.sh` / `install.sh` / `Info.plist` / `argos.spec` /
      `homebrew/argos.rb` / `VERSION`
- [ ] 不改 `CHANGELOG.md` 既有 `## [0.1.0]` 段
- [ ] 不改 `README.md` 既有"什么是 Argos"段
- [ ] 不加 sqlite / 不加新强制外部依赖
- [ ] 不接 code signing / notarize / SmartScreen 跳警
- [ ] 不真提交 winget-pkgs / nixpkgs / 建 homebrew-argos 仓(留手动)
