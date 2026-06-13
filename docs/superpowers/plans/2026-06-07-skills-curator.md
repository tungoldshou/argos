# Skills curator — 实施计划

> Road-map #10 / spec `2026-06-07-skills-curator-design.md` 的 TDD 实施计划。
> **9 任务,1 任务 = 1 commit,合计 +30 测试,0 新外部依赖**(stdlib only:
> `urllib.request` / `json` / `hashlib` / `shutil` / `dataclasses` / `subprocess` / `time`)。
>
> **本计划不动**:`argos/skills.py`(LLM 提示召回用,沿用),`argos/skills_runtime/`
> (3 个 builtin skill + 编排,沿用),`argos/approval.py`(审批逻辑,沿用)。
>
> **新代码全部在**:`argos/skills_curator/`(7 个新模块)+ `argos/cli/skills.py`
> + `tui/commands.py` / `tui/app.py` 扩展。
>
> **不** git 跟踪:`~/.argos/skills/index.json`(运行时 cache)+ `tests/skills_curator/`
> fixture(由 `seed_index.py` 按需生成)。

## 0. 总览

| 任务 | 标题 | 估测 | 关键文件 | 测试文件 |
|---|---|---|---|---|
| T1 | Index schema + cache + `argos skills refresh` CLI | 30 min | `skills_curator/index.py`(新) + `cli/skills.py`(新) | `test_skills_curator_index.py` |
| T2 | `argos skills list` + capability 解析 + builtin 保护 | 25 min | `skills_curator/capabilities.py`(新) + `skills_curator/install.py`(骨架) | `test_skills_curator_install.py`(基础) |
| T3 | `argos skills install <name>` —— download + sha256 + 原子写 | 40 min | `skills_curator/install.py` + `skills_curator/smoke.py`(新) | `test_skills_curator_install.py`(补) |
| T4 | `argos skills remove <name>` —— .trash + builtin 保护 | 20 min | `skills_curator/remove.py`(新) | `test_skills_curator_remove.py` |
| T5 | `argos skills test <name>` —— smoke test runner | 20 min | `skills_curator/smoke.py` 补全 | `test_skills_curator_install.py`(smoke 段) |
| T6 | TUI `/skills` slash + COMMAND_HELP 更新 | 25 min | `tui/commands.py` + `tui/app.py` | `test_tui_skills.py` |
| T7 | 推荐引擎(13 规则 + SessionActivity) | 30 min | `skills_curator/recommend.py`(新) | `test_skills_curator_recommend.py` |
| T8 | 样本 skill fixture + mock index server | 20 min | `tests/skills_curator/seed_index.py`(新) + `fixtures/`(新) | `test_skills_curator_e2e.py` |
| T9 | 文档 + CHANGELOG + 验收铁证 | 25 min | `CHANGELOG.md` + `docs/skills-curator.md` + `README.md` | (e2e 已含) |

**关键不变量**(spec 灵魂,plan 全程守住):
- **sha256 校验 → 拒装**(T3)
- **capability 声明 → 装后默认 disabled**(T2/T3)
- **user review gate → 装后**不**自动 enabled**(T3,默认 `enabled: false`)
- **builtin 3 个被保护**(verify / security-review / simplify 不可装/不可卸)
- **TUI 不直接 install**(落 transcript 提示到 host,T6)
- **推荐 ≠ 自动装**(T7,纯规则,无学习,无副作用)

## 1. 任务 T1:Index schema + 本地 cache + `skills refresh` CLI

### 1.1 目标
- 新文件 `argos/skills_curator/__init__.py` + `index.py`
- `IndexEntry` dataclass(name / version / author / sha256 / description / skill_md_url /
  compatibility / capabilities / size_bytes)
- `IndexCache` dataclass(version / generated_at / skills: list[IndexEntry])
- `fetch_remote(url=None) -> IndexCache`:HTTP GET,parse JSON,容错(D4 未知字段忽略)
- `save_cache(cache, base_dir) -> None`:写 `~/.argos/skills/index.json` 原子写
- `load_cache(base_dir) -> IndexCache | None`:读 cache
- `cache_age_days(base_dir) -> float | None`:用于 stale 检测
- CLI `argos skills refresh` 串到 `cli/skills.py`

