"""RunSnapshot:一次 run 起点的 workspace 文件快照(纯 stdlib,无新依赖)。

设计(spec §2.1):loop.run 入口拍快照到 tempfile.gettempdir()/argos-snapshots/,
剪枝目录复用 runtime.SNAPSHOT_PRUNE_DIRS。 run 结束后保留直到下一次 run 覆盖。
应用退出 / tempdir 清 → 自动失效(不显式清理)。

诚实:take/restore 失败不抛异常,所有路径走返回结果(模型/用户决定下一步)。

签名约定:tar_path 由调用方(App.start_run)预拼好,包含 session_id + run_seq。
本类不感知 session/run 概念,职责窄;这样测试也好写(tmp_path 即可)。
"""
from __future__ import annotations

import shutil
import tarfile
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


SNAPSHOT_ROOT: Path = Path(tempfile.gettempdir()) / "argos-snapshots"
"""快照固定根目录:进程级常驻,跨 run 复用路径槽。"""


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
        from argos_agent.runtime import SNAPSHOT_PRUNE_DIRS

        tar_path.parent.mkdir(parents=True, exist_ok=True)
        partial = tar_path.with_suffix(tar_path.suffix + ".partial")
        with tarfile.open(partial, "w") as tf:
            for p in sorted(workspace.rglob("*")):
                if not p.is_file():
                    continue
                rel = p.relative_to(workspace)
                if any(part in SNAPSHOT_PRUNE_DIRS for part in rel.parts):
                    continue
                tf.add(p, arcname=str(rel))
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
            result.errors.append(("", f"快照文件不存在:{self.tar_path}"))
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
                            result.errors.append((m.name, f"创建父目录失败:{e}"))
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
            result.errors.append(("", f"tar 读取失败:{e}"))
        return result
