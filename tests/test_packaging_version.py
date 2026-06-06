"""packaging/VERSION 文件存在 + 内容是 x.y.z + 与 git tag 一致。"""
import re
import subprocess
from pathlib import Path

import pytest

VERSION_FILE = Path(__file__).parent.parent / "packaging" / "VERSION"


def test_version_file_exists():
    assert VERSION_FILE.exists(), f"缺少 {VERSION_FILE}"


def test_version_file_format():
    """版本号必须是 x.y.z(可后缀 -rc1 等),写明校验。"""
    text = VERSION_FILE.read_text().strip()
    assert re.match(r"^\d+\.\d+\.\d+(-[a-zA-Z0-9.]+)?$", text), (
        f"VERSION 内容 '{text}' 不符合 x.y.z 格式"
    )


def test_version_matches_git_tag():
    """如果当前 commit 有 v* tag,VERSION 必须与 tag 一致。"""
    text = VERSION_FILE.read_text().strip()
    try:
        tag = subprocess.check_output(
            ["git", "describe", "--tags", "--exact-match"],
            cwd=VERSION_FILE.parent.parent,
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except subprocess.CalledProcessError:
        pytest.skip("当前 commit 无 tag,跳过(开发分支常态)")
    if tag.startswith("v"):
        assert text == tag[1:], f"VERSION ({text}) != git tag ({tag})"