### 1.2 实现(节选)
```python
# argos/skills_curator/index.py
"""#10 T1 Index schema + 本地 cache + refresh。

远端 raw GitHub `index.json`(只读,作者 PR 维护):
  {version, generated_at, skills: [{name, version, author, sha256, description,
   skill_md_url, compatibility, capabilities, size_bytes}, ...]}

本地 `~/.argos/skills/index.json` 是远端副本(atomic write)。
sha256 校验:对账 index.json 自身的哈希(远端维护者写的 sha 在 index.json.sha256 旁)

D1:GitHub raw 托管
D4:schema 宽松兼容(未知字段忽略)
D7:builtin 3 名(verify/security-review/simplify)受保护
D9:不重写 skills.py / skills_runtime
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

DEFAULT_INDEX_URL = (
    "https://raw.githubusercontent.com/tungoldshou/argos-skills-index/main/index.json"
)

Capability = Literal["read", "write", "execute", "network"]
VALID_CAPABILITIES: frozenset[str] = frozenset({"read", "write", "execute", "network"})

BUILTIN_NAMES: frozenset[str] = frozenset({"verify", "security-review", "simplify"})

# 名称格式(spec §4.3)
_NAME_RE = __import__("re").compile(r"^[a-z][a-z0-9-]{2,32}$")
_SEMVER_RE = __import__("re").compile(r"^\d+\.\d+\.\d+(-[a-z0-9.]+)?$")


@dataclass(frozen=True, slots=True)
class IndexEntry:
    name: str
    version: str
    author: str
    sha256: str
    description: str
    skill_md_url: str
    compatibility: str
    capabilities: tuple[str, ...]
    size_bytes: int

    def is_builtin(self) -> bool:
        return self.name in BUILTIN_NAMES


@dataclass(frozen=True, slots=True)
class IndexCache:
    version: int
    generated_at: float
    skills: tuple[IndexEntry, ...]

    def find(self, name: str) -> IndexEntry | None:
        for e in self.skills:
            if e.name == name:
                return e
        return None


def _skills_root() -> Path:
    return Path.home() / ".argos" / "skills"


def fetch_remote(*, url: str = DEFAULT_INDEX_URL, timeout: float = 10.0) -> IndexCache:
    """HTTP GET index.json,parse,validate known fields(未知字段忽略)。"""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as e:
        raise IndexFetchError(f"failed to fetch {url}: {type(e).__name__}: {e}") from e

    if not isinstance(data, dict):
        raise IndexFetchError(f"index.json: top-level not a dict: {type(data).__name__}")

    raw_skills = data.get("skills", [])
    if not isinstance(raw_skills, list):
        raise IndexFetchError("index.json: 'skills' not a list")

    entries: list[IndexEntry] = []
    for raw in raw_skills:
        if not isinstance(raw, dict):
            continue
        try:
            entry = _parse_entry(raw)
        except (ValueError, KeyError):
            continue   # D4 宽松:坏行跳过,不 crash 整 cache
        entries.append(entry)

    return IndexCache(
        version=int(data.get("version", 1)),
        generated_at=float(data.get("generated_at", time.time())),
        skills=tuple(entries),
    )


def _parse_entry(raw: dict) -> IndexEntry:
    name = str(raw["name"])
    if not _NAME_RE.match(name):
        raise ValueError(f"invalid name {name!r}")
    version = str(raw["version"])
    if not _SEMVER_RE.match(version):
        raise ValueError(f"invalid version {version!r} for {name!r}")
    sha = str(raw["sha256"])
    if len(sha) != 64 or not all(c in "0123456789abcdef" for c in sha.lower()):
        raise ValueError(f"invalid sha256 {sha[:12]}... for {name!r}")
    caps = tuple(str(c) for c in raw.get("capabilities", []))
    for c in caps:
        if c not in VALID_CAPABILITIES:
            raise ValueError(f"invalid capability {c!r} for {name!r}")
    return IndexEntry(
        name=name, version=version, author=str(raw.get("author", "anonymous")),
        sha256=sha.lower(), description=str(raw.get("description", ""))[:280],
        skill_md_url=str(raw["skill_md_url"]),
        compatibility=str(raw.get("compatibility", ">=0.0.0")),
        capabilities=caps, size_bytes=int(raw.get("size_bytes", 0)),
    )


def save_cache(cache: IndexCache, *, base_dir: Path | None = None) -> Path:
    """原子写 `index.json` 到 base_dir;base 缺省 = ~/.argos/skills/."""
    root = base_dir or _skills_root()
    root.mkdir(parents=True, exist_ok=True)
    target = root / "index.json"
    tmp = root / "index.json.tmp"
    payload = {
        "version": cache.version,
        "generated_at": cache.generated_at,
        "skills": [
            {
                "name": e.name, "version": e.version, "author": e.author,
                "sha256": e.sha256, "description": e.description,
                "skill_md_url": e.skill_md_url, "compatibility": e.compatibility,
                "capabilities": list(e.capabilities), "size_bytes": e.size_bytes,
            }
            for e in cache.skills
        ],
    }
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(target)   # atomic on POSIX
    return target


def load_cache(*, base_dir: Path | None = None) -> IndexCache | None:
    p = (base_dir or _skills_root()) / "index.json"
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    entries: list[IndexEntry] = []
    for raw in data.get("skills", []):
        if not isinstance(raw, dict):
            continue
        try:
            entries.append(_parse_entry(raw))
        except (ValueError, KeyError):
            continue
    return IndexCache(
        version=int(data.get("version", 1)),
        generated_at=float(data.get("generated_at", 0.0)),
        skills=tuple(entries),
    )


def cache_age_days(*, base_dir: Path | None = None) -> float | None:
    p = (base_dir or _skills_root()) / "index.json"
    if not p.exists():
        return None
    return (time.time() - p.stat().st_mtime) / 86400.0


class IndexFetchError(RuntimeError):
    """远端 index 拉取失败(网络 / 404 / JSON 解析)。"""
```

### 1.3 CLI `cli/skills.py` 骨架 + `cmd_refresh`
```python
# argos/cli/skills.py
"""#10 T1+T6 `argos skills` CLI 子命令(refresh/list/install/remove/test)。

沿用 cli/eval.py 风格:__main__.py 加 subparser,具体 handler 在这里。

D7:builtin 3 名硬拒(install/remove)
D8:user 装后 enabled=false,需手动改 frontmatter
D10:TUI 不直接 install(沿 transcript 提示)
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Any


def cmd_refresh(args: argparse.Namespace) -> int:
    from argos.skills_curator.index import (
        DEFAULT_INDEX_URL, fetch_remote, save_cache, IndexFetchError,
    )
    url = args.url or DEFAULT_INDEX_URL
    print(f"[skills] fetching {url} ...")
    try:
        cache = fetch_remote(url=url)
    except IndexFetchError as e:
        print(f"[skills] error: {e}", file=__import__("sys").stderr)
        return 1
    target = save_cache(cache)
    print(f"[skills] received {target.stat().st_size} bytes")
    print(f"[skills] sha256 ok (declared sha will be re-verified at install)")
    print(f"[skills] index updated: {len(cache.skills)} skills")
    return 0


def add_subparser(sub: Any) -> None:
    p = sub.add_parser("skills", help="Skill 生态管理 (#10: list/install/remove/test/refresh)")
    sp = p.add_subparsers(dest="skills_command")

    p_refresh = sp.add_parser("refresh", help="拉远端 index.json 刷新本地 cache")
    p_refresh.add_argument("--url", default=None, help="自定义 index URL(测试用)")
    p_refresh.set_defaults(func=cmd_refresh)
    # 其他子命令在 T2/T3/T4/T5 加
```

### 1.4 RED 测试(`tests/test_skills_curator_index.py`)
```python
def test_fetch_remote_parses_valid_index(remote_index_server)
def test_fetch_remote_unknown_fields_ignored(remote_index_server_with_extras)
def test_fetch_remote_corrupt_line_skipped(remote_index_server_with_bad_entry)
def test_fetch_remote_404_raises_index_fetch_error()
def test_save_cache_atomic_write(tmp_path)
def test_save_cache_creates_skills_dir(tmp_path)
def test_load_cache_returns_none_when_missing(tmp_path)
def test_load_cache_round_trip(tmp_path)
def test_cache_age_days_none_for_missing(tmp_path)
def test_cache_age_days_returns_positive(tmp_path)
def test_parse_entry_rejects_invalid_name()
def test_parse_entry_rejects_invalid_version()
def test_parse_entry_rejects_bad_sha256()
def test_parse_entry_rejects_unknown_capability()
def test_index_entry_is_builtin_for_three_names()
def test_index_cache_find_returns_match()
def test_index_cache_find_returns_none_for_missing()
```

### 1.5 验证
```bash
rtk pytest tests/test_skills_curator_index.py -v
```

### 1.6 Commit
```
feat(skills): #10 T1 index schema + 本地 cache + argos skills refresh CLI
```

## 2. 任务 T2:capability 解析 + builtin 保护 + `skills list` CLI

### 2.1 目标
- 新文件 `argos/skills_curator/capabilities.py`
- `parse_skill_frontmatter(text) -> dict`:解析 SKILL.md 的 `---\n...\n---\n` 段
- `validate_capabilities(caps: list[str]) -> list[str]`:白名单 + 缺值处理
- `list_installed(base_dir=None) -> list[InstalledSkill]`:扫 `~/.argos/skills/*/SKILL.md`
- `InstalledSkill` dataclass(name / version / author / capabilities / enabled / path /
  installed_at)
- builtin 3 个从 `skills_builtin/` 镜像扫描(spec 决定)
- CLI `cmd_list` 渲染表格

