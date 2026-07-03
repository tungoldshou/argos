"""Internal documentation."""
from __future__ import annotations

from pathlib import Path

import pytest

from argos.skills_runtime.builtin.security_review.secrets import (
    scan_file_for_secrets,
    SECRET_PATTERNS,
    SKIP_BASENAMES,
    DOWNGRADE_PATH_PATTERNS,
)



def test_all_nine_patterns_present():
    """Internal documentation."""
    assert len(SECRET_PATTERNS) == 9


def test_aws_access_key_detected(tmp_path):
    f = tmp_path / "config.py"
    f.write_text('aws_key = "AKIAIOSFODNN7EXAMPLE"\n')
    findings = scan_file_for_secrets(f, relpath="config.py", workspace=tmp_path)
    assert any(f.severity == "error" and "aws" in f.message.lower() for f in findings)


def test_aws_secret_detected(tmp_path):
    f = tmp_path / "config.py"
    f.write_text('aws_secret_access_key = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"\n')
    findings = scan_file_for_secrets(f, relpath="config.py", workspace=tmp_path)
    assert any(f.severity == "error" for f in findings)


def test_github_token_classic_detected(tmp_path):
    f = tmp_path / "leak.py"
    f.write_text('token = "ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789"\n')
    findings = scan_file_for_secrets(f, relpath="leak.py", workspace=tmp_path)
    assert any(f.severity == "error" and "github" in f.message.lower() for f in findings)


def test_github_token_fine_grained_detected(tmp_path):
    f = tmp_path / "leak.py"
    f.write_text(
        'token = "github_pat_11ABCDEFG0abcdefghijklmnopqrstuvwxyz0123456789'
        'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"\n'
    )
    findings = scan_file_for_secrets(f, relpath="leak.py", workspace=tmp_path)
    assert any(f.severity == "error" and "github" in f.message.lower() for f in findings)


def test_openai_key_detected(tmp_path):
    f = tmp_path / "leak.py"
    f.write_text('key = "sk-aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789"\n')
    findings = scan_file_for_secrets(f, relpath="leak.py", workspace=tmp_path)
    assert any(f.severity == "error" and "openai" in f.message.lower() for f in findings)


def test_openai_proj_key_detected(tmp_path):
    """Internal documentation."""
    f = tmp_path / "leak.py"
    f.write_text(
        'OPENAI_API_KEY = "sk-proj-aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789-_aBcDe"\n'
    )
    findings = scan_file_for_secrets(f, relpath="leak.py", workspace=tmp_path)
    assert any(f.severity == "error" and "openai" in f.message.lower() for f in findings), (
        f"modern sk-proj- key not detected; findings={[f.message for f in findings]}"
    )


def test_anthropic_key_detected_d4_new(tmp_path):
    """Internal documentation."""
    f = tmp_path / "leak.py"
    f.write_text('ANTHROPIC_API_KEY = "sk-ant-api03-aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789"\n')
    findings = scan_file_for_secrets(f, relpath="leak.py", workspace=tmp_path)
    assert any(f.severity == "error" and "anthropic" in f.message.lower() for f in findings)


def test_private_key_block_detected(tmp_path):
    f = tmp_path / "leak.py"
    f.write_text('-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAK...\n-----END RSA PRIVATE KEY-----\n')
    findings = scan_file_for_secrets(f, relpath="leak.py", workspace=tmp_path)
    assert any(f.severity == "error" and "private key" in f.message.lower() for f in findings)


def test_env_file_committed_warning(tmp_path):
    """Internal documentation."""
    f = tmp_path / ".env"
    f.write_text("FOO=bar\n")
    findings = scan_file_for_secrets(f, relpath=".env", workspace=tmp_path)
    assert any(f.severity == "warning" for f in findings)


def test_hardcoded_password_warning(tmp_path):
    """Internal documentation."""
    f = tmp_path / "cfg.py"
    f.write_text('password = "hunter2hunter2"\n')
    findings = scan_file_for_secrets(f, relpath="cfg.py", workspace=tmp_path)
    assert any(f.severity == "warning" and "password" in f.message.lower() for f in findings)



