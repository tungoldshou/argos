"""GitHub Actions release workflow YAML 语法校验。"""
import subprocess
from pathlib import Path

import pytest

WORKFLOW = Path(__file__).parent.parent / ".github" / "workflows" / "release.yml"


def test_workflow_exists():
    assert WORKFLOW.exists(), f"缺少 {WORKFLOW}"


def test_workflow_yaml_valid():
    """用 PyYAML 解析确认语法。"""
    import yaml
    with WORKFLOW.open() as f:
        try:
            data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            pytest.fail(f"YAML 解析失败: {e}")
    assert isinstance(data, dict), "workflow 必须是 dict"
    assert "jobs" in data, "缺少 jobs"
    assert "release" in data["jobs"], "缺少 release job"
    job = data["jobs"]["release"]
    # macos arm64 runner
    assert "macos-14" in job.get("runs-on", "") or "macos-latest" in job.get("runs-on", ""), (
        f"runs-on 必须是 macOS arm64,实际 {job.get('runs-on')}"
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


def test_workflow_uploads_assets():
    """必须用 softprops/action-gh-release@v2 上传 tarball + SHA256SUMS。"""
    import yaml
    data = yaml.safe_load(WORKFLOW.read_text())
    job = data["jobs"]["release"]
    steps_text = yaml.dump(job["steps"])
    assert "softprops/action-gh-release" in steps_text
    assert "tar.gz" in steps_text
    assert "SHA256SUMS" in steps_text or "sha256sums" in steps_text.lower()