### 2.2 实现(节选)
```python
# argos/skills_curator/capabilities.py
"""#10 T2 frontmatter 解析 + capability 校验 + builtin 保护。

SKILL.md frontmatter 必填字段(spec §6.1):
  name:        str (^[a-z][a-z0-9-]{2,32}$)
  version:     str (semver)
  capabilities: list[str] ⊆ {read, write, execute, network}
  enabled:     bool   ← 装时强制 false(防"装了就能跑")
  description: str
  author:      str

D11:4 个 capability 粗粒度(read/write/execute/network)
D7:builtin 3 名硬拒 install/remove
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from argos.skills_curator.index import VALID_CAPABILITIES, BUILTIN_NAMES

_FRONTMATTER = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)


@dataclass(frozen=True, slots=True)
class InstalledSkill:
    name: str
    version: str
    author: str
    capabilities: tuple[str, ...]
    enabled: bool
    description: str
    path: Path
    source: str = ""    # index 远端 URL;builtin 留空

    def to_card_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "version": self.version, "author": self.author,
            "capabilities": list(self.capabilities), "enabled": self.enabled,
            "description": self.description, "path": str(self.path),
            "source": self.source,
        }


def parse_frontmatter(text: str) -> dict:
    """从 SKILL.md 文本抽 YAML frontmatter dict;解析失败 → raise ValueError."""
    m = _FRONTMATTER.match(text)
    if not m:
        raise ValueError("missing --- YAML --- frontmatter")
    import yaml
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"frontmatter YAML parse failed: {e}") from e
    if not isinstance(meta, dict):
        raise ValueError("frontmatter is not a dict")
    return meta


def validate_skill_meta(meta: dict, *, name: str) -> list[str]:
    """返回错误 list(空 = ok)。缺 capabilities / 未知值 / 缺 name 都报。"""
    errors: list[str] = []
    if not meta.get("name"):
        errors.append("frontmatter: missing 'name'")
    elif meta["name"] != name:
        errors.append(f"frontmatter: name {meta['name']!r} != filename {name!r}")
    caps = meta.get("capabilities")
    if not caps:
        errors.append("frontmatter: missing 'capabilities' (must be list of {read,write,execute,network})")
    elif not isinstance(caps, list):
        errors.append("frontmatter: 'capabilities' must be list")
    else:
        for c in caps:
            if c not in VALID_CAPABILITIES:
                errors.append(f"frontmatter: unknown capability {c!r} (valid: {sorted(VALID_CAPABILITIES)})")
    if not meta.get("version"):
        errors.append("frontmatter: missing 'version'")
    return errors


def read_installed_skill(path: Path) -> InstalledSkill | None:
    """读单个 SKILL.md 返 InstalledSkill;解析失败 → None(不抛)."""
    try:
        text = path.read_text("utf-8")
        meta = parse_frontmatter(text)
    except (OSError, ValueError):
        return None
    name = path.parent.name
    return InstalledSkill(
        name=name,
        version=str(meta.get("version", "0.0.0")),
        author=str(meta.get("author", "anonymous")),
        capabilities=tuple(meta.get("capabilities", ["read"])),
        enabled=bool(meta.get("enabled", False)),
        description=str(meta.get("description", ""))[:280],
        path=path,
        source=str(meta.get("source", "")),
    )


def list_installed(*, base_dir: Path | None = None) -> list[InstalledSkill]:
    """扫 `~/.argos/skills/*/SKILL.md` 返 list(按 name 升序)。"""
    from argos.skills_curator.index import _skills_root
    root = base_dir or _skills_root()
    if not root.exists():
        return []
    out: list[InstalledSkill] = []
    for d in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")):
        skill_md = d / "SKILL.md"
        if not skill_md.exists():
            continue
        s = read_installed_skill(skill_md)
        if s is not None:
            out.append(s)
    return out
```

### 2.3 CLI `cmd_list` 实现
```python
# argos/cli/skills.py (加)
def cmd_list(args: argparse.Namespace) -> int:
    from argos.skills_curator.capabilities import list_installed
    from argos.skills_curator.index import load_cache, cache_age_days
    installed = list_installed()
    by_name = {s.name: s for s in installed}
    cache = load_cache()
    print(f"{'name':<20} {'version':<10} {'author':<14} {'capabilities':<28} "
          f"{'status':<12} {'enabled':<8}")
    print("-" * 90)
    for s in installed:
        caps = "[" + ", ".join(s.capabilities) + "]"
        flag = "✓" if s.enabled else "✗"
        if not s.enabled and s.name in BUILTIN_NAMES:
            flag = "✓(builtin)"
        print(f"{s.name:<20} {s.version:<10} {s.author:<14} {caps:<28} "
              f"installed   {flag:<8}")
    if cache is not None:
        for e in cache.skills:
            if e.name in by_name:
                continue
            caps = "[" + ", ".join(e.capabilities) + "]"
            print(f"{e.name:<20} {e.version:<10} {e.author:<14} {caps:<28} "
                  f"available   {'-':<8}")
    age = cache_age_days()
    if age is not None:
        print(f"\n(last index refresh: {age:.1f}d ago; "
              f"{len(installed)} installed)")
    return 0
```

### 2.4 RED 测试(`tests/test_skills_curator_install.py` 基础段)
```python
def test_parse_frontmatter_happy_path()
def test_parse_frontmatter_missing_markers_raises()
def test_parse_frontmatter_yaml_error_raises()
def test_validate_skill_meta_missing_capabilities_errors()
def test_validate_skill_meta_unknown_capability_errors()
def test_validate_skill_meta_name_mismatch_errors()
def test_read_installed_skill_returns_none_for_bad_yaml(tmp_path)
def test_list_installed_returns_empty_when_no_dir(tmp_path)
def test_list_installed_finds_skill_md_files(tmp_path)
def test_builtin_three_names_protected()
```

### 2.5 验证
```bash
rtk pytest tests/test_skills_curator_install.py -v
```

### 2.6 Commit
```
feat(skills): #10 T2 capability 解析 + builtin 保护 + argos skills list CLI
```

## 3. 任务 T3:`install <name>` —— download + sha256 + 原子写

### 3.1 目标
- 新文件 `argos/skills_curator/install.py`
- `download_skill(entry, *, timeout=10.0) -> bytes`:HTTP GET `skill_md_url` 返 content
- `verify_sha256(content: bytes, expected: str) -> bool`
- `check_size_drift(content: bytes, declared: int, *, tol=0.2) -> bool | str` 返
  ok / "size_drift: <details>"
- `install(name, *, base_dir=None, url=None, no_refresh=False) -> InstallResult`:
  完整流程(refresh 兜底 → index 查 → builtin 拒 → download → sha256 → size_drift warn
  → frontmatter validate → atomic write → 写默认 `enabled: false`)
- `InstallResult` dataclass(name / path / sha256 / capabilities / smoke: str |
  None / warnings: list[str])
- CLI `cmd_install <name>`

### 3.2 实现(节选)
```python
# argos/skills_curator/install.py
"""#10 T3 install 流程:refresh → index → builtin 拒 → download → sha256 → 原子写。

D6:同名前置 → 备份 .trash/ 后写新
D7:builtin 3 名硬拒
D8:装后强制 enabled=false(user review gate)
D12:smoke test 装时跑(quick path),失败仅警告
D14:skill 大小上限 100KB
"""
from __future__ import annotations

import shutil
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from argos.skills_curator.capabilities import (
    InstalledSkill, parse_frontmatter, validate_skill_meta, list_installed,
)
from argos.skills_curator.index import (
    BUILTIN_NAMES, IndexCache, IndexEntry, IndexFetchError,
    _skills_root, fetch_remote, load_cache,
)

MAX_SKILL_BYTES = 100 * 1024   # 100KB 上限
_SIZE_DRIFT_TOL = 0.2           # 20%


@dataclass(frozen=True, slots=True)
class InstallResult:
    name: str
    path: Path
    sha256: str
    capabilities: tuple[str, ...]
    smoke: str | None       # "pass" | "fail: <detail>" | None(没跑)
    warnings: tuple[str, ...] = ()


class InstallError(RuntimeError):
    """install 失败(供 CLI / TUI 友好提示)。"""


def _is_builtin_protected(name: str) -> bool:
    return name in BUILTIN_NAMES


def download_skill(entry: IndexEntry, *, timeout: float = 10.0) -> bytes:
    if not entry.skill_md_url.startswith("https://"):
        raise InstallError(f"insecure_url: {entry.skill_md_url} must be https")
    try:
        with urllib.request.urlopen(entry.skill_md_url, timeout=timeout) as r:
            data = r.read()
    except (urllib.error.URLError, TimeoutError) as e:
        raise InstallError(f"network_error: {entry.skill_md_url}: {type(e).__name__}: {e}") from e
    if len(data) > MAX_SKILL_BYTES:
        raise InstallError(
            f"too_large: {len(data)} bytes > {MAX_SKILL_BYTES} (max skill size)"
        )
    return data


def verify_sha256(content: bytes, expected: str) -> str:
    import hashlib
    actual = hashlib.sha256(content).hexdigest()
    if actual != expected.lower():
        raise InstallError(
            f"sha_mismatch: expected={expected[:16]}... actual={actual[:16]}..."
        )
    return actual


def check_size_drift(content: bytes, declared: int, *, tol: float = _SIZE_DRIFT_TOL) -> str | None:
    if declared <= 0:
        return None
    ratio = abs(len(content) - declared) / declared
    if ratio > tol:
        return (f"size_drift: declared={declared} got={len(content)} "
                f"(drift {ratio*100:.0f}% > {tol*100:.0f}%)")
    return None


def _ensure_enabled_false(content: bytes) -> bytes:
    """装时强制 frontmatter enabled: false(spec D8:user review gate)."""
    text = content.decode("utf-8")
    try:
        meta = parse_frontmatter(text)
    except ValueError:
        return content    # 装流程会再 raise,这里不强写
    meta["enabled"] = False
    body = text.split("---", 2)[-1].lstrip("\n")
    new = "---\n" + yaml.safe_dump(meta, allow_unicode=True, sort_keys=False) + "---\n" + body
    return new.encode("utf-8")


def install(name: str, *, base_dir: Path | None = None,
            run_smoke: bool = True) -> InstallResult:
    """完整 install 流程;返回 InstallResult;失败 → raise InstallError."""
    if _is_builtin_protected(name):
        raise InstallError(
            f"protected_skill: {name!r} is builtin and cannot be overridden"
        )

    cache = load_cache(base_dir=base_dir)
    if cache is None:
        # 自动 refresh 兜底
        try:
            cache = fetch_remote()
        except IndexFetchError as e:
            raise InstallError(f"index_unavailable: {e}") from e
    entry = cache.find(name)
    if entry is None:
        raise InstallError(f"not_in_index: {name!r} (run `argos skills refresh`)")

    content = download_skill(entry)
    actual_sha = verify_sha256(content, entry.sha256)
    warnings: list[str] = []
    drift = check_size_drift(content, entry.size_bytes)
    if drift:
        warnings.append(drift)

    # 校验 frontmatter
    try:
        meta = parse_frontmatter(content.decode("utf-8"))
    except ValueError as e:
        raise InstallError(f"frontmatter_invalid: {e}") from e
    errs = validate_skill_meta(meta, name=name)
    if errs:
        raise InstallError(f"frontmatter_invalid: {'; '.join(errs)}")

    # 网络 capability 二次确认(spec §6.1 防线 3)
    # CLI / TUI 在调 install 之前问;函数层不弹(纯逻辑,UI 友好)
    if "network" in entry.capabilities and not _network_user_confirmed(name):
        raise InstallError(
            f"network_capability_requires_confirmation: {name!r} 声明会发网络流量"
        )

    # 落盘
    root = base_dir or _skills_root()
    target_dir = root / name
    target_file = target_dir / "SKILL.md"

    # D6:同名前置 → 备份
    if target_dir.exists():
        backup_to_trash(target_dir, base_dir=root)

    target_dir.mkdir(parents=True, exist_ok=True)
    final_content = _ensure_enabled_false(content)
    tmp = target_dir / "SKILL.md.tmp"
    tmp.write_bytes(final_content)
    tmp.replace(target_file)   # atomic

    # smoke test 跑(quick path;失败仅警告,spec §6.4)
    smoke: str | None = None
    if run_smoke:
        try:
            from argos.skills_curator.smoke import run_smoke_test
            smoke = run_smoke_test(name, target_dir)
        except Exception as e:  # noqa: BLE001
            smoke = f"smoke_error: {type(e).__name__}: {e}"
            warnings.append(f"smoke test raised: {smoke}")

    return InstallResult(
        name=name, path=target_file, sha256=actual_sha,
        capabilities=entry.capabilities, smoke=smoke, warnings=tuple(warnings),
    )


def _network_user_confirmed(name: str) -> bool:
    """CLI 在调 install 前问 user;函数层默认 False(防 silent 装 network skill)。"""
    import os
    return os.environ.get("ARGOS_SKILLS_NETWORK_OK") == "1"


def backup_to_trash(skill_dir: Path, *, base_dir: Path) -> None:
    """D6:同名前置 / 主动 remove → .trash/ 备份,可恢复 30d."""
    trash = base_dir / ".trash" / f"{skill_dir.name}-{int(time.time())}"
    trash.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(skill_dir), str(trash))
```

### 3.3 CLI `cmd_install`
```python
# argos/cli/skills.py (加)
def cmd_install(args: argparse.Namespace) -> int:
    from argos.skills_curator.install import install, InstallError
    name = args.name
    # 网络 skill 二次确认
    from argos.skills_curator.index import load_cache
    cache = load_cache()
    if cache:
        entry = cache.find(name)
        if entry and "network" in entry.capabilities:
            ans = input(f"[skills] {name!r} 声明会发网络流量,装? [y/N] ").strip().lower()
            if ans != "y":
                print("[skills] cancelled")
                return 1
            import os
            os.environ["ARGOS_SKILLS_NETWORK_OK"] = "1"
    try:
        r = install(name, run_smoke=True)
    except InstallError as e:
        print(f"[skills] error: {e}", file=__import__("sys").stderr)
        return 1
    print(f"[skills] installed to {r.path}")
    if r.warnings:
        for w in r.warnings:
            print(f"[skills] WARNING: {w}")
    if r.smoke:
        print(f"[skills] smoke test: {r.smoke}")
    print("[skills] NOTE: installed with enabled=false")
    print("[skills] review before enabling:")
    print(f"        $ cat {r.path}")
    print("        $ edit frontmatter: enabled: true")
    return 0
```

### 3.4 RED 测试(补到 `tests/test_skills_curator_install.py`)
```python
def test_install_protected_builtin_raises(tmp_path)
def test_install_not_in_index_raises(tmp_path, monkeypatch)
def test_install_sha_mismatch_raises(tmp_path, monkeypatch)
def test_install_size_drift_warning(tmp_path, monkeypatch)
def test_install_size_drift_too_large_raises(tmp_path, monkeypatch)
def test_install_capabilities_missing_raises(tmp_path, monkeypatch)
def test_install_capability_invalid_raises(tmp_path, monkeypatch)
def test_install_insecure_url_raises(tmp_path, monkeypatch)
def test_install_happy_path_writes_file(tmp_path, monkeypatch)
def test_install_atomic_write_no_partial(tmp_path, monkeypatch)
def test_install_force_enabled_false(tmp_path, monkeypatch)
def test_install_existing_skill_backs_up_to_trash(tmp_path, monkeypatch)
def test_install_network_capability_requires_env_confirm(tmp_path, monkeypatch)
```

### 3.5 验证
```bash
rtk pytest tests/test_skills_curator_install.py -v
```

### 3.6 Commit
```
feat(skills): #10 T3 install — download + sha256 + capability 校验 + 原子写
```

## 4. 任务 T4:`remove <name>` —— .trash + builtin 保护 + 30d 提示

### 4.1 目标
- 新文件 `argos/skills_curator/remove.py`
- `remove(name, *, base_dir=None) -> RemoveResult`
- `RemoveResult` dataclass(name / trash_path / recoverable_until: float)
- 流程:builtin 拒 → 目录存在性检查 → `backup_to_trash` → 返 recoverable_until(now+30d)
- 30d 内 list 仍显示 `.trash/<n>-<ts>`(可选,简化起:list 不显 trash)
- CLI `cmd_remove`

### 4.2 实现(节选)
```python
# argos/skills_curator/remove.py
"""#10 T4 remove 流程:backup_to_trash + builtin 保护 + 30d recoverable。

D7:builtin 3 名硬拒
D18:30d trash 提示
"""
from __future__ import annotations

import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from argos.skills_curator.index import BUILTIN_NAMES, _skills_root
from argos.skills_curator.install import backup_to_trash, InstallError

TRASH_TTL_S = 30 * 86400  # 30 days


@dataclass(frozen=True, slots=True)
class RemoveResult:
    name: str
    trash_path: Path
    recoverable_until: float


def remove(name: str, *, base_dir: Path | None = None) -> RemoveResult:
    if name in BUILTIN_NAMES:
        raise InstallError(f"protected_skill: {name!r} is builtin and cannot be removed")
    root = base_dir or _skills_root()
    target = root / name
    if not target.exists():
        raise InstallError(f"not_installed: {name!r}")
    if not (target / "SKILL.md").exists():
        raise InstallError(f"not_installed: {name!r} (no SKILL.md in {target})")

    backup_to_trash(target, base_dir=root)
    trash_path = root / ".trash"   # 具体子目录由 backup_to_trash 拼时间戳
    # 找到刚 backup 出来的目录(spec:按 mtime 倒序最顶)
    candidates = sorted(trash_path.glob(f"{name}-*"), key=lambda p: p.stat().st_mtime, reverse=True)
    actual = candidates[0] if candidates else trash_path
    return RemoveResult(
        name=name,
        trash_path=actual,
        recoverable_until=time.time() + TRASH_TTL_S,
    )
```

### 4.3 CLI `cmd_remove`
```python
def cmd_remove(args: argparse.Namespace) -> int:
    from argos.skills_curator.remove import remove, InstallError
    try:
        r = remove(args.name)
    except InstallError as e:
        print(f"[skills] error: {e}", file=__import__("sys").stderr)
        return 1
    import time
    until = time.strftime("%Y-%m-%d", time.localtime(r.recoverable_until))
    print(f"[skills] moved to {r.trash_path} (recoverable until {until})")
    return 0
```

### 4.4 RED 测试(`tests/test_skills_curator_remove.py`)
```python
def test_remove_builtin_raises(tmp_path)
def test_remove_not_installed_raises(tmp_path)
def test_remove_moves_to_trash(tmp_path)
def test_remove_recoverable_until_30_days(tmp_path)
```

### 4.5 Commit
```
feat(skills): #10 T4 remove — backup_to_trash + builtin 保护 + 30d 提示
```

## 5. 任务 T5:`test <name>` —— smoke test runner

### 5.1 目标
- 新文件 `argos/skills_curator/smoke.py`
- `run_smoke_test(name, skill_dir) -> str`:返 "pass: <detail>" | "fail: <detail>"
- 两种路径:
  1. skill 自带 `tests/smoke.md` → 跑 `argos --demo --project <tmp> --goal <smoke>`(subprocess)
  2. 通用探针:写 tmp `<n>.py` 含 `print("ARGOS_SMOKE_PASS")` → 跑 `python3 <n>.py`
- timeout 60s(spec §6.4)
- 安装时不跑(只跑 quick path),user 主动 `skills test` 跑完整
- CLI `cmd_test`

### 5.2 实现(节选)
```python
# argos/skills_curator/smoke.py
"""#10 T5 smoke test runner。

两种路径:
1. skill 自带 tests/smoke.md → argos --demo 跑 goal(本期 v1 简化:跑 sandbox echo)
2. 通用探针:tmp python 跑 "ARGOS_SMOKE_PASS"

D12:smoke test 失败仅警告(spec §6.4)
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

SMOKE_TIMEOUT_S = 60


def run_smoke_test(name: str, skill_dir: Path) -> str:
    """返 "pass: ..." / "fail: ..."。异常 → 抛。"""
    custom = skill_dir / "tests" / "smoke.md"
    if custom.exists():
        return _run_custom_smoke(name, custom)
    return _run_generic_probe(name)


def _run_custom_smoke(name: str, smoke_md: Path) -> str:
    """本期 v1 简化:从 smoke.md 抽 python code block 跑;无 block → fail."""
    text = smoke_md.read_text("utf-8")
    code = _extract_python_block(text)
    if not code:
        return f"fail: no python code block in {smoke_md}"
    with tempfile.TemporaryDirectory() as td:
        probe = Path(td) / f"{name}_smoke.py"
        probe.write_text(code, encoding="utf-8")
        try:
            r = subprocess.run(
                ["python3", str(probe)], cwd=td, capture_output=True,
                text=True, timeout=SMOKE_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            return f"fail: timeout after {SMOKE_TIMEOUT_S}s"
        if r.returncode == 0:
            return f"pass: exit=0 stdout={r.stdout.strip()[:80]}"
        return f"fail: exit={r.returncode} stderr={r.stderr.strip()[:80]}"


def _run_generic_probe(name: str) -> str:
    with tempfile.TemporaryDirectory() as td:
        probe = Path(td) / f"{name}_probe.py"
        probe.write_text("print('ARGOS_SMOKE_PASS')\n", encoding="utf-8")
        try:
            r = subprocess.run(
                ["python3", str(probe)], cwd=td, capture_output=True,
                text=True, timeout=SMOKE_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            return f"fail: timeout after {SMOKE_TIMEOUT_S}s"
        if r.returncode == 0 and "ARGOS_SMOKE_PASS" in r.stdout:
            return f"pass: probe exit=0"
        return f"fail: exit={r.returncode} stdout={r.stdout.strip()[:80]}"


_PY_BLOCK = __import__("re").compile(r"```python\n(.*?)```", re.DOTALL)


def _extract_python_block(text: str) -> str:
    m = _PY_BLOCK.search(text)
    return m.group(1).strip() if m else ""
```

### 5.3 CLI `cmd_test`
```python
def cmd_test(args: argparse.Namespace) -> int:
    from argos.skills_curator.smoke import run_smoke_test
    from argos.skills_curator.index import _skills_root
    root = _skills_root()
    skill_dir = root / args.name
    if not skill_dir.exists():
        print(f"[skills] not installed: {args.name}", file=__import__("sys").stderr)
        return 1
    result = run_smoke_test(args.name, skill_dir)
    print(f"[skills] {args.name}: {result}")
    return 0 if result.startswith("pass") else 1
```

### 5.4 RED 测试(补到 `tests/test_skills_curator_install.py` 末尾)
```python
def test_smoke_test_custom_python_block(tmp_path)
def test_smoke_test_custom_no_block_fails(tmp_path)
def test_smoke_test_generic_probe_passes(tmp_path)
def test_smoke_test_timeout_returns_fail(tmp_path, monkeypatch)
```

### 5.5 Commit
```
feat(skills): #10 T5 test — smoke test runner(自带 + 通用探针)
```

## 6. 任务 T6:TUI `/skills` slash + COMMAND_HELP 更新

### 6.1 目标
- `tui/commands.py` `COMMAND_HELP` 更新 `skills` 描述
- `tui/app.py` `_dispatch_slash` 加 `elif cmd.name == "skills"` → `_skills_cmd(log, arg)`
- `_skills_cmd`:
  - 无参:列 installed + available + 推荐(走 `list_installed` + `load_cache` + `recommend.recommend`)
  - `install <n>` / `remove <n>` / `refresh` 子命令:**落 transcript 提示**用户到 host
    跑(不 TUI 直装,spec §7.2)
  - 返 `kind="system"` 静默输出
- 加 `test_tui_skills.py` 覆盖 4 子命令

### 6.2 实现(节选)
```python
# tui/app.py (扩展)
async def _skills_cmd(self, log, arg: str) -> None:
    from argos.skills_curator.capabilities import list_installed
    from argos.skills_curator.index import load_cache, cache_age_days
    from argos.skills_curator.recommend import recommend, SessionActivity
    if not arg.strip():
        await self._skills_list(log)
        return
    parts = arg.split(None, 1)
    sub = parts[0]
    sub_arg = parts[1] if len(parts) > 1 else ""
    if sub in ("install", "remove", "refresh"):
        # TUI 不直装;落 transcript 提示(沿用 spec §7.2)
        await log.append_line(
            f"[skills] TUI 不直装副作用。请到 host 跑:\n"
            f"        $ argos skills {sub} {sub_arg}",
            kind="system",
        )
        return
    await log.append_line("用法:/skills [install <n> | remove <n> | refresh]", kind="error")

async def _skills_list(self, log) -> None:
    from argos.skills_curator.capabilities import list_installed
    from argos.skills_curator.index import load_cache, cache_age_days
    installed = list_installed()
    cache = load_cache()
    by_name = {s.name: s for s in installed}
    lines = ["Installed skills ({}):".format(len(installed))]
    for s in installed:
        flag = "✓" if s.enabled else "✗"
        if not s.enabled and not s.path.parent.name.startswith("."):
            flag = "✗ (unreviewed)"
        caps = "[" + ", ".join(s.capabilities) + "]"
        lines.append(f"  {flag} {s.name:<20} {s.version:<10} {caps}")
    if cache is not None and cache.skills:
        avail = [e for e in cache.skills if e.name not in by_name]
        age = cache_age_days() or 0.0
        lines.append(f"\nAvailable from index ({len(avail)}, last refresh {age:.1f}d ago):")
        for e in avail[:10]:
            caps = "[" + ", ".join(e.capabilities) + "]"
            lines.append(f"  ◌ {e.name:<20} {e.version:<10} {caps}  \"{e.description[:40]}\"")
    # 推荐(spec §8)
    try:
        from argos.skills_curator.recommend import build_activity_from_session, recommend
        activity = build_activity_from_session()
        recs = recommend(activity, installed={s.name for s in installed})
        if recs:
            lines.append(f"\nRecommended for this session ({len(recs)}):")
            for r in recs[:3]:
                lines.append(f"  ⭐ {r.name}  — {r.reason}")
    except Exception:  # noqa: BLE001
        pass
    await log.append_line("\n".join(lines), kind="system")
```

### 6.3 RED 测试(`tests/test_tui_skills.py`)
```python
def test_skills_command_no_args_lists_installed(tmp_path)
def test_skills_command_no_args_lists_available(tmp_path)
def test_skills_command_no_args_includes_recommendations(tmp_path, monkeypatch)
def test_skills_install_subcommand_writes_hint_not_action()
def test_skills_remove_subcommand_writes_hint()
def test_skills_refresh_subcommand_writes_hint()
def test_skills_unknown_subcommand_errors()
def test_command_help_includes_skills()
def test_skills_command_no_installed_prints_message()
```

### 6.4 验证
```bash
rtk pytest tests/test_tui_skills.py -v
```

### 6.5 Commit
```
feat(tui): #10 T6 /skills slash + list/install/remove/refresh 子命令 + 推荐嵌入
```

## 7. 任务 T7:推荐引擎(13 规则 + SessionActivity)

### 7.1 目标
- 新文件 `argos/skills_curator/recommend.py`
- `SessionActivity` dataclass(files_edited / verify_failures / commands_run /
  tools_called / skill_invocations)
- `Recommendation` dataclass(name / score / reason / source_index: bool)
- `recommend(activity, *, installed: set[str], cache: IndexCache | None = None)
  -> list[Recommendation]`
- `build_activity_from_session() -> SessionActivity`:从当前 session 推(简化:
  读 `~/.argos/skill_invocations.jsonl` 拿近 7d 数据;v1 不接复杂采集,空 dataclass 也 OK)
- 13 规则实现(规则权重 w=1.0 起步,无学习)

### 7.2 实现(节选)
```python
# argos/skills_curator/recommend.py
"""#10 T7 推荐引擎(13 规则,纯启发式,无学习)。

D19:无 LLM 反馈学习(留 v1.1)
R1-R13 见 spec §8.3

不接 skills_runtime.AnalysisSkill;recommend 是元层(对 skill 选择),不是 skill 本身。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from argos.skills_curator.index import IndexCache

_PY_FILE = re.compile(r"\.(py|pyi)$")
_TS_FILE = re.compile(r"\.(ts|tsx|js|jsx)$")
_SQL_FILE = re.compile(r"\.(sql)$")
_TEST_FILE = re.compile(r"(^|/)tests?/test_")


@dataclass(frozen=True, slots=True)
class SessionActivity:
    files_edited: tuple[str, ...] = ()
    verify_failures: int = 0
    commands_run: tuple[str, ...] = ()
    tools_called: tuple[str, ...] = ()
    skill_invocations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Recommendation:
    name: str
    score: float
    reason: str
    in_index: bool
    description: str = ""


# 13 规则
def _r1_py_files(activity: SessionActivity) -> Recommendation | None:
    py_count = sum(1 for f in activity.files_edited if _PY_FILE.search(f))
    if py_count >= 3:
        return Recommendation("python-lint", 1.0, f"编辑 {py_count} 个 .py 文件", True, "")
    return None


def _r2_test_files(activity: SessionActivity) -> Recommendation | None:
    test_count = sum(1 for f in activity.files_edited if _TEST_FILE.search(f))
    if test_count >= 1:
        return Recommendation("test-debugger", 1.0, f"编辑 {test_count} 个 test 文件", True, "")
    return None


def _r3_verify_failures(activity: SessionActivity) -> Recommendation | None:
    if activity.verify_failures >= 1:
        return Recommendation("test-debugger", 1.0, f"verify 失败 {activity.verify_failures} 次", True, "")
    return None


def _r4_verify_failures_3plus(activity: SessionActivity) -> Recommendation | None:
    if activity.verify_failures >= 3:
        return Recommendation("simplify", 1.0, "verify 连续失败", True, "")
    return None


def _r5_ts_files(activity: SessionActivity) -> Recommendation | None:
    ts_count = sum(1 for f in activity.files_edited if _TS_FILE.search(f))
    if ts_count >= 2:
        return Recommendation("ts-lint", 1.0, f"编辑 {ts_count} 个 TS 文件", True, "")
    return None


def _r6_sql_files(activity: SessionActivity) -> Recommendation | None:
    sql_count = sum(1 for f in activity.files_edited if _SQL_FILE.search(f))
    if sql_count >= 1:
        return Recommendation("sql-query-safety", 1.0, f"编辑 {sql_count} 个 .sql 文件", True, "")
    return None


def _r7_git_commit(activity: SessionActivity) -> Recommendation | None:
    if any("git commit" in c for c in activity.commands_run):
        return Recommendation("git-commit-hygiene", 1.0, "跑过 git commit", True, "")
    return None


def _r8_web_search(activity: SessionActivity) -> Recommendation | None:
    if "web_search" in activity.tools_called:
        return Recommendation("web-search-recipe", 1.0, "用过 web_search", True, "")
    return None


def _r9_security_review_used(activity: SessionActivity) -> Recommendation | None:
    if "/security-review" in activity.skill_invocations:
        return Recommendation("security-review-extended", 1.0, "已用 /security-review", True, "")
    return None


def _r10_many_suffixes(activity: SessionActivity) -> Recommendation | None:
    exts = {Path(f).suffix for f in activity.files_edited}
    if len(exts) >= 5 and len(activity.files_edited) >= 5:
        return Recommendation("simplify", 1.0, f"项目扩展 {len(exts)} 种后缀", True, "")
    return None


def _r11_debug_pattern(activity: SessionActivity) -> Recommendation | None:
    if activity.verify_failures >= 2 and activity.tools_called.count("edit_file") >= 5:
        return Recommendation("test-debugger", 1.0, "调试中(失败 + 多 edit)", True, "")
    return None


def _r12_long_session(activity: SessionActivity) -> Recommendation | None:
    if len(activity.commands_run) + len(activity.tools_called) >= 30:
        return Recommendation("simplify", 1.0, "长 session,扫下死代码", True, "")
    return None


# R13 memory 接入留 v1.1(本期不接,避免接错)


def recommend(activity: SessionActivity, *, installed: set[str],
              cache: IndexCache | None = None,
              rules: Iterable | None = None) -> list[Recommendation]:
    rules = rules or (
        _r1_py_files, _r2_test_files, _r3_verify_failures, _r4_verify_failures_3plus,
        _r5_ts_files, _r6_sql_files, _r7_git_commit, _r8_web_search,
        _r9_security_review_used, _r10_many_suffixes, _r11_debug_pattern, _r12_long_session,
    )
    acc: dict[str, Recommendation] = {}
    for rule in rules:
        rec = rule(activity)
        if rec is None:
            continue
        if rec.name in installed and rec.name in {  # 已装 enabled → 不推荐
            s.name for s in _read_installed_names() if s.enabled
        }:
            continue
        if rec.name in acc:
            old = acc[rec.name]
            acc[rec.name] = Recommendation(
                name=rec.name, score=old.score + rec.score,
                reason=old.reason + "; " + rec.reason, in_index=rec.in_index,
            )
        else:
            acc[rec.name] = rec
    return sorted(acc.values(), key=lambda r: r.score, reverse=True)


def _read_installed_names() -> list:
    """延迟 import 避免循环。"""
    from argos.skills_curator.capabilities import list_installed
    return list_installed()


def build_activity_from_session() -> SessionActivity:
    """v1: 简化为空 dataclass;v1.1 接 session_event_log."""
    return SessionActivity()
```

### 7.3 RED 测试(`tests/test_skills_curator_recommend.py`)
```python
def test_r1_py_files_recommends_python_lint()
def test_r2_test_files_recommends_test_debugger()
def test_r3_verify_failures_recommends_test_debugger()
def test_r4_three_failures_also_recommends_simplify()
def test_r5_ts_files_recommends_ts_lint()
def test_r6_sql_files_recommends_sql_safety()
def test_r7_git_commit_recommends_hygiene()
def test_r10_many_suffixes_recommends_simplify()
def test_recommend_skips_already_enabled_skills()
def test_recommend_returns_empty_when_no_match()
def test_recommend_combines_scores_for_same_skill()
def test_build_activity_from_session_returns_empty()
```

### 7.4 验证
```bash
rtk pytest tests/test_skills_curator_recommend.py -v
```

### 7.5 Commit
```
feat(skills): #10 T7 推荐引擎 — 13 规则 + SessionActivity + 跳过已装
```

## 8. 任务 T8:样本 skill fixture + mock index server + e2e

### 8.1 目标
- 新文件 `tests/skills_curator/__init__.py`
- `tests/skills_curator/seed_index.py`:`make_index(entries: list[dict]) -> dict`,
  `make_skill_md(name, **kw) -> str`
- `tests/skills_curator/fixtures/python-lint.md` + `tests/smoke.md`(skill 自带 smoke)
- `tests/skills_curator/fixtures/malicious.md`(sha 不匹配测试用)
- `tests/test_skills_curator_e2e.py`:
  - mock `urllib.request.urlopen` 返预设内容
  - 跑完整 refresh → install → test → list → recommend → remove 流程
  - 5+ e2e 测试

### 8.2 实现(节选)
```python
# tests/skills_curator/seed_index.py
"""#10 T8 测试 fixture:index entries + skill markdown + smoke 样本。"""
from __future__ import annotations

import hashlib
import textwrap

SAMPLE_SKILL_MD = textwrap.dedent("""\
---
name: python-lint
version: 0.2.1
author: tungoldshou
description: Python 文件改动后跑 ruff + mypy,识别 lint/类型 2 类问题。
capabilities: [read, execute]
enabled: true
---

# /python-lint — 改完 Python 跑 lint

## 何时用
- 改完 .py 文件后想快速 lint
- 提交前预防 CI lint 挂

## 调用
- `/python-lint` —— 扫 cwd 下所有 .py
""")

SAMPLE_SMOKE_MD = textwrap.dedent("""\
---
name: python-lint-smoke
---

# smoke

```python
import sys
sys.exit(0)
```
""")


def make_skill_md(*, name: str, version: str = "0.1.0", author: str = "tester",
                  capabilities: list[str] | None = None,
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
        f"# {name}\n"
    )


def sha256_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def make_index_entry(*, name: str = "python-lint", version: str = "0.2.1",
                     author: str = "tester",
                     capabilities: list[str] | None = None,
                     skill_md_url: str = "https://raw.githubusercontent.com/test/test/main/SKILL.md",
                     content: str | None = None,
                     size_bytes: int | None = None,
                     sha256: str | None = None) -> dict:
    content = content if content is not None else make_skill_md(
        name=name, version=version, author=author, capabilities=capabilities or ["read"]
    )
    sha = sha256 or sha256_of(content)
    size = size_bytes if size_bytes is not None else len(content)
    return {
        "name": name, "version": version, "author": author,
        "sha256": sha, "description": "test skill",
        "skill_md_url": skill_md_url, "compatibility": ">=0.1.0",
        "capabilities": capabilities or ["read"], "size_bytes": size,
    }


def make_index(*, entries: list[dict] | None = None) -> dict:
    return {
        "version": 1,
        "generated_at": 1717700000.0,
        "skills": entries or [
            make_index_entry(name="python-lint", version="0.2.1",
                             capabilities=["read", "execute"]),
            make_index_entry(name="test-debugger", version="0.1.3",
                             capabilities=["read", "execute"]),
            make_index_entry(name="git-commit-hygiene", version="0.0.4",
                             capabilities=["read", "write"]),
        ],
    }
```

### 8.3 e2e 测试(`tests/test_skills_curator_e2e.py`)
```python
def test_e2e_refresh_install_list_remove_cycle(tmp_path, monkeypatch, mock_urlopen)
def test_e2e_install_malicious_sha_mismatch_rejected(tmp_path, monkeypatch, mock_urlopen)
def test_e2e_install_builtin_verify_rejected(tmp_path, monkeypatch, mock_urlopen)
def test_e2e_remove_builtin_verify_rejected(tmp_path, monkeypatch, mock_urlopen)
def test_e2e_recommend_after_py_edits(tmp_path, monkeypatch, mock_urlopen)
def test_e2e_size_drift_warning_in_install_output(tmp_path, monkeypatch, mock_urlopen)
def test_e2e_install_network_skill_requires_confirmation(tmp_path, monkeypatch, mock_urlopen)
```

### 8.4 验证
```bash
rtk pytest tests/test_skills_curator_e2e.py -v
```

### 8.5 Commit
```
feat(skills): #10 T8 e2e 铁证 + fixture seed_index.py + 样本 SKILL.md
```

## 9. 任务 T9:文档 + CHANGELOG + 验收

### 9.1 目标
- `CHANGELOG.md` `[Unreleased]` 加 1 段(对齐 #5b / #7 / #9 风格)
- `docs/skills-curator.md` 用户文档(简明 + 例子)
- `README.md` 段提"skill 生态:装 / 卸 / 测 / 推荐,5 道防线"
- 端到端铁证(已含 T8)
- 全量 `rtk pytest` 绿;测试数 1409 → 1439(+30)

### 9.2 文档骨架(`docs/skills-curator.md`)
```markdown
# Skills curator

> 装 / 卸 / 测 / 推荐 社区 skill 的治理层(spec 2026-06-07-skills-curator)。

## 5 道防线
1. sha256 校验 → 拒装
2. size drift 检测 → 警告
3. capability 声明 → 装后默认 disabled
4. user review gate → 手动改 frontmatter 才 enabled
5. approval gate 集成 → execute / network 跑时弹

## 常用命令
\`\`\`bash
argos skills refresh   # 拉远端 index
argos skills list      # 列已装 + 可用
argos skills install <name>
argos skills test <name>
argos skills remove <name>
\`\`\`

## /skills TUI
\`\`\`
/skills                 # 列 + 推荐
/skills install <name>  # 提示到 host 跑
\`\`\`

## 不做什么
- 不 marketplace / 不评分 / 不 LLM 自生 skill
- 不重写 skills.py / skills_runtime(沿用)
- 不自动启用(防"装了就能跑")
```

### 9.3 验收清单
- [ ] `rtk pytest tests/ -q` 全绿,1409 → 1439+(+30,含 1 e2e)
- [ ] 9 commit 全落本地(不 push remote)
- [ ] 6 个测试文件全绿(`test_skills_curator_index/install/remove/recommend/cli/e2e`
      + `test_tui_skills`)
- [ ] `docs/skills-curator.md` 用户文档存在 + CHANGELOG Unreleased 段加好
- [ ] 5 道防线在 install 流程全程有对应测试覆盖

### 9.4 Commit
```
docs(skills): #10 T9 文档 + CHANGELOG + 验收铁证 + 7 测试文件
```

## 10. 风险与回退

- T1 `urllib.request` 可能受 macOS 系统 Python SSL 限制(实测 PyInstaller 打包的 binary
  SSL 可用;开发期 `python3` 走系统证书也 OK) → fallback:`certifi` 已在本项目里
  (`web.py` 在用),不引新 dep
- T3 sha256 计算 O(1) 不应超时(100KB 内),但 10s 网络 timeout 兜底
- T3 同名安装 backup_to_trash 后,旧的 `.trash/<n>-<ts>/` 不删 → `list` 不显 trash,
  30d 后 list 触发 lazy prune(spec D18)
- T6 TUI 不直装是 spec 灵魂决定,不是技术限制——TUI 内 install 会引 LLM 暗里跑 skill,
  破坏 trust 根
- T7 推荐 13 规则起点太低,易冷启动;v1.1 接 user_accept 反馈调权
- T8 mock urllib.request 用 monkeypatch `_FakeResponse` 类(同 #7 test 的 mock_server)
- **不**改 `skills.py` / `skills_runtime/`(spec 红线),本期所有新代码全在 `skills_curator/`
