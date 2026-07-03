"""Internal documentation."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
PYPROJECT = ROOT / "pyproject.toml"
CLI_PKG = ROOT / "argos" / "cli" / "pkg.py"
PUBLISH_YML = ROOT / ".github" / "workflows" / "publish.yml"


def _project_version() -> str:
    match = re.search(r'^version = "([^"]+)"', PYPROJECT.read_text(), re.M)
    assert match
    return match.group(1)



def test_pyproject_has_license_mit():
    """Internal documentation."""
    txt = PYPROJECT.read_text()
    assert re.search(r'license\s*=\s*\{\s*text\s*=\s*"MIT"\s*\}', txt), (
        f"pyproject 缺 license = {{text = 'MIT'}};got:\n{txt[txt.find('license'):txt.find('license')+80]}"
    )


def test_pyproject_has_authors_with_email():
    """Internal documentation."""
    txt = PYPROJECT.read_text()
    m = re.search(r'authors\s*=\s*\[(.*?)\]', txt, flags=re.DOTALL)
    assert m, "pyproject 缺 [project.authors] 段"
    body = m.group(1)
    assert "email" in body, f"[project.authors] 缺 email:{body[:200]}"
    assert "tungoldshou" in body


def test_pyproject_has_classifiers_list():
    """Internal documentation."""
    txt = PYPROJECT.read_text()
    m = re.search(r'classifiers\s*=\s*\[(.*?)\]', txt, flags=re.DOTALL)
    assert m, "pyproject 缺 [project.classifiers] 段"
    body = m.group(1)
    assert "License :: OSI Approved :: MIT License" in body
    assert "Programming Language :: Python :: 3.12" in body
    assert "Operating System :: POSIX :: Linux" in body
    assert "Operating System :: Microsoft :: Windows :: Windows 10" in body


def test_pyproject_has_urls_section():
    """Internal documentation."""
    txt = PYPROJECT.read_text()
    m = re.search(r'\[project\.urls\](.*?)(?=\n\[|\Z)', txt, flags=re.DOTALL)
    assert m, "pyproject 缺 [project.urls] 段"
    body = m.group(1)
    for k in ("Homepage", "Repository", "Issues", "Changelog"):
        assert k in body, f"[project.urls] 缺 {k};got:\n{body[:200]}"


def test_pyproject_scripts_contains_argos_and_argospkg():
    """Internal documentation."""
    txt = PYPROJECT.read_text()
    m = re.search(r'\[project\.scripts\](.*?)(?=\n\[|\Z)', txt, flags=re.DOTALL)
    assert m, "pyproject 缺 [project.scripts] 段"
    body = m.group(1)
    assert re.search(r'^\s*argos\s*=\s*"argos\.__main__:main"', body, re.M),\
        "缺 argos = argos.__main__:main"
    assert re.search(r'^\s*argospkg\s*=\s*"argos\.cli\.pkg:main"', body, re.M),\
        "缺 argospkg = argos.cli.pkg:main"


def test_pyproject_sdist_includes_critical_files():
    """Internal documentation."""
    txt = PYPROJECT.read_text()
    m = re.search(r'\[tool\.hatch\.build\.targets\.sdist\](.*?)(?=\n\[|\Z)', txt, flags=re.DOTALL)
    assert m, "pyproject 缺 [tool.hatch.build.targets.sdist] 段"
    body = m.group(1)
    for f in ("argos", "README.md", "LICENSE", "CHANGELOG.md",
              "packaging/VERSION", "packaging/Info.plist", "packaging/argos.spec"):
        assert f in body, f"[tool.hatch.build.targets.sdist.include] 缺 {f}"
    assert re.search(r'exclude\s*=\s*\[(.*?)\]', body, flags=re.DOTALL),\
        "pyproject [tool.hatch.build.targets.sdist.exclude] 缺"
    exclude_match = re.search(r'exclude\s*=\s*\[(.*?)\]', body, flags=re.DOTALL)
    exclude = exclude_match.group(1)
    for ex in ("tests", "build", "dist", "docs", ".venv", ".coverage"):
        assert ex in exclude, f"[tool.hatch.build.targets.sdist.exclude] 缺 {ex}"


# --- T2 part 2:argospkg dispatcher ---

def test_argospkg_pkg_file_exists():
    assert CLI_PKG.exists(), f"缺 {CLI_PKG}"


def test_argospkg_info_prints_metadata():
    """Internal documentation."""
    r = subprocess.run(
        [sys.executable, "-m", "argos.cli.pkg", "info"],
        capture_output=True, text=True, cwd=str(ROOT), timeout=30,
    )
    assert r.returncode == 0, f"argospkg info 返 {r.returncode};stderr={r.stderr}"
    out = r.stdout
    assert "name:        argos-agent" in out, f"stdout 缺 name;got:\n{out}"
    assert "version:" in out
    assert "pkg/VERSION:" in out


def test_argospkg_info_does_not_read_cwd_packaging_version(tmp_path, monkeypatch, capsys):
    """Internal documentation."""
    from argos.cli.pkg import cmd_info

    fake = tmp_path / "packaging"
    fake.mkdir()
    (fake / "VERSION").write_text("9.9.9\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert cmd_info([]) == 0
    out = capsys.readouterr().out
    assert "pkg/VERSION: 9.9.9" not in out
    assert f"pkg/VERSION: {_project_version()}" in out


def test_argospkg_check_imports_cleanly():
    """Internal documentation."""
    r = subprocess.run(
        [sys.executable, "-m", "argos.cli.pkg", "check"],
        capture_output=True, text=True, cwd=str(ROOT), timeout=30,
    )
    assert r.returncode == 0, f"argospkg check 返 {r.returncode};stderr={r.stderr}"
    assert "import OK" in r.stdout, f"stdout 缺 'import OK';got:\n{r.stdout}"


def test_argospkg_unknown_subcommand_exits_nonzero():
    """Internal documentation."""
    r = subprocess.run(
        [sys.executable, "-m", "argos.cli.pkg", "foo"],
        capture_output=True, text=True, cwd=str(ROOT), timeout=30,
    )
    assert r.returncode != 0
    assert "unknown subcommand" in r.stderr


def test_argospkg_manifest_lists_winget_dir():
    """Internal documentation."""
    r = subprocess.run(
        [sys.executable, "-m", "argos.cli.pkg", "manifest"],
        capture_output=True, text=True, cwd=str(ROOT), timeout=30,
    )
    assert "tungoldshou.argos.yaml" in r.stdout
    assert "tungoldshou.argos.installer.yaml" in r.stdout
    assert "tungoldshou.argos.locale.en-US.yaml" in r.stdout
    assert "placeholder" not in r.stdout.lower()
    assert "占位" not in r.stdout
    assert "v0.2.0" not in r.stdout.lower()


def test_argospkg_manifest_fails_on_placeholder_winget_digest():
    """Internal documentation."""
    r = subprocess.run(
        [sys.executable, "-m", "argos.cli.pkg", "manifest"],
        capture_output=True, text=True, cwd=str(ROOT), timeout=30,
    )
    installer = ROOT / "packaging" / "winget" / "tungoldshou.argos.installer.yaml"
    assert "PLACEHOLDER" in installer.read_text()
    assert r.returncode != 0
    assert "placeholder" in r.stderr.lower()


def test_argospkg_manifest_fails_on_invalid_winget_digest(tmp_path, monkeypatch, capsys):
    """Internal documentation."""
    from argos.cli.pkg import cmd_manifest

    src = ROOT / "packaging" / "winget"
    dst = tmp_path / "packaging" / "winget"
    dst.mkdir(parents=True)
    for p in src.glob("tungoldshou.argos*.yaml"):
        text = p.read_text()
        text = text.replace("PLACEHOLDER_FROM_BUMP", "not-a-real-sha")
        (dst / p.name).write_text(text)

    monkeypatch.chdir(tmp_path)
    assert cmd_manifest([]) == 1
    captured = capsys.readouterr()
    assert "InstallerSha256" in captured.err


def test_argospkg_manifest_fails_without_winget_dir(tmp_path, monkeypatch, capsys):
    """Internal documentation."""
    from argos.cli.pkg import cmd_manifest

    monkeypatch.chdir(tmp_path)
    assert cmd_manifest([]) == 1
    captured = capsys.readouterr()
    assert "packaging/winget" in captured.err


def test_argospkg_manifest_fails_when_required_winget_file_missing(tmp_path, monkeypatch, capsys):
    """Internal documentation."""
    from argos.cli.pkg import cmd_manifest

    dst = tmp_path / "packaging" / "winget"
    dst.mkdir(parents=True)
    (dst / "tungoldshou.argos.installer.yaml").write_text(
        "InstallerSha256: " + ("a" * 64) + "\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    assert cmd_manifest([]) == 1
    captured = capsys.readouterr()
    assert "tungoldshou.argos.yaml" in captured.err


def test_argospkg_help_prints_usage():
    """Internal documentation."""
    r = subprocess.run(
        [sys.executable, "-m", "argos.cli.pkg", "--help"],
        capture_output=True, text=True, cwd=str(ROOT), timeout=30,
    )
    assert r.returncode == 0, f"--help 返 {r.returncode};stderr={r.stderr}"
    assert "usage: argospkg" in r.stdout

    r2 = subprocess.run(
        [sys.executable, "-m", "argos.cli.pkg"],
        capture_output=True, text=True, cwd=str(ROOT), timeout=30,
    )
    assert r2.returncode == 1, f"无参期望 1,实得 {r2.returncode}"
    assert "usage: argospkg" in r2.stdout



def test_publish_workflow_exists_and_uses_pypa_action():
    """Internal documentation."""
    if not PUBLISH_YML.exists():
        pytest.skip("publish.yml 尚未创建(plan T10 任务) — skip 早期 commit")
    txt = PUBLISH_YML.read_text()
    assert "pypa/gh-action-pypi-publish" in txt, "publish.yml 缺 pypa/gh-action-pypi-publish"
    assert "@release/v1" in txt, "publish.yml pin 错(应 @release/v1)"
    assert "id-token: write" in txt, "publish.yml 缺 id-token: write(OIDC)"


def test_publish_workflow_does_not_ignore_twine_check_failure():
    """Internal documentation."""
    txt = PUBLISH_YML.read_text()
    assert "twine check dist/*" in txt
    assert "twine check dist/*  ||" not in txt
    assert "twine check dist/* ||" not in txt


def test_publish_workflow_cleans_dist_before_build():
    """Internal documentation."""
    txt = PUBLISH_YML.read_text()
    assert "run: rm -rf dist" in txt
    assert txt.index("run: rm -rf dist") < txt.index("run: uv build")


def test_publish_workflow_upload_artifact_fails_when_dist_is_empty():
    """Internal documentation."""
    txt = PUBLISH_YML.read_text()
    assert "actions/upload-artifact@v4" in txt
    assert "if-no-files-found: error" in txt


def test_publish_workflow_manual_dispatch_does_not_publish_to_pypi():
    """Internal documentation."""
    txt = PUBLISH_YML.read_text()
    assert "workflow_dispatch:" in txt
    assert "if: startsWith(github.ref, 'refs/tags/v')" in txt


def test_publish_workflow_manual_dispatch_publishes_to_testpypi_only():
    """Internal documentation."""
    txt = PUBLISH_YML.read_text()
    assert "  testpypi:" in txt
    testpypi_job = txt.split("  testpypi:", 1)[1].split("\n  pypi:", 1)[0]
    assert "needs: [test, build]" in testpypi_job
    assert "if: github.event_name == 'workflow_dispatch'" in testpypi_job
    assert "environment: testpypi" in testpypi_job
    assert "repository-url: https://test.pypi.org/legacy/" in testpypi_job
    assert "id-token: write" in testpypi_job


def test_publish_workflow_pypi_job_keeps_release_gates():
    """Internal documentation."""
    txt = PUBLISH_YML.read_text()
    pypi_job = txt.split("  pypi:", 1)[1]
    assert "needs: [test, build]" in pypi_job
    assert "environment: pypi" in pypi_job
    assert "id-token: write" in pypi_job


def test_publish_workflow_smokes_built_wheel_before_upload():
    """Internal documentation."""
    txt = PUBLISH_YML.read_text()
    smoke = (
        "uv run pytest tests/test_packaging_pypi.py::"
        "test_pip_install_wheel_and_run_argos_version -q --no-cov -m slow"
    )
    assert smoke in txt
    assert txt.index("run: uv build") < txt.index(smoke) < txt.index("actions/upload-artifact@v4")



def test_uv_build_dry_run_succeeds():
    """Internal documentation."""
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
    assert whl[0].name.startswith("argos_agent-"), f"wheel 名字错:{whl[0].name}"
    assert sdist[0].name.startswith("argos_agent-"), f"sdist 名字错:{sdist[0].name}"


@pytest.mark.slow
def test_pip_install_wheel_and_run_argos_version():
    """Internal documentation."""
    whl = list((ROOT / "dist").glob("*.whl"))
    if not whl:
        pytest.skip("无 wheel 可测(先跑 test_uv_build_dry_run_succeeds)")
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        venv_dir = Path(td) / "venv"
        r_uv = subprocess.run(
            ["uv", "venv", str(venv_dir), "--python", sys.executable],
            capture_output=True, text=True, timeout=120,
        )
        assert r_uv.returncode == 0, f"uv venv 失败;stderr={r_uv.stderr}"
        py = venv_dir / "bin" / "python"
        r = subprocess.run(
            ["uv", "pip", "install", "--python", str(py), str(whl[0])],
            capture_output=True, text=True, timeout=300,
        )
        if r.returncode != 0 and "Failed to fetch" in r.stderr and "timed out" in r.stderr:
            pytest.skip(f"pypi 不可达(本地网络/代理环境),跳过端到端安装:{r.stderr.splitlines()[-1]}")
        assert r.returncode == 0, f"uv pip install 失败;stderr={r.stderr}"
        # argos --version
        r2 = subprocess.run(
            [str(venv_dir / "bin" / "argos"), "--version"],
            capture_output=True, text=True, timeout=30,
        )
        assert r2.returncode == 0, f"argos --version 返 {r2.returncode};stderr={r2.stderr}"
        version = _project_version()
        assert version in r2.stdout, f"--version 缺 {version};got:{r2.stdout}"
        argospkg = venv_dir / "bin" / "argospkg"
        assert argospkg.exists(), f"argospkg 不在 venv bin:{list((venv_dir / 'bin').iterdir())}"
