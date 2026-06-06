"""GitHub Actions release workflow YAML 语法校验(plan #13 C 阶段重写)。

C 阶段把 release.yml 从 1 个 macOS job 扩到 3 OS 矩阵(macos + linux + windows),
并把 `softprops/action-gh-release@v2` 替换为 `gh release create` shell(修 v0.1.0 时
发现的 0 jobs bug)。本测试断言新结构合法。
"""
import re
import subprocess
from pathlib import Path

import pytest

WORKFLOW = Path(__file__).parent.parent / ".github" / "workflows" / "release.yml"


def test_workflow_exists():
    assert WORKFLOW.exists(), f"缺少 {WORKFLOW}"


def test_workflow_yaml_valid():
    """用 PyYAML 解析确认语法 + 3 OS 矩阵 + release job 用 ubuntu-latest(非 macos-14)。"""
    import yaml
    with WORKFLOW.open() as f:
        try:
            data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            pytest.fail(f"YAML 解析失败: {e}")
    assert isinstance(data, dict), "workflow 必须是 dict"
    assert "jobs" in data, "缺少 jobs"
    # 3 OS 矩阵 job
    for job in ("build-macos", "build-linux", "build-windows"):
        assert job in data["jobs"], f"缺 {job} job(plan T10 锁 3 OS 矩阵)"
    # release job 跑在 ubuntu-latest(免 macos minutes 贵,仅需 gh CLI)
    assert "release" in data["jobs"], "缺 release job"
    job = data["jobs"]["release"]
    assert "ubuntu" in job.get("runs-on", ""), (
        f"release job 应在 ubuntu-latest(免 macos minutes);实际 {job.get('runs-on')}"
    )
    # release job 必依赖 3 build
    needs = job.get("needs", [])
    assert set(needs) == {"build-macos", "build-linux", "build-windows"}, (
        f"release job needs 必须是 3 build;实际 {needs}"
    )


def test_workflow_triggers_on_tag():
    """必须响应 v* tag 推送。"""
    import yaml
    data = yaml.safe_load(WORKFLOW.read_text())
    triggers = data.get(True, data.get("on", {}))  # YAML 'on' 解析为 True
    assert "push" in triggers, "缺少 push trigger"
    assert "tags" in triggers["push"], "缺少 tags"
    assert any("v*" in t for t in triggers["push"]["tags"]), (
        f"tag pattern 必须含 v*: {triggers['push']['tags']}"
    )


def test_workflow_uses_gh_release_create_not_softprops():
    """release job 走 `gh release create` shell(替换 softprops/action-gh-release@v2;
    修 v0.1.0 时发现的 0 jobs bug)。
    """
    import yaml
    data = yaml.safe_load(WORKFLOW.read_text())
    job = data["jobs"]["release"]
    steps_text = yaml.dump(job["steps"])
    assert "gh release create" in steps_text, "release job 缺 gh release create"
    # 不应再 uses: softprops
    for step in job["steps"]:
        uses = (step.get("uses") or "")
        assert "softprops" not in uses, f"仍 uses: softprops:{uses}"


def test_workflow_uploads_assets_via_gh_release_create():
    """release job 通过 gh release create 把 3 OS build 产出的资产都上传。

    校验:gh release create 步骤的 run 含跨 OS 资产 glob(tar.gz / AppImage /
    deb / rpm / zip / msi.zip / SHA256SUMS)。
    """
    import yaml
    data = yaml.safe_load(WORKFLOW.read_text())
    job = data["jobs"]["release"]
    # 找 gh release create 步
    release_step = next(
        (s for s in job["steps"] if "gh release create" in str(s.get("run", ""))),
        None,
    )
    assert release_step is not None, "release job 缺 gh release create 步"
    run = str(release_step["run"])
    # 跨 OS 资产 glob 必含
    for ext in ("*.tar.gz", "*.AppImage", "*.deb", "*.rpm", "*.zip", "SHA256SUMS"):
        assert ext in run, f"gh release create 缺 {ext} glob"
    # 必含 --generate-notes(spec §10.2)
    assert "--generate-notes" in run, "缺 --generate-notes"
    # 必含 title "Argos v${VERSION}"
    assert "Argos v" in run, "缺 release title 'Argos v${VERSION}'"
