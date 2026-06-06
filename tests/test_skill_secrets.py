"""Pass 1 secret 扫描单元测试(spec §2.4 Pass 1 / D4)。"""
from __future__ import annotations

from pathlib import Path

import pytest

from argos_agent.skills_runtime.builtin.security_review.secrets import (
    scan_file_for_secrets,
    SECRET_PATTERNS,
    SKIP_BASENAMES,      # 跳过白名单(完全跳过)
    DOWNGRADE_PATH_PATTERNS,  # 降级白名单(降 severity 到 info)
)


# ── 9 条 regex 各 1 命中 ─────────────────────────────────────────

def test_all_nine_patterns_present():
    """SECRET_PATTERNS 长度 = 9(D4:含 sk-ant- 新增第 6 条)。"""
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
    """现代 OpenAI 项目 key 格式:sk-proj-...(body 含 -_)。regex 必须允许 -_,否则
    弱模型可把 sk-proj-... 整段塞进源码而不被 secret 扫描抓到 → 假绿 gate 让它
    走完 verify → 真绿 commit 落库。"""
    f = tmp_path / "leak.py"
    # 真实 OpenAI project key 风格:sk-proj- 后面是字母数字和 -_ 混合,>40 字符
    f.write_text(
        'OPENAI_API_KEY = "sk-proj-aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789-_aBcDe"\n'
    )
    findings = scan_file_for_secrets(f, relpath="leak.py", workspace=tmp_path)
    assert any(f.severity == "error" and "openai" in f.message.lower() for f in findings), (
        f"modern sk-proj- key not detected; findings={[f.message for f in findings]}"
    )


def test_anthropic_key_detected_d4_new(tmp_path):
    """D4 新增第 6 条:sk-ant-[A-Za-z0-9-_]{20,} 检测(覆盖 Argos 自身用户的 ANTHROPIC_API_KEY)。"""
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
    """.env 路径(非 .env.example)→ 1 条 warning(severity)。"""
    f = tmp_path / ".env"
    f.write_text("FOO=bar\n")
    findings = scan_file_for_secrets(f, relpath=".env", workspace=tmp_path)
    assert any(f.severity == "warning" for f in findings)


def test_hardcoded_password_warning(tmp_path):
    """password= 启发 → warning(severity,启发非强)。"""
    f = tmp_path / "cfg.py"
    f.write_text('password = "hunter2hunter2"\n')
    findings = scan_file_for_secrets(f, relpath="cfg.py", workspace=tmp_path)
    assert any(f.severity == "warning" and "password" in f.message.lower() for f in findings)


# ── 跳过白名单(D4:5 类 basename)────────────────────────────────

def test_dotenv_file_skipped(tmp_path):
    """.env 文件(裸)→ 仅发 1 条 .env committed warning,内容不扫(D4:user-controlled secret 存储)。"""
    f = tmp_path / ".env"
    f.write_text('ANTHROPIC_API_KEY = "sk-ant-api03-aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789"\n')
    findings = scan_file_for_secrets(f, relpath=".env", workspace=tmp_path)
    # 1 条 .env committed warning;但 sk-ant-* 不应触发(内容不扫)
    assert len(findings) == 1
    assert findings[0].severity == "warning"
    assert "committed" in findings[0].message.lower()
    assert not any("anthropic" in f.message.lower() for f in findings)


def test_dotenv_local_skipped(tmp_path):
    """.env.local → 跳过白名单。"""
    f = tmp_path / ".env.local"
    f.write_text('ANTHROPIC_API_KEY = "sk-ant-api03-aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789"\n')
    findings = scan_file_for_secrets(f, relpath=".env.local", workspace=tmp_path)
    assert findings == ()


def test_secrets_toml_skipped(tmp_path):
    """secrets.toml → 跳过白名单。"""
    f = tmp_path / "secrets.toml"
    f.write_text('aws_key = "AKIAIOSFODNN7EXAMPLE"\n')
    findings = scan_file_for_secrets(f, relpath="secrets.toml", workspace=tmp_path)
    assert findings == ()


def test_pem_file_skipped(tmp_path):
    """*.pem → 跳过白名单(PEM 私钥文件 user-controlled)。"""
    f = tmp_path / "server.pem"
    f.write_text('-----BEGIN RSA PRIVATE KEY-----\nfoo\n-----END RSA PRIVATE KEY-----\n')
    findings = scan_file_for_secrets(f, relpath="server.pem", workspace=tmp_path)
    assert findings == ()


def test_key_file_skipped(tmp_path):
    """*.key → 跳过白名单。"""
    f = tmp_path / "server.key"
    f.write_text('-----BEGIN RSA PRIVATE KEY-----\nfoo\n-----END RSA PRIVATE KEY-----\n')
    findings = scan_file_for_secrets(f, relpath="server.key", workspace=tmp_path)
    assert findings == ()


# ── 降级白名单 ───────────────────────────────────────────────────

def test_tests_fixtures_downgraded_to_info(tmp_path):
    """tests/fixtures/** 路径命中 → 降级到 info(仍扫,不跳过)。"""
    f = tmp_path / "tests" / "fixtures" / "secret.txt"
    f.parent.mkdir(parents=True)
    f.write_text('aws_key = "AKIAIOSFODNN7EXAMPLE"\n')
    findings = scan_file_for_secrets(f, relpath="tests/fixtures/secret.txt", workspace=tmp_path)
    assert any(f.severity == "info" for f in findings)
    assert all(f.severity != "error" for f in findings)


def test_env_example_not_warned(tmp_path):
    """.env.example(以 .example 结尾)→ 跳过(不算"committed .env")。"""
    f = tmp_path / ".env.example"
    f.write_text("FOO=bar\n")
    findings = scan_file_for_secrets(f, relpath=".env.example", workspace=tmp_path)
    # 不应有 "committed .env" warning(.env.example 是模板)
    assert not any("committed" in f.message.lower() for f in findings)


# ── 边界 ─────────────────────────────────────────────────────────

def test_binary_file_skipped_silently(tmp_path):
    """二进制文件(UnicodeDecodeError)→ 静默跳,不报 finding。"""
    f = tmp_path / "blob.bin"
    f.write_bytes(b"\x00\x01\xff\xfe")
    findings = scan_file_for_secrets(f, relpath="blob.bin", workspace=tmp_path)
    assert findings == ()


def test_oversize_file_skipped(tmp_path):
    """> 1MB 文件 → 跳过(spec §2.4 Pass 1 防 token 暴)。"""
    f = tmp_path / "big.py"
    f.write_text("# header\n" + "x = 1\n" * 200_000)
    findings = scan_file_for_secrets(f, relpath="big.py", workspace=tmp_path)
    assert findings == ()


def test_findings_have_required_fields(tmp_path):
    """每条 finding 必含 severity / category / file / line / snippet / message。"""
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
