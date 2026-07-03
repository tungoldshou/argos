from __future__ import annotations

import pytest

from argos.permissions.secrets import (
    MAX_SCAN_BYTES,
    SECRET_PATTERNS,
    find_secret_in_content,
)


def test_secret_patterns_count_is_9():
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
    content = "EXAMPLE_AWS_KEY=AKIAIOSFODNN7EXAMPLE"
    assert find_secret_in_content(content) == "AWS access key"


def test_env_example_not_scanned():
    content = "EXAMPLE_AWS_KEY=AKIAIOSFODNN7EXAMPLE"
    assert find_secret_in_content(content) is not None


def test_normal_content_not_flagged():
    assert find_secret_in_content("hello world\nprint(1+1)\n") is None


def test_large_content_skipped():
    big = "a" * (MAX_SCAN_BYTES + 100)
    assert find_secret_in_content(big) is None


def test_edit_file_scans_new_content():
    new_content = "AKIAIOSFODNN7EXAMPLE"   # new
    assert find_secret_in_content(new_content) == "AWS access key"
