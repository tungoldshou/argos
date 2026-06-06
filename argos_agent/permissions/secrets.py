"""Secret patterns 单一来源(D2 锁):re-export 9 条 SECRET_PATTERNS + 提供 find 工具函数。"""
from __future__ import annotations

from typing import Optional

# 同源:不复制定义,直接 re-export(单一来源,spec §2.4)
from argos_agent.skills_runtime.builtin.security_review.secrets import (  # noqa: F401
    SECRET_PATTERNS,
    _SecretPattern,  # type: ignore
)

# 1MB 跳过大文件(D13 锁)
MAX_SCAN_BYTES: int = 1_000_000


def find_secret_in_content(content: str) -> Optional[str]:
    """扫内容(新内容,不是 old block),返命中的 secret pattern name;content > 1MB → 跳(返 None)。

    不在已存在内容上跑(避免 edit_file 替换旧 block 含 key 误报)。"""
    if not isinstance(content, str):
        return None
    if len(content.encode("utf-8")) > MAX_SCAN_BYTES:
        return None
    for pat in SECRET_PATTERNS:
        # 跳过文件名匹配的那条(它对 .env 文件名生效,不在 content 跑)
        if pat.name == ".env file committed":
            continue
        if pat.regex.search(content):
            return pat.name
    return None
