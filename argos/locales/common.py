"""共享文案 —— 跨多个 cluster 复用的通用词 / 短语。

key 命名空间:common.*。各 cluster 专属串放各自的目录文件。
"""
from __future__ import annotations

EN: dict[str, str] = {
    "common.enabled": "enabled",
    "common.disabled": "disabled",
    "common.yes": "yes",
    "common.no": "no",
    "common.cancel": "cancel",
    "common.done": "done",
    "common.running": "running",
    "common.unavailable": "unavailable",
}

ZH: dict[str, str] = {
    "common.enabled": "已启用",
    "common.disabled": "已禁用",
    "common.yes": "是",
    "common.no": "否",
    "common.cancel": "取消",
    "common.done": "完成",
    "common.running": "运行中",
    "common.unavailable": "不可用",
}
