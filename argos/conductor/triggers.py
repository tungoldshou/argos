"""Internal documentation."""
from __future__ import annotations

import fnmatch
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

log = logging.getLogger("argos.conductor.triggers")


@dataclass(frozen=True, slots=True)
class FileTriggerFact:
    """Internal documentation."""
    path: str
    mtime: float
    glob: str
    detected_at: float


class FileTriggerWatcher:
    """Internal documentation."""

    def __init__(
        self,
        glob_pattern: str,
        base_dir: Path | None = None,
        *,
        debounce_secs: float = 5.0,
        poll_interval: float = 1.0,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._glob = glob_pattern
        self._base = base_dir or Path.cwd()
        self._debounce = debounce_secs
        self._poll_interval = poll_interval
        self._clock: Callable[[], float] = clock if clock is not None else __import__("time").time

        self._known_mtimes: dict[str, float] = {}
        self._last_fired: dict[str, float] = {}

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------

    def poll(self) -> list[FileTriggerFact]:
        """Internal documentation."""
        now = self._clock()
        facts: list[FileTriggerFact] = []
        matched_paths = self._match_glob()

        for path_str in matched_paths:
            p = Path(path_str)
            try:
                current_mtime = p.stat().st_mtime
            except OSError:
                continue

            known_mtime = self._known_mtimes.get(path_str)

            if known_mtime is None or current_mtime != known_mtime:
                last_fired = self._last_fired.get(path_str, float("-inf"))
                if now - last_fired > self._debounce:
                    facts.append(FileTriggerFact(
                        path=path_str,
                        mtime=current_mtime,
                        glob=self._glob,
                        detected_at=now,
                    ))
                    self._last_fired[path_str] = now
                self._known_mtimes[path_str] = current_mtime

        return facts

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------

    def _match_glob(self) -> list[str]:
        """Internal documentation."""
        try:
            base_resolved = self._base.resolve()
            matched = list(self._base.rglob(
                self._glob.lstrip("/")
            ))
            result = []
            for p in matched:
                if not (p.is_file() and fnmatch.fnmatch(p.name, Path(self._glob).name)):
                    continue
                rp = p.resolve()
                if base_resolved != rp and base_resolved not in rp.parents:
                    log.warning(
                        "FileTriggerWatcher: 匹配越出 base_dir,已丢弃: %s (base=%s)",
                        rp, base_resolved,
                    )
                    continue
                result.append(str(rp))
            return result
        except Exception as exc:  # noqa: BLE001
            log.warning("FileTriggerWatcher: glob 匹配失败 %r: %s", self._glob, exc)
            return []
