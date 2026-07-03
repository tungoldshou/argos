import re
import subprocess
from pathlib import Path

import pytest

WORKFLOW = Path(__file__).parent.parent / ".github" / "workflows" / "release.yml"


def test_workflow_exists():
    assert WORKFLOW.exists(), f"缺少 {WORKFLOW}"


def test_workflow_yaml_valid():
    import yaml
    with WORKFLOW.open() as f:
        try:
            data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            pytest.fail(f"YAML 解析失败: {e}")
    assert isinstance(data, dict), "workflow 必须是 dict"
    assert "jobs" in data, "缺少 jobs"
    for job in ("build-macos", "build-linux", "build-windows"):
        assert job in data["jobs"], f"缺 {job} job(plan T10 锁 3 OS 矩阵)"
    assert "release" in data["jobs"], "缺 release job"
    job = data["jobs"]["release"]
    assert "ubuntu" in job.get("runs-on", ""), (
        f"release job 应在 ubuntu-latest(免 macos minutes);实际 {job.get('runs-on')}"
    )
    needs = job.get("needs", [])
    assert {"build-macos", "build-linux", "build-windows"} <= set(needs), (
        f"release job needs 缺 3 build 之一;实际 {needs}"
    )


def test_workflow_is_manual_for_binary_release():
    import yaml
    data = yaml.safe_load(WORKFLOW.read_text())
    triggers = data.get(True, data.get("on", {}))
    assert "workflow_dispatch" in triggers, "缺少 manual trigger"
    assert "push" not in triggers, "binary release workflow 不应由 tag push 自动触发"


def test_workflow_uses_gh_release_create_not_softprops():
    import yaml
    data = yaml.safe_load(WORKFLOW.read_text())
    job = data["jobs"]["release"]
    steps_text = yaml.dump(job["steps"])
    assert "gh release create" in steps_text, "release job 缺 gh release create"
    for step in job["steps"]:
        uses = (step.get("uses") or "")
        assert "softprops" not in uses, f"仍 uses: softprops:{uses}"


def test_workflow_uploads_assets_via_gh_release_create():
    import yaml
    data = yaml.safe_load(WORKFLOW.read_text())
    job = data["jobs"]["release"]
    release_step = next(
        (s for s in job["steps"] if "gh release create" in str(s.get("run", ""))),
        None,
    )
    assert release_step is not None, "release job 缺 gh release create 步"
    run = str(release_step["run"])
    assert "dist/release-assets.txt" in run
    assert "printf '%s\\n' \"$ASSETS\"" in run
    for glob in ("*.tar.gz", "*.AppImage", "*.deb", "*.rpm", "*.zip", "*.msi.zip"):
        assert glob not in run, f"gh release create 不应再用宽泛 glob:{glob}"
    assert "--generate-notes" in run, "缺 --generate-notes"
    assert "Argos v" in run, "缺 release title 'Argos v${VERSION}'"
