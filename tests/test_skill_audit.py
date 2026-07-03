from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from argos.skills_runtime.builtin.security_review.audit import (
    detect_lockfiles,
    audit_lockfile,
    audit_dependencies,
)



def test_detect_lockfiles_npm(tmp_path):
    (tmp_path / "package-lock.json").write_text("{}")
    detected = detect_lockfiles(tmp_path)
    assert "npm" in detected


def test_detect_lockfiles_pip(tmp_path):
    (tmp_path / "requirements.txt").write_text("foo==1.0\n")
    detected = detect_lockfiles(tmp_path)
    assert "pip" in detected


def test_detect_lockfiles_cargo(tmp_path):
    (tmp_path / "Cargo.lock").write_text("")
    detected = detect_lockfiles(tmp_path)
    assert "cargo" in detected


def test_detect_lockfiles_multiple(tmp_path):
    (tmp_path / "package-lock.json").write_text("{}")
    (tmp_path / "requirements.txt").write_text("")
    (tmp_path / "Cargo.lock").write_text("")
    detected = detect_lockfiles(tmp_path)
    assert detected == {"npm", "pip", "cargo"}


def test_detect_lockfiles_none(tmp_path):
    assert detect_lockfiles(tmp_path) == set()



def test_audit_deps_npm_missing_tool_returns_error_severity(tmp_path):
    (tmp_path / "package-lock.json").write_text("{}")

    # mock FileNotFoundError on spawn
    def _raise(*args, **kwargs):
        raise FileNotFoundError("npm not found")

    with patch("argos.skills_runtime.builtin.security_review.audit.subprocess.run", side_effect=_raise):
        findings = audit_dependencies(tmp_path, rel_workspace=tmp_path)

    err_findings = [f for f in findings if f.severity == "error" and f.category == "dep_audit"]
    assert len(err_findings) == 1
    assert "npm" in err_findings[0].message
    assert "install" in err_findings[0].suggestion.lower()


def test_audit_deps_pip_missing_tool_returns_error_severity(tmp_path):
    (tmp_path / "requirements.txt").write_text("foo==1.0\n")

    def _raise(*args, **kwargs):
        raise FileNotFoundError("pip-audit not found")

    with patch("argos.skills_runtime.builtin.security_review.audit.subprocess.run", side_effect=_raise):
        findings = audit_dependencies(tmp_path, rel_workspace=tmp_path)

    err_findings = [f for f in findings if f.severity == "error" and f.category == "dep_audit"]
    assert len(err_findings) == 1
    assert "pip" in err_findings[0].message


def test_audit_deps_cargo_missing_tool_returns_error_severity(tmp_path):
    (tmp_path / "Cargo.lock").write_text("")

    def _raise(*args, **kwargs):
        raise FileNotFoundError("cargo-audit not found")

    with patch("argos.skills_runtime.builtin.security_review.audit.subprocess.run", side_effect=_raise):
        findings = audit_dependencies(tmp_path, rel_workspace=tmp_path)

    err_findings = [f for f in findings if f.severity == "error" and f.category == "dep_audit"]
    assert len(err_findings) == 1
    assert "cargo" in err_findings[0].message



def test_audit_lockfile_returns_empty_on_healthy_output(tmp_path):
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = json.dumps({"vulnerabilities": {}})
    mock_result.stderr = ""

    with patch("argos.skills_runtime.builtin.security_review.audit.subprocess.run", return_value=mock_result):
        findings = audit_lockfile(tmp_path, "npm")
    assert findings == ()


def test_audit_lockfile_nonzero_returncode_yields_error_finding(tmp_path):
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = ""
    mock_result.stderr = "audit tool internal error"

    with patch("argos.skills_runtime.builtin.security_review.audit.subprocess.run", return_value=mock_result):
        findings = audit_lockfile(tmp_path, "npm")
    err_findings = [f for f in findings if f.severity == "error"]
    assert len(err_findings) >= 1



def test_audit_deps_healthy_no_findings(tmp_path):
    findings = audit_dependencies(tmp_path, rel_workspace=tmp_path)
    assert findings == ()



def test_audit_deps_npm_vuln_parsed(tmp_path):
    (tmp_path / "package-lock.json").write_text("{}")
    mock_output = json.dumps({
        "vulnerabilities": {
            "lodash": {
                "severity": "critical",
                "via": [{"title": "Prototype Pollution", "url": "https://example.com/CVE-2021-23337"}],
                "fixAvailable": {"version": "4.17.21"},
            },
            "minimist": {
                "severity": "high",
                "via": [{"title": "Prototype Pollution"}],
                "fixAvailable": True,
            },
        },
    })

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = mock_output
    mock_result.stderr = ""

    with patch("argos.skills_runtime.builtin.security_review.audit.subprocess.run", return_value=mock_result):
        findings = audit_dependencies(tmp_path, rel_workspace=tmp_path)

    dep_vuln = [f for f in findings if f.category == "dep_vuln"]
    assert len(dep_vuln) == 2
    assert all(f.severity == "error" for f in dep_vuln)
