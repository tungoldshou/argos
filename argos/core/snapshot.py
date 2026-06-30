"""RunSnapshot:一次 run 起点的 workspace 文件快照(纯 stdlib,无新依赖)。

设计(spec §2.1):loop.run 入口拍快照到 ~/.argos/snapshots/(持久化,跨重启可用),
剪枝目录复用 runtime.SNAPSHOT_PRUNE_DIRS。run 结束后由 manager.recover() 剪枝终态快照。

诚实:take/restore 失败不抛异常,所有路径走返回结果(模型/用户决定下一步)。

签名约定:tar_path 由调用方(App.start_run)预拼好,包含 session_id + run_seq。
本类不感知 session/run 概念,职责窄;这样测试也好写(tmp_path 即可)。
"""
from __future__ import annotations

import logging
import os
import shutil

from argos.i18n import t
import tarfile
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


def _snapshot_root() -> Path:
    """返回快照根目录:优先 ARGOS_CONFIG_DIR 环境变量,其次 ~/.argos/snapshots/。"""
    base = Path(os.environ.get("ARGOS_CONFIG_DIR", "") or (Path.home() / ".argos")).expanduser()
    return base / "snapshots"


SNAPSHOT_ROOT: Path = _snapshot_root()
"""快照固定根目录:持久化在 ~/.argos/snapshots/(同 runs/ ledger/ 等同级),跨重启可用。"""

# 单文件上限:超过此大小的文件跳过(不纳入快照),避免拷贝大型二进制/数据文件
# (如 SQLite DB、视频、大 JSON)让 /undo 冻结几十秒。10MB 经验值:足以覆盖常见源码文件。
_FILE_SIZE_CAP_BYTES: int = 10 * 1024 * 1024  # 10 MB

# 快照总上限:所有已入 tar 文件的累计字节数超过此值时停止添加新文件,/undo 诚实降级
# (已收入的文件仍可还原,余下文件仅告知用户)。200MB 足以覆盖中等项目。
_TOTAL_SIZE_CAP_BYTES: int = 200 * 1024 * 1024  # 200 MB


@dataclass(frozen=True)
class RestoreResult:
    restored: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)

    def __bool__(self) -> bool:  # True = 至少还原一个文件
        return bool(self.restored)


@dataclass(frozen=True)
class RunSnapshot:
    """一次 run 起点的 workspace 快照。不可变;restore 后该实例仍可再 restore(幂等)。"""
    tar_path: Path

    @classmethod
    def take(cls, workspace: Path, tar_path: Path) -> "RunSnapshot":
        """拍 workspace 既有文件快照到 tar 文件。返回新 RunSnapshot。

        不含子目录里的空目录、空文件(只存文件内容)。
        剪枝目录:runtime.SNAPSHOT_PRUNE_DIRS。

        实现:写 .partial + 原子重命名(失败时不留半截快照,旧快照可继续 restore)。
        """
        # 延迟 import 避免循环(若后续 runtime 引到 core 任何东西)
        from argos.runtime import SNAPSHOT_PRUNE_DIRS

        import os as _os

        tar_path.parent.mkdir(parents=True, exist_ok=True)
        partial = tar_path.with_suffix(tar_path.suffix + ".partial")
        total_bytes = 0
        skipped_large: list[str] = []
        cap_hit = False
        with tarfile.open(partial, "w") as tf:
            # os.walk + 原地剪枝:绝不【进入】prune 目录。旧实现用 rglob("*") 会先递归遍历
            # .venv/dist/build/target 里几十万文件(即使后续 continue 跳过 add 也照样 walk),
            # 大项目卡十几秒(2026-06-14 真机 11.4s)。原地裁 dirnames 让 os.walk 不下钻 → 快。
            for dirpath, dirnames, filenames in _os.walk(workspace):
                if cap_hit:
                    break
                dirnames[:] = sorted(d for d in dirnames if d not in SNAPSHOT_PRUNE_DIRS)
                for fn in sorted(filenames):
                    p = Path(dirpath) / fn
                    if not p.is_file():
                        continue
                    # 单文件上限:超大文件跳过,/undo 诚实降级(不阻断 tar,其余文件正常收)
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
                    # 总量上限:累计超限则停止,诚实记录(不假装完整快照)
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
        """用快照还原 workspace 既有文件。失败不抛,所有路径走 RestoreResult。

        语义:
        - 快照里有 → 覆盖写入(走 restored 列表)
        - 快照里有但目标父目录不存在 → 自动 mkdir;失败走 errors
        - 快照里没文件 → 跳过(spec §2.1.2:还原不删 run 中新建文件)
        - 还原 tar 不可读/不存在 → 整批走 errors(空 path)
        """
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
                        # 走 extractfile(返回 ExFileObject)→ 写到目标;处理大文件
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
        """从快照中提取单个文件到 workspace(文件粒度 undo)。

        语义:
        - rel_path 在快照中存在 → 覆盖写回 workspace(文件内容逐字节还原)
        - rel_path 不在快照中(run 中新建) → 删除该文件;结果在 RestoreResult.missing 标注
          (调用方可据此在响应中说明"此文件是任务中新建的,撤销即删除")
        - 路径牢笼:rel_path 解析后必须在 workspace 内(防 ../ 逃逸),否则走 errors(fail-closed)
        - 快照不可读/不存在 → errors(fail-closed)

        Args:
            workspace: workspace 根目录(绝对路径)
            rel_path:  相对于 workspace 的路径(如 "src/main.py")

        Returns:
            RestoreResult —— 不抛异常,调用方按 .errors 判断成败
        """
        result = RestoreResult()

        # 路径牢笼:解析后必须在 workspace 内(防 ../ 路径逃逸,fail-closed)
        try:
            target = (workspace / rel_path).resolve()
            workspace_resolved = workspace.resolve()
            # resolve() 后 target 必须以 workspace 为前缀(含等于自身)
            target.relative_to(workspace_resolved)
        except (ValueError, OSError) as e:
            result.errors.append((rel_path, t("core2.snapshot.path_cage_rejected", error=e)))
            return result

        if not self.tar_path.exists():
            result.errors.append((rel_path, t("core2.snapshot.tar_not_found_file", path=self.tar_path)))
            return result

        # 规范化 rel_path 以匹配 tar 内 arcname(tar 用 str(rel),POSIX 分隔符)
        norm_rel = rel_path.replace("\\", "/").lstrip("/")

        try:
            with tarfile.open(self.tar_path, "r") as tf:
                # 在 tar 成员中查找匹配项
                matched: "tarfile.TarInfo | None" = None
                for m in tf.getmembers():
                    if m.name == norm_rel and m.isfile():
                        matched = m
                        break

                if matched is None:
                    # 快照中没有该文件 → run 中新建 → 撤销 = 删除
                    result.missing.append(rel_path)
                    if target.exists():
                        try:
                            target.unlink()
                        except OSError as e:
                            result.errors.append((rel_path, t("core2.snapshot.new_file_delete_failed", error=e)))
                    return result

                # 快照中有 → 覆盖写回
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
