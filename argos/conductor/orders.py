"""Standing order persistence for dreams and conductor state.

Dream state uses ARGOS_CONFIG_DIR/dreams and conductor orders use
ARGOS_CONFIG_DIR/conductor.
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from argos.i18n import t

log = logging.getLogger("argos.conductor.orders")

OrderKind = Literal["schedule", "file_trigger"]

OrderAction = Literal["run", "dream"]

def _default_orders_dir() -> Path:
    from argos import config

    return Path(config.get("ARGOS_CONFIG_DIR") or (Path.home() / ".argos")).expanduser() / "conductor"


@dataclass(frozen=True, slots=True)
class StandingOrder:
    """Internal documentation."""
    id: str
    utterance: str
    kind: OrderKind
    schedule: str | None
    trigger_glob: str | None
    goal_template: str
    enabled: bool
    created_at: float
    last_fired_at: float | None
    action: OrderAction = "run"

    def __post_init__(self) -> None:
        """Internal documentation."""
        if self.kind == "schedule" and not self.schedule:
            raise ValueError(t("cond.order.schedule_required", id=self.id))
        if self.kind == "file_trigger" and not self.trigger_glob:
            raise ValueError(t("cond.order.trigger_glob_required", id=self.id))
        if self.action not in ("run", "dream"):
            raise ValueError(t("cond.order.action_invalid", action=self.action, id=self.id))

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Internal documentation."""
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
            "action": self.action,
        }

    @staticmethod
    def from_dict(d: dict) -> "StandingOrder":
        """Internal documentation."""
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
            action=d.get("action", "run"),
        )

    def with_last_fired(self, ts: float) -> "StandingOrder":
        """Internal documentation."""
        import dataclasses
        return dataclasses.replace(self, last_fired_at=ts)

    def with_enabled(self, enabled: bool) -> "StandingOrder":
        """Internal documentation."""
        import dataclasses
        return dataclasses.replace(self, enabled=enabled)


def _new_order_id() -> str:
    """Internal documentation."""
    return uuid.uuid4().hex


class OrderStore:
    """Internal documentation."""

    def __init__(self, orders_dir: Path | None = None) -> None:
        self._dir = Path(orders_dir).expanduser() if orders_dir else _default_orders_dir()
        self._path = self._dir / "orders.jsonl"

    @property
    def path(self) -> Path:
        """Internal documentation."""
        return self._path

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------

    def list(self) -> list[StandingOrder]:
        """Internal documentation."""
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
        """Internal documentation."""
        for o in self.list():
            if o.id == order_id:
                return o
        return None

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------

    def add(self, order: StandingOrder) -> None:
        """Internal documentation."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(order.to_dict(), ensure_ascii=False) + "\n"
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(line)
        except OSError as exc:
            log.warning("orders: add 写入失败: %s", exc)

    def update(self, order: StandingOrder) -> bool:
        """Internal documentation."""
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
        """Internal documentation."""
        existing = self.list()
        filtered = [o for o in existing if o.id != order_id]
        if len(filtered) == len(existing):
            return False
        self._write_all(filtered)
        return True

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------

    def _write_all(self, orders: list[StandingOrder]) -> None:
        """Internal documentation."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("w", encoding="utf-8") as fh:
                for o in orders:
                    fh.write(json.dumps(o.to_dict(), ensure_ascii=False) + "\n")
        except OSError as exc:
            log.warning("orders: _write_all 写入失败: %s", exc)
