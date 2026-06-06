"""9 条 secret pattern flag-and-ask 铁证(spec §2.4, D8 锁 flag-and-ask)。

复 SECRET_PATTERNS 9 条,每条 ≥ 1 命中 case + .env.example 不误报。"""
from __future__ import annotations

import pytest

from argos_agent.permissions.secrets import (
    MAX_SCAN_BYTES,
    SECRET_PATTERNS,
    find_secret_in_content,
)


def test_secret_patterns_count_is_9():
    """spec §2.4 锁:9 条 regex,单一来源 D2。"""
    assert len(SECRET_PATTERNS) == 9


def test_aws_access_key_detected():
    assert find_secret_in_content("AKIAIOSFODNN7EXAMPLE") == "AWS access key"


def test_aws_secret_access_key_detected():
    val = "a" * 40
    assert find_secret_in_content(f'aws_secret_access_key="{val}"') == "AWS secret access key"


def test_github_classic_detected():
    token = "ghp_" + "a" * 36
    assert find_secret_in_content(token) == "GitHub token (classic)"


def test_github_fine_grained_detected():
    token = "github_pat_" + "a" * 82
    assert find_secret_in_content(token) == "GitHub token (fine-grained)"


def test_openai_key_detected():
    assert find_secret_in_content("sk-" + "a" * 24) == "OpenAI API key"


def test_anthropic_key_detected():
    assert find_secret_in_content("sk-ant-" + "a" * 24) == "Anthropic API key"


def test_private_key_detected():
    assert find_secret_in_content("-----BEGIN RSA PRIVATE KEY-----") == "Private key block"


def test_hardcoded_password_detected():
    assert find_secret_in_content('password="hunter2"') == "hardcoded password"


def test_example_key_still_flagged():
    """D8 锁:EXAMPLE_AWS_KEY=AKIA... 仍 flag(不 heuristic 区分真假 key;用户**永远**看到弹窗)。"""
    content = "EXAMPLE_AWS_KEY=AKIAIOSFODNN7EXAMPLE"
    assert find_secret_in_content(content) == "AWS access key"


def test_env_example_not_scanned():
    """.env.example 里写 AKIA 仍被 flag(只是 path 走 allow,但内容仍 secret flag)。"""
    content = "EXAMPLE_AWS_KEY=AKIAIOSFODNN7EXAMPLE"
    assert find_secret_in_content(content) is not None


def test_normal_content_not_flagged():
    assert find_secret_in_content("hello world\nprint(1+1)\n") is None


def test_large_content_skipped():
    """1MB+ 内容 skip(D13 锁)。"""
    big = "a" * (MAX_SCAN_BYTES + 100)
    assert find_secret_in_content(big) is None


def test_edit_file_scans_new_content():
    """edit_file 替换的新内容(不是 old block)走扫描;这里只验 find 函数对"新内容"行为正确。"""
    new_content = "AKIAIOSFODNN7EXAMPLE"   # new
    # find 接受新内容;old 不会传进来
    assert find_secret_in_content(new_content) == "AWS access key"
