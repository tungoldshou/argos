"""#10 T8 端到端铁证:refresh → install → test → list → recommend → remove 全链路。"""
from __future__ import annotations

import io
import json
import urllib.request
from argparse import Namespace
from pathlib import Path

import pytest

import argos.skills_curator.index as _idx
from tests.skills_curator.seed_index import (
    make_index,
    make_index_entry,
    make_skill_md,
    sha256_of,
)


def _ns(**kw) -> Namespace:
    return Namespace(**kw)


class _Resp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): self.close()
    def read(self, *a, **k):  # type: ignore[override]
        return super().read(*a, **k)


@pytest.fixture
def fresh_root(tmp_path, monkeypatch):
    """隔离 ~/.argos/skills/ 到 tmp_path."""
    monkeypatch.setattr(_idx, "_skills_root", lambda: tmp_path)
    return tmp_path


# ── e2e 1: refresh → install → list → remove 全链路 ──────


def test_e2e_refresh_install_list_remove_cycle(fresh_root, monkeypatch):
    """mock 远端 → refresh → install good skill → list 显 → remove → 目录进 .trash."""
    content = make_skill_md(name="python-lint", capabilities=["read", "execute"])
    sha = sha256_of(content)
    index_payload = make_index(entries=[
        make_index_entry(
            name="python-lint", content=content, sha256=sha,
            capabilities=["read", "execute"],
        ),
    ])

    def _serve(url, timeout=10.0):
        if "index.json" in url:
            return _Resp(json.dumps(index_payload).encode("utf-8"))
        if "SKILL.md" in url:
            return _Resp(content.encode("utf-8"))
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr(urllib.request, "urlopen", _serve)

    # 1) refresh
    from argos.skills_curator.index import fetch_remote, save_cache
    cache = fetch_remote()
    save_cache(cache, base_dir=fresh_root)
    assert (fresh_root / "index.json").exists()

    # 2) install
    from argos.skills_curator.install import install
    r = install("python-lint", base_dir=fresh_root, run_smoke=False)
    assert r.path.exists()
    assert r.sha256 == sha
    assert "execute" in r.capabilities

    # 3) list
    from argos.skills_curator.capabilities import list_installed
    out = list_installed(base_dir=fresh_root)
    assert len(out) == 1
    assert out[0].name == "python-lint"
    assert out[0].enabled is False  # 装后强制 false

    # 4) remove → 目录进 .trash
    from argos.skills_curator.remove import remove
    r = remove("python-lint", base_dir=fresh_root)
    assert not (fresh_root / "python-lint").exists()
    assert r.trash_path.exists()


# ── e2e 2: malicious sha 不匹配 → 拒装 ──────────────


def test_e2e_install_malicious_sha_mismatch_rejected(fresh_root, monkeypatch):
    content = make_skill_md(name="malicious", capabilities=["read"])
    # index 声明的 sha 与实际 content 的 sha 不一致
    index_payload = make_index(entries=[
        make_index_entry(
            name="malicious", content=content,
            sha256="0" * 64,  # wrong sha
        ),
    ])

    def _serve(url, timeout=10.0):
        if "index.json" in url:
            return _Resp(json.dumps(index_payload).encode("utf-8"))
        if "SKILL.md" in url:
            return _Resp(content.encode("utf-8"))
        raise AssertionError(url)

    monkeypatch.setattr(urllib.request, "urlopen", _serve)

    from argos.skills_curator.index import fetch_remote, save_cache
    cache = fetch_remote()
    save_cache(cache, base_dir=fresh_root)

    from argos.skills_curator.install import install, InstallError
    with pytest.raises(InstallError, match="sha_mismatch"):
        install("malicious", base_dir=fresh_root, run_smoke=False)
    # 目录不应创建
    assert not (fresh_root / "malicious").exists()


# ── e2e 3: install builtin → 拒 ──────────────


def test_e2e_install_builtin_verify_rejected(fresh_root, monkeypatch):
    from argos.skills_curator.install import install, InstallError
    with pytest.raises(InstallError, match="protected_skill"):
        install("verify", base_dir=fresh_root, run_smoke=False)


# ── e2e 4: remove builtin → 拒 ──────────────


def test_e2e_remove_builtin_verify_rejected(fresh_root, monkeypatch):
    from argos.skills_curator.remove import remove
    from argos.skills_curator.install import InstallError
    with pytest.raises(InstallError, match="protected_skill"):
        remove("verify", base_dir=fresh_root)


