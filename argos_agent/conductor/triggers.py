"""FileTriggerWatcher — mtime 轮询式文件触发器（设计 §9 自治面）。

职责：纯探测，不执行任何副作用。
- 以 mtime 轮询替代 inotify/watchdog（零新依赖）。
- 支持 glob 模式（fnmatch 语义，跨目录 **）。
- 去抖（debounce）：同一文件在 debounce_secs 内只触发一次。
- 返回触发事实（FileTriggerFact），不启动 run、不产生 suggestion。
"""
from __future__ import annotations

import fnmatch
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

log = logging.getLogger("argos.conductor.triggers")


@dataclass(frozen=True, slots=True)
class FileTriggerFact:
    """一次文件触发事实。

    字段：
        path        变化文件的绝对路径字符串
        mtime       触发时的文件 mtime（Unix float）
        glob        匹配该文件的 glob 模式
        detected_at 探测到变化时的时钟时间（注入 clock() 的返回值）
    """
    path: str
    mtime: float
    glob: str
    detected_at: float


class FileTriggerWatcher:
    """基于 mtime 轮询的文件触发器。

    参数：
        glob_pattern    文件 glob 模式（fnmatch 语义，支持 **）
        base_dir        glob 搜索根目录（默认 Path.cwd()）
        debounce_secs   同一文件两次触发的最短间隔秒数（默认 5.0）
        poll_interval   两次 poll() 之间的最短间隔（仅文档语义；
                        实际调度由外部 tick/loop 决定，不在此强制 sleep）
        clock           可注入时钟函数，默认 time.time()（禁止内部直接 import time.time）

    设计约束：
        - 本类只暴露 poll() 方法，不含任何 sleep / thread / asyncio。
        - poll() 幂等：同一次调用内多次 glob 匹配只产出一次 fact/文件。
        - 去抖：_last_fired[path] 记录上次触发时的 clock 时间，
          未超过 debounce_secs 的变化被静默吞掉。
    """

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

        # path(str) → 已知的 mtime（float），用于变化检测
        self._known_mtimes: dict[str, float] = {}
        # path(str) → 上次触发时的 clock 时间（float），用于去抖
        self._last_fired: dict[str, float] = {}

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def poll(self) -> list[FileTriggerFact]:
        """执行一次轮询，返回本轮检测到的触发事实列表。

        算法：
          1. 用 fnmatch 在 base_dir 下递归匹配 glob_pattern。
          2. 对每个匹配文件，读取当前 mtime。
          3. 若 mtime 与上次记录不同（新文件 or 变化），且去抖窗口已过 → 产出 fact。
          4. 更新 _known_mtimes 和 _last_fired。
        """
        now = self._clock()
        facts: list[FileTriggerFact] = []
        matched_paths = self._match_glob()

        for path_str in matched_paths:
            p = Path(path_str)
            try:
                current_mtime = p.stat().st_mtime
            except OSError:
                # 文件读取失败（竞态删除等）→ 跳过
                continue

            known_mtime = self._known_mtimes.get(path_str)

            # 文件新出现或 mtime 变化
            if known_mtime is None or current_mtime != known_mtime:
                # 去抖检查（严格大于：等于 debounce_secs 时不触发）
                # _NEVER_FIRED = -inf，保证首次进入时 now - (-inf) > debounce 永远成立
                last_fired = self._last_fired.get(path_str, float("-inf"))
                if now - last_fired > self._debounce:
                    facts.append(FileTriggerFact(
                        path=path_str,
                        mtime=current_mtime,
                        glob=self._glob,
                        detected_at=now,
                    ))
                    self._last_fired[path_str] = now
                # 无论是否触发，都更新已知 mtime（避免反复进入此分支）
                self._known_mtimes[path_str] = current_mtime

        return facts

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    def _match_glob(self) -> list[str]:
        """在 base_dir 下递归展开 glob_pattern，返回绝对路径字符串列表。

        边界牢笼:pattern 含 `..` 时 rglob 会跟出 base_dir 之外 —— 每个匹配
        resolve 后必须仍在 base_dir 牢笼内,越界一律丢弃(fail-closed,终审 major 修复)。
        """
        try:
            base_resolved = self._base.resolve()
            matched = list(self._base.rglob(
                # Path.rglob 不接受绝对路径；去掉前缀 **/ 让 rglob 处理递归
                self._glob.lstrip("/")
            ))
            # 过滤：fnmatch 二次校验（处理 rglob 的宽松匹配）+ 边界断言
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
