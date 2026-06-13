"""#10 T2 + T3 capability 解析 + install 流程 测试。"""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from typing import Callable

import pytest

import argos.skills_curator.index as _idx
import argos.skills_curator.capabilities as _cap


# ── helpers ──────────────────────────────────────────────────


def _make_skill_md(*, name: str = "user-skill", version: str = "0.1.0",
                   author: str = "tester", capabilities: list | None = None,
                   enabled: bool = True, description: str = "test") -> str:
    caps = capabilities or ["read"]
    cap_str = "[" + ", ".join(caps) + "]"
    return (
        f"---\n"
        f"name: {name}\n"
        f"version: {version}\n"
        f"author: {author}\n"
        f"description: {description}\n"
        f"capabilities: {cap_str}\n"
        f"enabled: {str(bool(enabled)).lower()}\n"
        f"---\n\n"
        f"# {name}\n\nbody\n"
    )


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _seed_index_cache(tmp_path, *, entries: list[dict]) -> None:
    """写一个本地 index.json,装时直接读 cache 不走远端."""
    cache_path = tmp_path / "index.json"
    cache_path.write_text(
        json.dumps({"version": 1, "generated_at": 0.0, "skills": entries}),
        encoding="utf-8",
    )


def _entry_dict(name: str, **over) -> dict:
    content = over.pop("content", None) or _make_skill_md(
        name=name,
        version=over.get("version", "0.1.0"),
        author=over.get("author", "tester"),
        capabilities=over.get("capabilities", ["read"]),
    )
    sha = over.pop("sha256", None) or _sha(content)
    size = over.pop("size_bytes", None) or len(content)
    base = {
        "name": name, "version": "0.1.0", "author": "tester",
        "sha256": sha, "description": "x",
        "skill_md_url": f"https://example.com/skills/{name}/SKILL.md",
        "compatibility": ">=0.1.0",
        "capabilities": ["read"], "size_bytes": size,
    }
    base.update(over)
    return base


# ── T2 capability tests ──────────────────────────────────────


def test_parse_frontmatter_happy_path():
    text = _make_skill_md()
    meta = _cap.parse_frontmatter(text)
    assert meta["name"] == "user-skill"
    assert meta["enabled"] is True


def test_parse_frontmatter_missing_markers_raises():
    with pytest.raises(ValueError, match="missing ---"):
        _cap.parse_frontmatter("just body text\n")


def test_parse_frontmatter_bad_yaml_raises():
    with pytest.raises(ValueError, match="YAML parse failed"):
        _cap.parse_frontmatter("---\n[unclosed\n---\nbody")


def test_validate_skill_meta_missing_capabilities_errors():
    errs = _cap.validate_skill_meta(
        {"name": "x", "version": "0.1.0", "capabilities": []}, name="x"
    )
    assert any("capabilities" in e for e in errs)


def test_validate_skill_meta_unknown_capability_errors():
    errs = _cap.validate_skill_meta(
        {"name": "x", "version": "0.1.0", "capabilities": ["read", "evil"]},
        name="x",
    )
    assert any("unknown capability" in e for e in errs)


def test_validate_skill_meta_name_mismatch_errors():
    errs = _cap.validate_skill_meta(
        {"name": "y", "version": "0.1.0", "capabilities": ["read"]},
        name="x",
    )
    assert any("name" in e for e in errs)


def test_validate_skill_meta_missing_version_errors():
    errs = _cap.validate_skill_meta(
        {"name": "x", "capabilities": ["read"]}, name="x",
    )
    assert any("version" in e for e in errs)


def test_read_installed_skill_happy(tmp_path):
    skill = tmp_path / "user-skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text(_make_skill_md(), encoding="utf-8")
    s = _cap.read_installed_skill(skill / "SKILL.md")
    assert s is not None
    assert s.name == "user-skill"
    assert s.enabled is True
    assert s.capabilities == ("read",)


def test_read_installed_skill_returns_none_for_bad_yaml(tmp_path):
    skill = tmp_path / "user-skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("not frontmatter\n", encoding="utf-8")
    assert _cap.read_installed_skill(skill / "SKILL.md") is None


def test_list_installed_returns_empty_when_no_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(_idx, "_skills_root", lambda: tmp_path / "missing")
    assert _cap.list_installed() == []


def test_list_installed_finds_skill_md_files(tmp_path, monkeypatch):
    monkeypatch.setattr(_idx, "_skills_root", lambda: tmp_path)
    for n in ("a", "b"):
        d = tmp_path / n
        d.mkdir()
        (d / "SKILL.md").write_text(_make_skill_md(name=n), encoding="utf-8")
    out = _cap.list_installed()
    assert sorted(s.name for s in out) == ["a", "b"]


def test_builtin_three_names_protected():
    from argos.skills_curator.index import BUILTIN_NAMES
    assert "verify" in BUILTIN_NAMES
    assert "security-review" in BUILTIN_NAMES
    assert "simplify" in BUILTIN_NAMES


# ── T3 install tests (impl 已在 install.py) ───────────────────


class _Resp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): self.close()
    def read(self, *a, **k):  # type: ignore[override]
        return super().read(*a, **k)


@pytest.fixture
def install_env(tmp_path, monkeypatch):
    """所有 install 流程所需 mock:tmp root + cache + urlopen."""
    monkeypatch.setattr(_idx, "_skills_root", lambda: tmp_path)
    return tmp_path


