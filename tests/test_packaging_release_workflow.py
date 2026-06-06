"""打包 C 阶段 — release.yml / publish.yml 工作流结构测试(plan T10)。"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
RELEASE_YML = ROOT / ".github" / "workflows" / "release.yml"


def test_release_workflow_pins_setup_python_v4():
    """release.yml pin `actions/setup-python@v4` 修 v0.1.0 时的 0 jobs bug。"""
    txt = RELEASE_YML.read_text()
    # 不应有 @v5
    assert "actions/setup-python@v5" not in txt, "release.yml 仍用 @v5(0 jobs bug 没修)"
    # 应有 @v4
    assert "actions/setup-python@v4" in txt, "release.yml 缺 actions/setup-python@v4 pin"


def test_release_workflow_has_three_os_jobs():
    """release.yml 必含 build-macos + build-linux + build-windows 3 job。"""
    txt = RELEASE_YML.read_text()
    for job in ("build-macos:", "build-linux:", "build-windows:"):
        assert job in txt, f"release.yml 缺 {job}"


def test_release_workflow_uses_gh_release_create():
    """release.yml 用 `gh release create` 替换 softprops(action-gh-release@v2)。

    注:`uses:` 行才会真引 action;注释里出现 'softprops' 是历史溯源(spec §10 锁)。
    """
    txt = RELEASE_YML.read_text()
    assert "gh release create" in txt, "release.yml 缺 gh release create(仍用 softprops?)"
    # 只在 uses: 行查 softprops(注释允许)
    for line in txt.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("uses:") or stripped.startswith("- uses:"):
            assert "softprops" not in line, \
                f"release.yml 仍 uses: softprops(line: {line!r})"


def test_release_workflow_no_softprops_action_uses():
    """显式断言:任何 `uses:` 行都不引 softprops(注释除外)。"""
    txt = RELEASE_YML.read_text()
    for line in txt.splitlines():
        s = line.lstrip()
        if s.startswith("uses:") or s.startswith("- uses:"):
            assert "softprops" not in line, f"uses: 仍引 softprops:{line!r}"


def test_release_workflow_uses_setup_uv_v4():
    """release.yml pin `astral-sh/setup-uv@v4` 跟 v0.1.0 一致。"""
    txt = RELEASE_YML.read_text()
    assert "astral-sh/setup-uv@v4" in txt


def test_release_workflow_triggers_on_v_tag():
    """release.yml on: push: tags: 'v*'(v0.1.0 锁过的不动)。"""
    txt = RELEASE_YML.read_text()
    assert "tags:" in txt
    assert "'v*'" in txt or '"v*"' in txt
