"""StandingOrder + OrderStore — 常驻指令持久层（设计 §9 自治面）。

Standing Order = 用户用人话立下的一条自治规矩，可以是：
  - schedule 类：cron/间隔表达式触发（"每天早上九点…"）
  - file_trigger 类：glob 文件变化触发（"每次 requirements.txt 改变就…"）

存储路径：~/.argos/conductor/orders.jsonl（可注入目录，便于测试）
格式：每行一条 StandingOrder.to_dict() 序列化的 JSON。
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

log = logging.getLogger("argos.conductor.orders")

# 常驻指令类型
OrderKind = Literal["schedule", "file_trigger"]

# 默认 orders JSONL 路径
_DEFAULT_ORDERS_DIR = Path.home() / ".argos" / "conductor"


@dataclass(frozen=True, slots=True)
class StandingOrder:
    """一条常驻自治指令（frozen dataclass — 不可变、可哈希）。

    字段说明：
        id              唯一 ID（uuid4 十六进制，不含连字符）
        utterance       用户的原始人话描述
                        例："每天早上九点把昨天的日志整理成摘要"
        kind            "schedule"（定时）或 "file_trigger"（文件变化触发）
        schedule        cron-lite 表达式（kind=schedule 时必填，否则 None）
                        例："09:00"、"every 1h"、"@daily"、"0 9 * * *"
        trigger_glob    文件 glob 模式（kind=file_trigger 时必填，否则 None）
                        例："**/requirements*.txt"
        goal_template   传给 AgentLoop 的 goal 模板；可含 {date}/{path} 占位符
        enabled         False → ConductorEngine tick 时跳过
        created_at      创建时间（Unix float）
        last_fired_at   最近一次产出 ProactiveSuggestion 的时间（None = 从未触发）
    """
    id: str
    utterance: str
    kind: OrderKind
    schedule: str | None
    trigger_glob: str | None
    goal_template: str
    enabled: bool
    created_at: float
    last_fired_at: float | None

    def __post_init__(self) -> None:
        """字段一致性断言（构造时立即检查，fail-loud）。"""
        if self.kind == "schedule" and not self.schedule:
            raise ValueError(
                f"StandingOrder kind=schedule 必须提供 schedule 字段 (id={self.id!r})"
            )
        if self.kind == "file_trigger" and not self.trigger_glob:
            raise ValueError(
                f"StandingOrder kind=file_trigger 必须提供 trigger_glob 字段 (id={self.id!r})"
            )

    # ------------------------------------------------------------------
    # 序列化 / 反序列化
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """序列化为 dict（供 JSONL 落盘）。"""
        return {
            "id": self.id,
            "utterance": self.utterance,
            "kind": self.kind,
            "schedule": self.schedule,
            "trigger_glob": self.trigger_glob,
            "goal_template": self.goal_template,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "last_fired_at": self.last_fired_at,
        }

    @staticmethod
    def from_dict(d: dict) -> "StandingOrder":
        """从落盘 dict 还原 StandingOrder。"""
        return StandingOrder(
            id=str(d["id"]),
            utterance=str(d["utterance"]),
            kind=d["kind"],  # type: ignore[arg-type]
            schedule=d.get("schedule"),
            trigger_glob=d.get("trigger_glob"),
            goal_template=str(d["goal_template"]),
            enabled=bool(d.get("enabled", True)),
            created_at=float(d["created_at"]),
            last_fired_at=float(d["last_fired_at"]) if d.get("last_fired_at") is not None else None,
        )

    def with_last_fired(self, ts: float) -> "StandingOrder":
        """返回已更新 last_fired_at 的新 StandingOrder（frozen 不可变，返回副本）。"""
        import dataclasses
        return dataclasses.replace(self, last_fired_at=ts)

    def with_enabled(self, enabled: bool) -> "StandingOrder":
        """返回已更新 enabled 状态的新 StandingOrder。"""
        import dataclasses
        return dataclasses.replace(self, enabled=enabled)


def _new_order_id() -> str:
    """生成新 StandingOrder ID（uuid4，不含连字符）。"""
    return uuid.uuid4().hex


class OrderStore:
    """常驻指令的 JSONL 持久化 CRUD。

    存储格式：每行一条 StandingOrder.to_dict()，每条 order 独立一行。
    - 文件不存在 → 自动创建（首次 add 时）。
    - IO 失败 → log.warning + 不抛（best-effort 语义，不阻断主流程）。
    - 删改通过覆写整文件实现（orders 数量通常很小，< 1000 条）。
    """

    def __init__(self, orders_dir: Path | None = None) -> None:
        self._dir = Path(orders_dir) if orders_dir else _DEFAULT_ORDERS_DIR
        self._path = self._dir / "orders.jsonl"

    @property
    def path(self) -> Path:
        """JSONL 文件路径（供测试检查）。"""
        return self._path

    # ------------------------------------------------------------------
    # 读操作
    # ------------------------------------------------------------------

    def list(self) -> list[StandingOrder]:
        """返回所有 StandingOrder 列表（按 created_at 升序）。

        文件不存在 → 返回空列表。
        解析失败的行 → log.warning + 跳过。
        """
        if not self._path.exists():
            return []
        orders: list[StandingOrder] = []
        try:
            with self._path.open("r", encoding="utf-8") as fh:
                for i, line in enumerate(fh, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        orders.append(StandingOrder.from_dict(d))
                    except Exception as exc:  # noqa: BLE001
                        log.warning("orders: 第 %d 行解析失败: %s", i, exc)
        except OSError as exc:
            log.warning("orders: list 读取失败 %s: %s", self._path, exc)
        orders.sort(key=lambda o: o.created_at)
        return orders

    def get(self, order_id: str) -> StandingOrder | None:
        """按 ID 查找 StandingOrder，不存在返回 None。"""
        for o in self.list():
            if o.id == order_id:
                return o
        return None

    # ------------------------------------------------------------------
    # 写操作
    # ------------------------------------------------------------------

    def add(self, order: StandingOrder) -> None:
        """追加一条新 StandingOrder。

        不检查重复 ID（调用方负责用 _new_order_id() 生成唯一 ID）。
        """
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(order.to_dict(), ensure_ascii=False) + "\n"
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(line)
        except OSError as exc:
            log.warning("orders: add 写入失败: %s", exc)

    def update(self, order: StandingOrder) -> bool:
        """替换同 ID 的 StandingOrder，返回 True = 成功找到并替换；False = ID 不存在。

        实现：读 → 替换目标行 → 覆写整文件。
        """
        existing = self.list()
        updated = [order if o.id == order.id else o for o in existing]
        if updated == existing and all(o.id != order.id for o in existing):
            return False
        found = any(o.id == order.id for o in existing)
        if not found:
            return False
        self._write_all(updated)
        return True

    def delete(self, order_id: str) -> bool:
        """删除指定 ID 的 StandingOrder，返回 True = 成功删除；False = ID 不存在。"""
        existing = self.list()
        filtered = [o for o in existing if o.id != order_id]
        if len(filtered) == len(existing):
            return False
        self._write_all(filtered)
        return True

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    def _write_all(self, orders: list[StandingOrder]) -> None:
        """覆写整个 JSONL 文件。IO 失败 log + 不抛。"""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("w", encoding="utf-8") as fh:
                for o in orders:
                    fh.write(json.dumps(o.to_dict(), ensure_ascii=False) + "\n")
        except OSError as exc:
            log.warning("orders: _write_all 写入失败: %s", exc)
