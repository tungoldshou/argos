"""打包 C 阶段 — PyPI 元数据 + argospkg dispatcher 测试(plan T1+T2)。

- part 1:T1 pyproject.toml 字段 + sdist include
- part 2:T2 argospkg dispatcher(info / check / unknown / help)
- part 3:T10 publish.yml workflow 结构
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
PYPROJECT = ROOT / "pyproject.toml"
CLI_PKG = ROOT / "argos_agent" / "cli" / "pkg.py"
PUBLISH_YML = ROOT / ".github" / "workflows" / "publish.yml"


# --- T1 part 1:pyproject 字段 ---

def test_pyproject_has_license_mit():
    """[project.license] 是 {text = 'MIT'} 形式(PEP 639)。"""
    txt = PYPROJECT.read_text()
    assert re.search(r'license\s*=\s*\{\s*text\s*=\s*"MIT"\s*\}', txt), (
        f"pyproject 缺 license = {{text = 'MIT'}};got:\n{txt[txt.find('license'):txt.find('license')+80]}"
    )


def test_pyproject_has_authors_with_email():
    """[project.authors] 非空 list,首项有 email。"""
    txt = PYPROJECT.read_text()
    m = re.search(r'authors\s*=\s*\[(.*?)\]', txt, flags=re.DOTALL)
    assert m, "pyproject 缺 [project.authors] 段"
    body = m.group(1)
    assert "email" in body, f"[project.authors] 缺 email:{body[:200]}"
    assert "tungoldshou" in body


def test_pyproject_has_classifiers_list():
    """[project.classifiers] 是 list,含 License + Python 3.12。"""
    txt = PYPROJECT.read_text()
    m = re.search(r'classifiers\s*=\s*\[(.*?)\]', txt, flags=re.DOTALL)
    assert m, "pyproject 缺 [project.classifiers] 段"
    body = m.group(1)
    assert "License :: OSI Approved :: MIT License" in body
    assert "Programming Language :: Python :: 3.12" in body
    assert "Operating System :: POSIX :: Linux" in body
    assert "Operating System :: Microsoft :: Windows :: Windows 10" in body


def test_pyproject_has_urls_section():
    """[project.urls] 含 Homepage + Repository + Issues + Changelog。"""
    txt = PYPROJECT.read_text()
    m = re.search(r'\[project\.urls\](.*?)(?=\n\[|\Z)', txt, flags=re.DOTALL)
    assert m, "pyproject 缺 [project.urls] 段"
    body = m.group(1)
    for k in ("Homepage", "Repository", "Issues", "Changelog"):
        assert k in body, f"[project.urls] 缺 {k};got:\n{body[:200]}"


def test_pyproject_scripts_contains_argos_and_argospkg():
    """[project.scripts] 既含 argos 又含 argospkg,argospkg 指向 cli.pkg:main。"""
    txt = PYPROJECT.read_text()
    m = re.search(r'\[project\.scripts\](.*?)(?=\n\[|\Z)', txt, flags=re.DOTALL)
    assert m, "pyproject 缺 [project.scripts] 段"
    body = m.group(1)
    assert re.search(r'^\s*argos\s*=\s*"argos_agent\.__main__:main"', body, re.M), \
        "缺 argos = argos_agent.__main__:main"
    assert re.search(r'^\s*argospkg\s*=\s*"argos_agent\.cli\.pkg:main"', body, re.M), \
        "缺 argospkg = argos_agent.cli.pkg:main"


def test_pyproject_sdist_includes_critical_files():
    """[tool.hatch.build.targets.sdist.include] 含 argos_agent + README + LICENSE + VERSION + argos.spec。"""
    txt = PYPROJECT.read_text()
    m = re.search(r'\[tool\.hatch\.build\.targets\.sdist\](.*?)(?=\n\[|\Z)', txt, flags=re.DOTALL)
    assert m, "pyproject 缺 [tool.hatch.build.targets.sdist] 段"
    body = m.group(1)
    for f in ("argos_agent", "README.md", "LICENSE", "CHANGELOG.md",
              "packaging/VERSION", "packaging/Info.plist", "packaging/argos.spec"):
        assert f in body, f"[tool.hatch.build.targets.sdist.include] 缺 {f}"
    # exclude 也得有(在 body 内)
    assert re.search(r'exclude\s*=\s*\[(.*?)\]', body, flags=re.DOTALL), \
        "pyproject [tool.hatch.build.targets.sdist.exclude] 缺"
    exclude_match = re.search(r'exclude\s*=\s*\[(.*?)\]', body, flags=re.DOTALL)
    exclude = exclude_match.group(1)
    for ex in ("tests", "build", "dist", "docs", ".venv", ".coverage"):
        assert ex in exclude, f"[tool.hatch.build.targets.sdist.exclude] 缺 {ex}"


# --- T2 part 2:argospkg dispatcher ---

def test_argospkg_pkg_file_exists():
    assert CLI_PKG.exists(), f"缺 {CLI_PKG}"


def test_argospkg_info_prints_metadata():
    """`argospkg info` 退出 0,stdout 含 name/version/pkg/VERSION。"""
    r = subprocess.run(
        [sys.executable, "-m", "argos_agent.cli.pkg", "info"],
        capture_output=True, text=True, cwd=str(ROOT), timeout=30,
    )
    assert r.returncode == 0, f"argospkg info 返 {r.returncode};stderr={r.stderr}"
    out = r.stdout
    assert "name:        argos-agent" in out, f"stdout 缺 name;got:\n{out}"
    assert "version:" in out
    assert "pkg/VERSION:" in out


def test_argospkg_check_imports_cleanly():
    """`argospkg check` 退出 0,stdout 含 'import OK'。"""
    r = subprocess.run(
        [sys.executable, "-m", "argos_agent.cli.pkg", "check"],
        capture_output=True, text=True, cwd=str(ROOT), timeout=30,
    )
    assert r.returncode == 0, f"argospkg check 返 {r.returncode};stderr={r.stderr}"
    assert "import OK" in r.stdout, f"stdout 缺 'import OK';got:\n{r.stdout}"


def test_argospkg_unknown_subcommand_exits_nonzero():
    """`argospkg foo` 退出非 0(2),stderr 含 'unknown subcommand'。"""
    r = subprocess.run(
        [sys.executable, "-m", "argos_agent.cli.pkg", "foo"],
        capture_output=True, text=True, cwd=str(ROOT), timeout=30,
    )
    assert r.returncode != 0
    assert "unknown subcommand" in r.stderr


def test_argospkg_manifest_lists_winget_dir():
    """`argospkg manifest` 退出 0,列 packaging/winget/ 文件(若存在)。"""
    r = subprocess.run(
        [sys.executable, "-m", "argos_agent.cli.pkg", "manifest"],
        capture_output=True, text=True, cwd=str(ROOT), timeout=30,
    )
    assert r.returncode == 0, f"argospkg manifest 返 {r.returncode};stderr={r.stderr}"
    # 不强制 winget 文件存在(本期任务 T8 后才有),但 stdout 必含 manifest 提示
    assert "manifest" in r.stdout.lower()


def test_argospkg_help_prints_usage():
    """`--help` 返 0 + 显 usage;无参 返 1 + 显 usage(用户调用方式提示)。"""
    r = subprocess.run(
        [sys.executable, "-m", "argos_agent.cli.pkg", "--help"],
        capture_output=True, text=True, cwd=str(ROOT), timeout=30,
    )
    assert r.returncode == 0, f"--help 返 {r.returncode};stderr={r.stderr}"
    assert "usage: argospkg" in r.stdout

    r2 = subprocess.run(
        [sys.executable, "-m", "argos_agent.cli.pkg"],
        capture_output=True, text=True, cwd=str(ROOT), timeout=30,
    )
    # 无参 dispatch 返 1(告诉用户"请给子命令"),但 usage 仍打印
    assert r2.returncode == 1, f"无参期望 1,实得 {r2.returncode}"
    assert "usage: argospkg" in r2.stdout


# --- T10 part 3:publish.yml 结构 ---

def test_publish_workflow_exists_and_uses_pypa_action():
    """publish.yml 存在 + 含 pypa/gh-action-pypi-publish@release/v1 + id-token: write。"""
    if not PUBLISH_YML.exists():
        pytest.skip("publish.yml 尚未创建(plan T10 任务) — skip 早期 commit")
    txt = PUBLISH_YML.read_text()
    assert "pypa/gh-action-pypi-publish" in txt, "publish.yml 缺 pypa/gh-action-pypi-publish"
    assert "@release/v1" in txt, "publish.yml pin 错(应 @release/v1)"
    assert "id-token: write" in txt, "publish.yml 缺 id-token: write(OIDC)"


# --- 验收:uv build 跑通(契约 §4.4;spec §1.4 锁"uv build 必须能出")---

def test_uv_build_dry_run_succeeds():
    """`uv build` 能出 wheel + sdist(契约 §4.4 端到端铁证)。"""
    r = subprocess.run(
        ["uv", "build"],
        capture_output=True, text=True, cwd=str(ROOT), timeout=300,
    )
    assert r.returncode == 0, f"uv build 失败(rc={r.returncode});stderr={r.stderr}\nstdout={r.stdout[:500]}"
    dist = ROOT / "dist"
    assert dist.exists(), "uv build 后缺 dist/"
    whl = list(dist.glob("*.whl"))
    sdist = list(dist.glob("*.tar.gz"))
    assert whl, f"dist/ 无 .whl;有:{list(dist.iterdir())}"
    assert sdist, f"dist/ 无 .tar.gz;有:{list(dist.iterdir())}"
    # 名字符合 spec §4.4(hatch 把 `argos-agent` 规整为 `argos_agent` 文件名)
    assert whl[0].name.startswith("argos_agent-"), f"wheel 名字错:{whl[0].name}"
    assert sdist[0].name.startswith("argos_agent-"), f"sdist 名字错:{sdist[0].name}"


def test_pip_install_wheel_and_run_argos_version():
    """uv build 出来的 wheel,临时 venv pip install + 跑 argos --version(契约 §4.4 端到端)。

    走 `uv venv` 拿带 pip 的 venv(uv venv 默认带 pip;stdlib venv.create + ensurepip 在
    沙箱下偶发 SIGABRT,这是本地沙箱已知问题,不是产品 bug)。
    """
    whl = list((ROOT / "dist").glob("*.whl"))
    if not whl:
        pytest.skip("无 wheel 可测(先跑 test_uv_build_dry_run_succeeds)")
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        venv_dir = Path(td) / "venv"
        # 走 uv venv 拿带 pip 的 venv
        r_uv = subprocess.run(
            ["uv", "venv", str(venv_dir), "--python", sys.executable],
            capture_output=True, text=True, timeout=120,
        )
        assert r_uv.returncode == 0, f"uv venv 失败;stderr={r_uv.stderr}"
        py = venv_dir / "bin" / "python"
        # 装
        r = subprocess.run(
            ["uv", "pip", "install", "--python", str(py), str(whl[0])],
            capture_output=True, text=True, timeout=300,
        )
        assert r.returncode == 0, f"uv pip install 失败;stderr={r.stderr}"
        # argos --version
        r2 = subprocess.run(
            [str(venv_dir / "bin" / "argos"), "--version"],
            capture_output=True, text=True, timeout=30,
        )
        assert r2.returncode == 0, f"argos --version 返 {r2.returncode};stderr={r2.stderr}"
        assert "0.1.0" in r2.stdout, f"--version 缺 0.1.0;got:{r2.stdout}"
        # argospkg 应该也在
        argospkg = venv_dir / "bin" / "argospkg"
        assert argospkg.exists(), f"argospkg 不在 venv bin:{list((venv_dir / 'bin').iterdir())}"
