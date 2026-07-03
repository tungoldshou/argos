import subprocess

from argos.core.loop import _git_status_snapshot, _env_context


def test_git_status_empty_for_non_git_dir(tmp_path):
    assert _git_status_snapshot(tmp_path) == ""


def test_git_status_snapshot_for_git_dir(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "f.txt").write_text("x")
    out = _git_status_snapshot(tmp_path)
    assert "##" in out
    assert "f.txt" in out


def test_env_context_omits_git_block_for_non_git_dir(tmp_path):
    block = _env_context(tmp_path)
    assert "<environment>" in block
    assert "<git_status>" not in block
