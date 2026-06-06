"""#10 T8 e2e fixture:index entries + skill markdown + smoke 样本."""
from __future__ import annotations

import hashlib


SAMPLE_SKILL_MD = """\
---
name: python-lint
version: 0.2.1
author: tungoldshou
description: Python 文件改动后跑 ruff + mypy,识别 lint/类型 2 类问题.
capabilities: [read, execute]
enabled: true
---

# /python-lint -- 改完 Python 跑 lint

## 何时用
- 改完 .py 文件后想快速 lint
- 提交前预防 CI lint 挂
"""


SAMPLE_SMOKE_MD = """\
---
name: python-lint-smoke
---

# smoke

```python
import sys
sys.exit(0)
```
"""


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
        name=name, version=version, author=author,
        capabilities=capabilities or ["read"],
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