def test_dotenv_file_skipped(tmp_path):
    """Internal documentation."""
    f = tmp_path / ".env"
    f.write_text('ANTHROPIC_API_KEY = "sk-ant-api03-aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789"\n')
    findings = scan_file_for_secrets(f, relpath=".env", workspace=tmp_path)
    assert len(findings) == 1
    assert findings[0].severity == "warning"
    assert "committed" in findings[0].message.lower()
    assert not any("anthropic" in f.message.lower() for f in findings)


def test_dotenv_local_skipped(tmp_path):
    """Internal documentation."""
    f = tmp_path / ".env.local"
    f.write_text('ANTHROPIC_API_KEY = "sk-ant-api03-aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789"\n')
    findings = scan_file_for_secrets(f, relpath=".env.local", workspace=tmp_path)
    assert findings == ()


def test_secrets_toml_skipped(tmp_path):
    """Internal documentation."""
    f = tmp_path / "secrets.toml"
    f.write_text('aws_key = "AKIAIOSFODNN7EXAMPLE"\n')
    findings = scan_file_for_secrets(f, relpath="secrets.toml", workspace=tmp_path)
    assert findings == ()


def test_pem_file_skipped(tmp_path):
    """Internal documentation."""
    f = tmp_path / "server.pem"
    f.write_text('-----BEGIN RSA PRIVATE KEY-----\nfoo\n-----END RSA PRIVATE KEY-----\n')
    findings = scan_file_for_secrets(f, relpath="server.pem", workspace=tmp_path)
    assert findings == ()


def test_key_file_skipped(tmp_path):
    """Internal documentation."""
    f = tmp_path / "server.key"
    f.write_text('-----BEGIN RSA PRIVATE KEY-----\nfoo\n-----END RSA PRIVATE KEY-----\n')
    findings = scan_file_for_secrets(f, relpath="server.key", workspace=tmp_path)
    assert findings == ()



def test_tests_fixtures_downgraded_to_info(tmp_path):
    """Internal documentation."""
    f = tmp_path / "tests" / "fixtures" / "secret.txt"
    f.parent.mkdir(parents=True)
    f.write_text('aws_key = "AKIAIOSFODNN7EXAMPLE"\n')
    findings = scan_file_for_secrets(f, relpath="tests/fixtures/secret.txt", workspace=tmp_path)
    assert any(f.severity == "info" for f in findings)
    assert all(f.severity != "error" for f in findings)


def test_env_example_not_warned(tmp_path):
    """Internal documentation."""
    f = tmp_path / ".env.example"
    f.write_text("FOO=bar\n")
    findings = scan_file_for_secrets(f, relpath=".env.example", workspace=tmp_path)
    assert not any("committed" in f.message.lower() for f in findings)



def test_binary_file_skipped_silently(tmp_path):
    """Internal documentation."""
    f = tmp_path / "blob.bin"
    f.write_bytes(b"\x00\x01\xff\xfe")
    findings = scan_file_for_secrets(f, relpath="blob.bin", workspace=tmp_path)
    assert findings == ()


def test_oversize_file_skipped(tmp_path):
    """Internal documentation."""
    f = tmp_path / "big.py"
    f.write_text("# header\n" + "x = 1\n" * 200_000)
    findings = scan_file_for_secrets(f, relpath="big.py", workspace=tmp_path)
    assert findings == ()


def test_findings_have_required_fields(tmp_path):
    """Internal documentation."""
    f = tmp_path / "leak.py"
    f.write_text('token = "ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789"\n')
    findings = scan_file_for_secrets(f, relpath="leak.py", workspace=tmp_path)
    assert len(findings) >= 1
    fi = findings[0]
    assert fi.severity == "error"
    assert fi.category == "secret"
    assert fi.file == "leak.py"
    assert fi.line == 1
    assert fi.snippet is not None
    assert len(fi.snippet) <= 120
    assert "github" in fi.message.lower() or "token" in fi.message.lower()