def test_install_protected_builtin_raises(install_env, monkeypatch):
    import os
    os.environ["ARGOS_SKILLS_NETWORK_OK"] = "1"
    from argos.skills_curator.install import install, InstallError
    with pytest.raises(InstallError, match="protected_skill"):
        install("verify")
    os.environ.pop("ARGOS_SKILLS_NETWORK_OK", None)


def test_install_not_in_index_raises(install_env, monkeypatch):
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda url, timeout=10.0: (_ for _ in ()).throw(TimeoutError("no")))
    from argos.skills_curator.install import install, InstallError
    with pytest.raises(InstallError, match="index_unavailable|not_in_index"):
        install("nope")


def test_install_sha_mismatch_raises(install_env, monkeypatch):
    content = _make_skill_md(name="bad-skill", capabilities=["read"])
    _seed_index_cache(install_env, entries=[_entry_dict("bad-skill",
                                                        content=content,
                                                        sha256="0" * 64)])
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda url, timeout=10.0: _Resp(content.encode("utf-8")))
    from argos.skills_curator.install import install, InstallError
    with pytest.raises(InstallError, match="sha_mismatch"):
        install("bad-skill")


def test_install_size_drift_warning(install_env, monkeypatch):
    """声明 10 bytes,实际 5000 → 警告 but install 继续."""
    content = _make_skill_md(name="big-skill", capabilities=["read"])
    sha = _sha(content)
    _seed_index_cache(install_env, entries=[_entry_dict(
        "big-skill", content=content, sha256=sha, size_bytes=10,  # 严重不符
    )])
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda url, timeout=10.0: _Resp(content.encode("utf-8")))
    from argos.skills_curator.install import install
    r = install("big-skill", run_smoke=False)
    assert r.path.exists()
    assert any("size_drift" in w for w in r.warnings)


def test_install_capabilities_missing_raises(install_env, monkeypatch):
    content = _make_skill_md(name="bad-meta", capabilities=["read"])
    # 改掉 frontmatter → capabilities 缺
    content = content.replace("capabilities: [read]\n", "")
    sha = _sha(content)
    _seed_index_cache(install_env, entries=[_entry_dict(
        "bad-meta", content=content, sha256=sha, capabilities=["read"],
    )])
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda url, timeout=10.0: _Resp(content.encode("utf-8")))
    from argos.skills_curator.install import install, InstallError
    with pytest.raises(InstallError, match="frontmatter_invalid"):
        install("bad-meta")


def test_install_insecure_url_raises(install_env, monkeypatch):
    _seed_index_cache(install_env, entries=[_entry_dict(
        "evil", capabilities=["read"],
        skill_md_url="http://insecure.example.com/SKILL.md",
    )])
    from argos.skills_curator.install import install, InstallError
    with pytest.raises(InstallError, match="insecure_url"):
        install("evil")


def test_install_happy_path_writes_file(install_env, monkeypatch):
    content = _make_skill_md(name="good", capabilities=["read", "execute"])
    sha = _sha(content)
    _seed_index_cache(install_env, entries=[_entry_dict(
        "good", content=content, sha256=sha, capabilities=["read", "execute"],
    )])
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda url, timeout=10.0: _Resp(content.encode("utf-8")))
    from argos.skills_curator.install import install
    r = install("good", run_smoke=False)
    assert r.path.exists()
    assert r.sha256 == sha
    assert "execute" in r.capabilities


def test_install_force_enabled_false(install_env, monkeypatch):
    """装时强制 enabled: false(user review gate,spec D8)."""
    content = _make_skill_md(name="auto-off", capabilities=["read"], enabled=True)
    sha = _sha(content)
    _seed_index_cache(install_env, entries=[_entry_dict(
        "auto-off", content=content, sha256=sha, capabilities=["read"],
    )])
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda url, timeout=10.0: _Resp(content.encode("utf-8")))
    from argos.skills_curator.install import install
    install("auto-off", run_smoke=False)
    written = (install_env / "auto-off" / "SKILL.md").read_text("utf-8")
    assert "enabled: false" in written


def test_install_existing_skill_backs_up_to_trash(install_env, monkeypatch):
    content = _make_skill_md(name="twice", capabilities=["read"])
    sha = _sha(content)
    _seed_index_cache(install_env, entries=[_entry_dict(
        "twice", content=content, sha256=sha, capabilities=["read"],
    )])
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda url, timeout=10.0: _Resp(content.encode("utf-8")))
    from argos.skills_curator.install import install
    install("twice", run_smoke=False)
    install("twice", run_smoke=False)  # 二次 → backup
    assert (install_env / ".trash").exists()
    trash_dirs = list((install_env / ".trash").iterdir())
    assert any(d.name.startswith("twice-") for d in trash_dirs)


def test_install_network_capability_requires_env_confirm(install_env, monkeypatch):
    content = _make_skill_md(name="net-skill", capabilities=["network"])
    sha = _sha(content)
    _seed_index_cache(install_env, entries=[_entry_dict(
        "net-skill", content=content, sha256=sha, capabilities=["network"],
    )])
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda url, timeout=10.0: _Resp(content.encode("utf-8")))
    from argos.skills_curator.install import install, InstallError
    import os
    # 不设 env
    os.environ.pop("ARGOS_SKILLS_NETWORK_OK", None)
    with pytest.raises(InstallError, match="network_capability"):
        install("net-skill")
    # 设了 → 装成功
    os.environ["ARGOS_SKILLS_NETWORK_OK"] = "1"
    r = install("net-skill", run_smoke=False)
    assert r.path.exists()
    os.environ.pop("ARGOS_SKILLS_NETWORK_OK", None)
