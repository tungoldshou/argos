"""#6 CC对齐:run 起始的 git 状态快照(_git_status_snapshot)。
非 git 目录 → 静默空(不阻断);git 目录 → 含分支行 + 变更文件;capped 防爆。"""
import subprocess

from argos.core.loop import _git_status_snapshot, _env_context


def test_git_status_empty_for_non_git_dir(tmp_path):
    assert _git_status_snapshot(tmp_path) == ""        # 非 git 仓库 → 静默空


def test_git_status_snapshot_for_git_dir(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "f.txt").write_text("x")
    out = _git_status_snapshot(tmp_path)
    assert "##" in out                                  # --branch 行(## No commits yet ...)
    assert "f.txt" in out                               # --short 列出未跟踪文件


def test_env_context_omits_git_block_for_non_git_dir(tmp_path):
    # 非 git 目录:environment 块在,但不应混进 <git_status> 块(否则系统提示词测试会漂)。
    block = _env_context(tmp_path)
    assert "<environment>" in block
    assert "<git_status>" not in block
