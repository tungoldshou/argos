"""Internal documentation."""
from __future__ import annotations

import logging
import shutil

from argos.i18n import t
import tarfile
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


def _snapshot_root() -> Path:
    """Internal documentation."""
    from argos import config as C
    base = Path(C.get("ARGOS_CONFIG_DIR") or (Path.home() / ".argos")).expanduser()
    return base / "snapshots"


SNAPSHOT_ROOT: Path = _snapshot_root()
"""Snapshot storage root under ARGOS_CONFIG_DIR/snapshots."""

_FILE_SIZE_CAP_BYTES: int = 10 * 1024 * 1024  # 10 MB

_TOTAL_SIZE_CAP_BYTES: int = 200 * 1024 * 1024  # 200 MB


@dataclass(frozen=True)
class RestoreResult:
    restored: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.restored)


@dataclass(frozen=True)
class RunSnapshot:
    """Internal documentation."""
    tar_path: Path

    @classmethod
    def take(cls, workspace: Path, tar_path: Path) -> "RunSnapshot":
        """Internal documentation."""
        from argos.runtime import SNAPSHOT_PRUNE_DIRS

        import os as _os

        tar_path.parent.mkdir(parents=True, exist_ok=True)
        partial = tar_path.with_suffix(tar_path.suffix + ".partial")
        total_bytes = 0
        skipped_large: list[str] = []
        cap_hit = False
        with tarfile.open(partial, "w") as tf:
            for dirpath, dirnames, filenames in _os.walk(workspace):
                if cap_hit:
                    break
                dirnames[:] = sorted(d for d in dirnames if d not in SNAPSHOT_PRUNE_DIRS)
                for fn in sorted(filenames):
                    p = Path(dirpath) / fn
                    if not p.is_file():
                        continue
                    try:
                        fsize = p.stat().st_size
                    except OSError:
                        continue
                    if fsize > _FILE_SIZE_CAP_BYTES:
                        rel = str(p.relative_to(workspace))
                        skipped_large.append(rel)
                        logger.debug("snapshot: 跳过超大文件 %s (%d B > %d B 上限)",
                                     rel, fsize, _FILE_SIZE_CAP_BYTES)
                        continue
                    if total_bytes + fsize > _TOTAL_SIZE_CAP_BYTES:
                        cap_hit = True
                        logger.warning(
                            "snapshot: 总量超限 %d MB,剩余文件未纳入快照 — /undo 仅能还原已收入部分",
                            _TOTAL_SIZE_CAP_BYTES // 1024 // 1024,
                        )
                        break
                    tf.add(p, arcname=str(p.relative_to(workspace)))
                    total_bytes += fsize
        if skipped_large:
            logger.info("snapshot: %d 个大文件已跳过(不影响 /undo 其余文件还原)", len(skipped_large))
        partial.rename(tar_path)
        return cls(tar_path=tar_path)

    def restore(self, workspace: Path) -> RestoreResult:
        """Internal documentation."""
        result = RestoreResult()
        if not self.tar_path.exists():
            result.errors.append(("", t("core2.snapshot.tar_not_found_restore", path=self.tar_path)))
            return result
        try:
            with tarfile.open(self.tar_path, "r") as tf:
                members = tf.getmembers()
                for m in members:
                    target = workspace / m.name
                    if not m.isfile():
                        continue
                    if not target.parent.exists():
                        try:
                            target.parent.mkdir(parents=True, exist_ok=True)
                        except OSError as e:
                            result.errors.append((m.name, t("core2.snapshot.mkdir_failed", error=e)))
                            continue
                    try:
                        src = tf.extractfile(m)
                        if src is None:
                            result.missing.append(m.name)
                            continue
                        with target.open("wb") as dst:
                            shutil.copyfileobj(src, dst)
                        result.restored.append(m.name)
                    except OSError as e:
                        result.errors.append((m.name, str(e)))
        except tarfile.TarError as e:
            result.errors.append(("", t("core2.snapshot.tar_read_failed", error=e)))
        return result

    def restore_file(self, workspace: Path, rel_path: str) -> RestoreResult:
        """Internal documentation."""
        result = RestoreResult()

        try:
            target = (workspace / rel_path).resolve()
            workspace_resolved = workspace.resolve()
            target.relative_to(workspace_resolved)
        except (ValueError, OSError) as e:
            result.errors.append((rel_path, t("core2.snapshot.path_cage_rejected", error=e)))
            return result

        if not self.tar_path.exists():
            result.errors.append((rel_path, t("core2.snapshot.tar_not_found_file", path=self.tar_path)))
            return result

        norm_rel = rel_path.replace("\\", "/").lstrip("/")

        try:
            with tarfile.open(self.tar_path, "r") as tf:
                matched: "tarfile.TarInfo | None" = None
                for m in tf.getmembers():
                    if m.name == norm_rel and m.isfile():
                        matched = m
                        break

                if matched is None:
                    result.missing.append(rel_path)
                    if target.exists():
                        try:
                            target.unlink()
                        except OSError as e:
                            result.errors.append((rel_path, t("core2.snapshot.new_file_delete_failed", error=e)))
                    return result

                if not target.parent.exists():
                    try:
                        target.parent.mkdir(parents=True, exist_ok=True)
                    except OSError as e:
                        result.errors.append((rel_path, t("core2.snapshot.mkdir_failed_file", error=e)))
                        return result
                try:
                    src = tf.extractfile(matched)
                    if src is None:
                        result.errors.append((rel_path, t("core2.snapshot.extractfile_none")))
                        return result
                    with target.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
                    result.restored.append(rel_path)
                except OSError as e:
                    result.errors.append((rel_path, str(e)))
        except tarfile.TarError as e:
            result.errors.append((rel_path, t("core2.snapshot.tar_read_failed_file", error=e)))
        return result
