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
    """必须用 softprops/action-gh-release@v2 上传 tarball + SHA256SUMS。

    加强:解析 tarball 命名(从 pack 步的 `tar czf`)vs upload glob(从 files:),
    断言命名一致(防止 v-prefix 错位再发生)。
    """
    import re

    import yaml
    data = yaml.safe_load(WORKFLOW.read_text())
    job = data["jobs"]["release"]
    steps_text = yaml.dump(job["steps"])
    assert "softprops/action-gh-release" in steps_text
    assert "tar.gz" in steps_text
    assert "SHA256SUMS" in steps_text or "sha256sums" in steps_text.lower()

    # 定位 pack step(run 含 `tar czf`)
    pack_step = next(
        (s for s in job["steps"] if "tar czf" in str(s.get("run", ""))),
        None,
    )
    assert pack_step is not None, "找不到 pack step(tar czf)"
    pack_run = str(pack_step["run"])

    # 从 `tar czf "<name>.tar.gz"` 提取命名
    pack_names = set(re.findall(r'tar\s+czf\s+"([^"]+\.tar\.gz)"', pack_run))
    assert pack_names, "找不到 pack step 的 tarball 命名"

    # 解析 pack run 里的 `VAR=...` 赋值,用于把 ${VAR} 在 pack name 里展开
    # (例:VERSION="${ARGOS_VERSION#v}" → ${VERSION} 替成 ${ARGOS_VERSION#v})
    def resolve_pack_name(name: str) -> str:
        for m in re.finditer(r"^(\w+)=(\"[^\"]*\"|'[^']*'|\S+)", pack_run, re.MULTILINE):
            var, val = m.group(1), m.group(2)
            if (val.startswith('"') and val.endswith('"')) or (
                val.startswith("'") and val.endswith("'")
            ):
                val = val[1:-1]
            name = name.replace(f"${{{var}}}", val)
        return name

    resolved_names = {resolve_pack_name(n) for n in pack_names}

    # 解析 upload files: globs
    upload_files: set[str] = set()
    for step in job["steps"]:
        files = (step.get("with") or {}).get("files", "")
        if files:
            for line in files.splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    upload_files.add(line)

    # 解析后 pack 命名的 basename 必须出现在 upload files 里
    for name in resolved_names:
        basename = Path(name).name
        assert any(basename in f for f in upload_files), (
            f"pack step 命名 {basename!r} (resolved from {name!r}) "
            f"不在 upload files {upload_files!r} 中"
        )