# ── e2e 5: recommend after py edits ──────────────


def test_e2e_recommend_after_py_edits(fresh_root, monkeypatch):
    from argos.skills_curator.recommend import (
        SessionActivity, build_activity_from_session, recommend,
    )
    # 模拟装一个别的 skill;python-lint 未装 → 应被推荐
    other = fresh_root / "other-skill"
    other.mkdir()
    (other / "SKILL.md").write_text(
        make_skill_md(name="other-skill", capabilities=["read"], enabled=True),
        encoding="utf-8",
    )
    activity = SessionActivity(
        files_edited=("a.py", "b.py", "c.py"),
        verify_failures=1,
    )
    recs = recommend(activity, installed=set())
    names = [r.name for r in recs]
    assert "python-lint" in names
    assert "test-debugger" in names


# ── e2e 6: size_drift warning 落地 ──────────────


def test_e2e_size_drift_warning_in_install_output(fresh_root, monkeypatch):
    content = make_skill_md(name="big", capabilities=["read"])
    sha = sha256_of(content)
    index_payload = make_index(entries=[
        make_index_entry(
            name="big", content=content, sha256=sha,
            size_bytes=10,  # 严重不符
            capabilities=["read"],
        ),
    ])

    def _serve(url, timeout=10.0):
        if "index.json" in url:
            return _Resp(json.dumps(index_payload).encode("utf-8"))
        if "SKILL.md" in url:
            return _Resp(content.encode("utf-8"))
        raise AssertionError(url)

    monkeypatch.setattr(urllib.request, "urlopen", _serve)

    from argos.skills_curator.index import fetch_remote, save_cache
    cache = fetch_remote()
    save_cache(cache, base_dir=fresh_root)

    from argos.skills_curator.install import install
    r = install("big", base_dir=fresh_root, run_smoke=False)
    assert any("size_drift" in w for w in r.warnings)


# ── e2e 7: network skill 需 env 确认 ──────────────


def test_e2e_install_network_skill_requires_confirmation(fresh_root, monkeypatch):
    content = make_skill_md(name="net-skill", capabilities=["network"])
    sha = sha256_of(content)
    index_payload = make_index(entries=[
        make_index_entry(
            name="net-skill", content=content, sha256=sha,
            capabilities=["network"],
        ),
    ])

    def _serve(url, timeout=10.0):
        if "index.json" in url:
            return _Resp(json.dumps(index_payload).encode("utf-8"))
        if "SKILL.md" in url:
            return _Resp(content.encode("utf-8"))
        raise AssertionError(url)

    monkeypatch.setattr(urllib.request, "urlopen", _serve)

    from argos.skills_curator.index import fetch_remote, save_cache
    save_cache(fetch_remote(), base_dir=fresh_root)

    from argos.skills_curator.install import install, InstallError
    import os
    os.environ.pop("ARGOS_SKILLS_NETWORK_OK", None)
    with pytest.raises(InstallError, match="network_capability"):
        install("net-skill", base_dir=fresh_root, run_smoke=False)
    os.environ["ARGOS_SKILLS_NETWORK_OK"] = "1"
    r = install("net-skill", base_dir=fresh_root, run_smoke=False)
    assert r.path.exists()
    os.environ.pop("ARGOS_SKILLS_NETWORK_OK", None)


# ── e2e 8: CLI 集成 refresh → list 链路 ──────────────


def test_e2e_cli_refresh_then_list(fresh_root, monkeypatch, capsys):
    content = make_skill_md(name="cli-test", capabilities=["read"])
    sha = sha256_of(content)
    index_payload = make_index(entries=[
        make_index_entry(name="cli-test", content=content, sha256=sha),
    ])

    def _serve(url, timeout=10.0):
        if "index.json" in url:
            return _Resp(json.dumps(index_payload).encode("utf-8"))
        if "SKILL.md" in url:
            return _Resp(content.encode("utf-8"))
        raise AssertionError(url)

    monkeypatch.setattr(urllib.request, "urlopen", _serve)

    from argos.cli import skills as cli
    ns = cli.cmd_refresh(_ns(url=None))
    captured = capsys.readouterr()
    assert ns == 0
    assert "index updated" in captured.out
