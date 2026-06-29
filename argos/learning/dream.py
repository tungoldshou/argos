"""dream:夜间整合 —— 跨 run 聚类 + 综合蒸馏(spec: 2026-06-13-dream-consolidation-design)。

铁律(与 distiller 同源):
- 可执行内容(代码段/verify 命令)逐字来自已验证源材料,绝不出自模型;
- narrative(模型产出,pipeline 层调用)只进叙述层,其中的 fenced code block 一律剥除;
- narrative 缺失/为空 → 模板叙述兜底,功能不死。

本模块只做纯函数层:cluster_candidates / synthesize / narrative_prompt。
管道编排(含真模型调用、async、IO)在 DreamPipeline 层(Task 8)追加,不污染纯函数。
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from argos.i18n import t
from argos.learning.candidates import StoredCandidate

if TYPE_CHECKING:
    from pathlib import Path

    from argos.learning.distiller import SkillCandidate

log = logging.getLogger(__name__)

# 锁文件名:从 candidates_root 派生(见 _lock_path_for)。两个进程(CLI + daemon)
# 默认 candidates_root 相同 → 锁路径相同 → 跨进程互斥;测试注入 tmp 时锁随之隔离。
DREAM_LOCK_NAME = ".dream.lock"

# 哨兵:平台无 fcntl 或锁文件打不开时的"无文件锁"占位 fd(release 时忽略)。
_NO_FCNTL_FD = -1


def _lock_path_for(candidates_root: "Path") -> "Path":
    """从 candidates_root 派生一个两进程都算得出的稳定锁路径。

    用 candidates_root.parent —— 候选区父目录(默认 ~/.argos/learning)既稳定
    又随测试注入的 tmp candidates_root 一起隔离,不会污染真实 ~/.argos。
    """
    return candidates_root.parent / DREAM_LOCK_NAME


def _acquire_cross_process_lock(candidates_root: "Path") -> "int | None":
    """抢一个跨进程文件锁(非阻塞)。

    返回:
    - fd(int)  —— 抢到锁;caller 负责在 finally 里 _release_cross_process_lock(fd)。
    - None      —— 锁被另一进程持有(LOCK_NB 立刻失败)→ caller 应跳过本轮。

    平台兜底:fcntl 仅 unix(本项目 macOS/linux 为主)。import 失败 → 降级为
    "仅进程内锁",此处返回 None 会误判忙,故降级语义改为返回哨兵 -1(= 拿到
    一个"无文件锁"的占位 fd,释放时 close 一个不存在的 fd 会被 finally 吞掉)。
    为清晰起见用专门哨兵 _NO_FCNTL_FD,_release 见名识义直接忽略它。
    """
    try:
        import fcntl
    except ImportError:  # pragma: no cover — 非 unix 平台(本项目主线 macOS/linux)
        log.warning("dream: 平台无 fcntl,降级为仅进程内锁(跨进程并发不防护)")
        return _NO_FCNTL_FD

    import os

    lock_path = _lock_path_for(candidates_root)
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(lock_path), os.O_CREAT | os.O_WRONLY, 0o600)
    except OSError as e:
        # 锁文件本身打不开(目录权限等)→ 保守不阻断:降级为仅进程内锁。
        log.warning("dream: 锁文件打开失败,降级仅进程内锁: %s", e)
        return _NO_FCNTL_FD
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        # 已被另一进程持有 → 非阻塞失败。close fd(不持锁),返 None。
        os.close(fd)
        return None
    return fd


def _release_cross_process_lock(fd: "int | None") -> None:
    """释放跨进程文件锁。flock 随 fd close 自动释放;哨兵/None 直接忽略。"""
    if fd is None or fd == _NO_FCNTL_FD:
        return
    import os
    try:
        os.close(fd)   # close 即释放 flock(无需显式 LOCK_UN)
    except OSError as e:  # noqa: BLE001 — 释放失败只记日志,不挂管道
        log.warning("dream: 锁释放失败(已忽略): %s", e)


SIM_THRESHOLD = 0.35       # goal+verify token Jaccard 阈值(宁可不合并)
DEFAULT_MAX_UNITS = 3      # 每晚每车道整合单元上限(防失控烧 token)
MAX_UNIT_SOURCES = 5       # 单个综合单元的源上限:超大簇截取前 5 个,余下留宿隔晚再整合

_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_TILDE_FENCE_RE = re.compile(r"~~~.*?~~~", re.DOTALL)
_CODE_BLOCK_RE = re.compile(r"```python\n(.*?)```", re.DOTALL)
# token 切分:ascii 字母数字 + CJK 统一表意文字段(与 distiller 的英文 slug 互补)
_TOKEN_RE = re.compile(r"[a-z0-9一-鿿]+")


@dataclass(frozen=True, slots=True)
class DreamUnit:
    """一个整合单元:同簇候选(≥2 = 综合;1 = 单例直接走 A/B)。"""
    sources: tuple[StoredCandidate, ...]


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall((text or "").lower()))


def _token_sim(a: str, b: str) -> float:
    """token Jaccard;空集对 → 0.0。"""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _sig(c: StoredCandidate) -> str:
    return f"{c.goal} {c.verify_cmd or ''}"


def _cost_rank_key(c: StoredCandidate) -> tuple:
    """Sort key: passed verdict first, then lower cost_usd, then fewer steps.

    Used to rank candidates within a DreamUnit so synthesize() picks the
    best-performing source as sources[0] (verify_cmd anchor, narrative focus).
    ponytail: sort key only, no new framework.
    """
    verdict_order = 0 if c.verdict_status == "passed" else 1
    cost = c.cost_usd if c.cost_usd is not None else float("inf")
    return (verdict_order, cost, c.steps)


def cluster_candidates(
    cands: list[StoredCandidate], *, max_units: int = DEFAULT_MAX_UNITS,
) -> list[DreamUnit]:
    """贪心单链聚类:依次归入首个相似度 ≥ SIM_THRESHOLD 的簇,否则开新簇。

    确定性:输入顺序决定输出顺序(caller 已按目录名 sorted)。
    双车道上限(评审裁定):多源簇与单例各自封顶 max_units —— 跨 run 综合
    (头牌价值)永远不会被单例挤掉,单例也不会饿死(积压的隔晚消化)。
    每单元源上限 MAX_UNIT_SOURCES(评审裁定:截取+留宿):超大簇只取前
    MAX_UNIT_SOURCES 个源组成**一个** unit(保序),余下的源不进本轮任何
    unit —— 它们保持未消费,下晚重新聚类再整合。绝不把同簇切成多个小单元:
    多源综合是本特性头牌价值,拆散同类材料是自残。
    caller 应对输入规模负责(list_unconsumed 的候选区有积压可能);
    O(n²) 在夜间规模(n<100)可忽略。
    """
    clusters: list[list[StoredCandidate]] = []
    for c in cands:
        for cl in clusters:
            if _token_sim(_sig(c), _sig(cl[0])) >= SIM_THRESHOLD:
                cl.append(c)
                break
        else:
            clusters.append([c])
    # 超大簇截取:每簇至多 MAX_UNIT_SOURCES 个源;被留宿的源本轮不消费,
    # 候选区里仍是 unconsumed,下晚 list_unconsumed 会再捞出来重新聚类。
    multi = [cl[:MAX_UNIT_SOURCES] for cl in clusters if len(cl) >= 2]
    single = [cl for cl in clusters if len(cl) == 1]
    picked = multi[:max_units] + single[:max_units]
    return [DreamUnit(sources=tuple(cl)) for cl in picked]


def _strip_code_blocks(text: str) -> str:
    """三层剥除模型输出中的可执行内容(铁律硬防线):

    ① 配对反引号 fence(```...```)整段剥除;
    ② 配对波浪 fence(~~~...~~~)整段剥除;
    ③ 不闭合 fence:剥完配对后若仍残留 "```" 或 "~~~"(奇数个/未闭合 ——
       模型截断输出最常见形态是开了 fence 没关),从第一个残留 fence 标记起
       截断到串尾。截到尾比留着安全。
    """
    out = _FENCE_RE.sub("", text or "")
    out = _TILDE_FENCE_RE.sub("", out)
    cuts = [p for p in (out.find("```"), out.find("~~~")) if p != -1]
    if cuts:
        out = out[:min(cuts)]
    return out.strip()


def _extract_code(body_markdown: str) -> str:
    """从源候选 SKILL.md 抽 python 代码块原文(distiller 产物格式)。"""
    return "\n\n".join(m.strip() for m in _CODE_BLOCK_RE.findall(body_markdown or ""))


def _merged_name(unit: DreamUnit) -> str:
    from argos.learning.distiller import slugify_goal
    # 双截断:slugify_goal 自身截 40,加 "dream-" 前缀后再截 40 → 有效 slug ≤34 字符
    return ("dream-" + slugify_goal(unit.sources[0].goal))[:40]


def narrative_prompt(unit: DreamUnit) -> str:
    """构造叙述层提示词(纯函数;模型调用在 DreamPipeline 层,async 友好)。"""
    return (
        t("learn.dream.narrative_prompt")
        + "\n".join(f"- {s.goal}" for s in unit.sources)
    )


def synthesize(
    unit: DreamUnit, *, narrative: str | None = None,
) -> "SkillCandidate | None":
    """把一个 DreamUnit 综合成 SkillCandidate(不落盘,晋升由 promotion_gate 决定)。

    narrative 是预先算好的叙述文本(模型产出,pipeline 层负责调用与失败兜底);
    本函数纯同步纯函数 —— 进来什么文本都先剥代码块,None/空 → 模板兜底。
    """
    from pathlib import Path

    from argos.learning.distiller import SkillCandidate

    if not unit.sources:
        return None
    name = _merged_name(unit)
    runs = [s.source_run for s in unit.sources]

    # 叙述层:剥代码(铁律:模型输出永远不许携带可执行内容) or 模板兜底
    text = _strip_code_blocks(narrative or "")
    if not text:
        text = t("learn.dream.synthesize_fallback", n=len(unit.sources))

    lines = [
        "---",
        f"name: {name}",
        "capabilities: []",
        "enabled: false",
        f"source_runs: [{', '.join(runs)}]",
        "---",
        "",
        f"# {name}",
        "",
        "## When to use",
        "",
        text,
        "",
        "## Verified sources",
        "",
    ]
    for s in unit.sources:
        lines += [f"### source_run {s.source_run}", "", f"**Goal**: {s.goal}", ""]
        code = _extract_code(s.body_markdown)
        if code:
            lines += ["```python", code, "```", ""]
        if s.verify_cmd:
            lines += ["Verify:", "", "```bash", s.verify_cmd, "```", ""]
    return SkillCandidate(
        name=name,
        body_markdown="\n".join(lines),
        verify_cmd=unit.sources[0].verify_cmd,
        skill_md_path=Path("unpromoted"),
    )


@dataclass(frozen=True, slots=True)
class HintedRunner:
    """B 侧 runner:把综合 skill 的叙述+源经验作为 hint 前置到 task.goal。

    promotion_gate 不感知 hint(契约注释言明是 runner 的事);A 侧用裸 runner。
    max_hint_len:hint 截断阈值(字符数)。hint 来自 synthesize(),5 源 × distiller
    可达 10k-50k+ 字符;前置到 task.goal 后 B 侧模型焦点会被稀释,截断防假阴性。
    """
    inner: object
    hint: str
    max_hint_len: int = 4000

    def run(self, task, *, model_tier: str):
        import dataclasses
        truncated = (self.hint or "")[:self.max_hint_len]  # hint=None 防 TypeError
        hinted = dataclasses.replace(
            task, goal=f"{t('learn.dream.hinted_runner_prefix')}{truncated}\n\n---\n\n{task.goal}")
        return self.inner.run(hinted, model_tier=model_tier)


def build_eval_tasks(unit: DreamUnit) -> tuple[list, list]:
    """从 unit 源构造 A/B 语料。返回 (tasks, workspace_gone_sources)。

    workspace 不存在或无 verify_cmd 的源进 gone 列表(消费规则:证据永远
    拿不到 → caller 标记 consumed)。
    """
    from pathlib import Path as _Path

    from argos.eval.corpus import EvalTask

    tasks: list = []
    gone: list[StoredCandidate] = []
    for s in unit.sources:
        ws = _Path(s.workspace) if s.workspace else None
        if ws is None or not ws.exists():
            gone.append(s)
            continue
        if not s.verify_cmd:
            gone.append(s)
            continue
        tasks.append(EvalTask(
            id=f"dream-{s.source_run[:12]}", category="dream", difficulty="n/a",
            title=s.goal[:60], goal=s.goal, verify_cmd=s.verify_cmd,
            setup_cmd=None, expected_files=(), working_dir=ws, corpus_version=0,
        ))
    return tasks, gone


# ── DreamPipeline 编排层(Task 8:含真模型调用、async、IO) ────────────────────

@dataclass(frozen=True, slots=True)
class DreamReport:
    """一次 Dream 的诚实结果计数。"""
    units_total: int = 0
    promoted: int = 0
    rejected: int = 0
    skipped: int = 0
    memory_merged: int = 0
    memory_archived: int = 0
    report_path: str = ""


def has_material(candidates_root: "Path", *, min_units: int = 1) -> bool:
    """材料门:候选区有未消费材料才值得建议(供 conductor_supervisor 过滤)。"""
    from argos.learning.candidates import list_unconsumed
    return len(list_unconsumed(candidates_root)) >= min_units


class DreamPipeline:
    """夜间整合编排:scan → cluster → synthesize → promote → memory → report。

    设计纪律:
    - 纯函数层(cluster/synthesize/narrative)只产数据;本层负责真模型调用、async、IO。
    - 单飞:同一时刻只允许一次 Dream(防两个 conductor tick 撞车烧 token + 撕扯候选区)。
    - 诚实计数:promoted/rejected/skipped 严格反映实际处理路径,绝不编造。
    - 任何单元失败不挂整条管道(单元级 try/except);记忆整理失败降级空报告。
    - 留宿契约:cluster_candidates 截掉的源不进任何 unit → 自然不被本轮碰过 →
      仍 unconsumed,下晚 list_unconsumed 重新捞出再聚类(与 dream.py
      cluster_candidates 的"截取+留宿"注释呼应,本层不额外消费它们)。
    """

    def __init__(
        self, *,
        candidates_root: "Path",
        skills_root: "Path",
        memory_dir: "Path",
        dreams_dir: "Path",
        runner_factory,                       # (hint: str | None) -> runner
        narrate=None,                         # (prompt: str) -> str | Awaitable[str]
        broadcast_fn=None,                    # (payload: dict) -> None
        max_units: int = DEFAULT_MAX_UNITS,
    ) -> None:
        self._candidates_root = candidates_root
        self._skills_root = skills_root
        self._memory_dir = memory_dir
        self._dreams_dir = dreams_dir
        self._runner_factory = runner_factory
        self._narrate = narrate
        self._broadcast_fn = broadcast_fn
        self._max_units = max_units
        # 懒初始化锁:__init__ 里建 asyncio.Lock 会绑创建时的事件循环,
        # 而 run() 可能跑在另一个 asyncio.run() 的新循环里 → 绑错循环会失效。
        # 推迟到 run() 首次执行时按当前运行循环创建。
        # run_id 注入由 caller(T9 daemon 的 _dream_bcast)在 broadcast payload 里完成 ——
        # 本管道只产 {"kind": ..., **payload},不感知 _conductor 虚拟通道。
        self._lock: "asyncio.Lock | None" = None

    @property
    def is_running(self) -> bool:
        """只读:当前是否有一次 Dream 正在跑(单飞锁已持有)。

        供 T9 daemon 的 _confirm_dream / POST /dream/run 先探锁 → 409 dream_busy,
        避免 create_task 后才被 run() 内的单飞判定静默吞掉(返 None,客户端无感)。
        锁未初始化(从未 run 过)→ 未在跑。
        """
        return self._lock is not None and self._lock.locked()

    def cross_process_busy(self) -> bool:
        """只读探针:另一进程(如 CLI)是否正持有跨进程 Dream 锁。

        供 daemon 在派生 pipeline.run() 任务前预检 —— 否则 run() 因跨进程锁返
        None 是异步发生的,daemon 已回 202 却没真跑(review#4:确认不要 202 却没跑)。
        非阻塞:抢到立刻释放(run() 稍后会重抢);抢不到 → True(忙)。
        本进程自己正持锁(is_running)时不算"另一进程忙",由 is_running 单独判定。
        """
        fd = _acquire_cross_process_lock(self._candidates_root)
        if fd is None:
            return True
        _release_cross_process_lock(fd)
        return False

    async def run(self) -> "DreamReport | None":
        """跑一次完整 Dream。已有 Dream 在跑 → log + 返 None。

        两层单飞:
        ① 进程内 asyncio.Lock —— 同进程两个 conductor tick 撞车防护;
        ② 跨进程 fcntl 文件锁 —— CLI 与 daemon 是独立进程,asyncio.Lock 跨进程
           不可见;无文件锁则两进程并发会撕裂写候选区/记忆(review#4)。
        语义一致:任一层判定"已在跑" → 返 None(与既有单飞约定相同)。
        """
        import asyncio
        if self._lock is None:
            self._lock = asyncio.Lock()
        if self._lock.locked():
            log.info("dream: 已有整合在跑,跳过本次(进程内单飞)")
            return None
        async with self._lock:
            # 进程内锁已持有 → 现在抢跨进程锁(另一进程可能正持有)。
            lock_fd = _acquire_cross_process_lock(self._candidates_root)
            if lock_fd is None:
                log.info("dream: 另一进程的整合在跑,跳过本次(跨进程单飞)")
                return None
            try:
                return await self._run_locked()
            finally:
                _release_cross_process_lock(lock_fd)

    async def _run_locked(self) -> "DreamReport":
        import time

        from argos.learning.candidates import list_unconsumed

        promoted = rejected = skipped = 0

        self._emit("dream_progress", stage="scan", detail="", ts=time.time())
        cands = list_unconsumed(self._candidates_root)
        # Rank by cost-efficiency before clustering so sources[0] in each DreamUnit
        # is the cheapest verified candidate (synthesize/build_eval_tasks use sources[0]).
        cands = sorted(cands, key=_cost_rank_key)
        units = cluster_candidates(cands, max_units=self._max_units)
        self._emit("dream_progress", stage="cluster",
                   detail=f"{len(units)} units", ts=time.time())

        for unit in units:
            try:
                outcome = await self._process_unit(unit)
                promoted += outcome[0]
                rejected += outcome[1]
                skipped += outcome[2]
            except Exception as e:  # noqa: BLE001 — 单元失败不挂管道
                log.warning("dream: 单元处理失败,跳过: %s", e)
                skipped += 1

        # 记忆整理阶段(失败降级空报告)
        self._emit("dream_progress", stage="memory", detail="", ts=time.time())
        try:
            from argos.memory.consolidate import consolidate
            mem_report = consolidate(self._memory_dir)
        except Exception as e:  # noqa: BLE001
            from argos.memory.consolidate import ConsolidationReport
            log.warning("dream: 记忆整理失败,降级空报告: %s", e)
            mem_report = ConsolidationReport()

        report = DreamReport(
            units_total=len(units),
            promoted=promoted, rejected=rejected, skipped=skipped,
            memory_merged=mem_report.merged, memory_archived=mem_report.archived,
        )
        ts = time.time()
        report_path = self._write_report_line(report, ts=ts)
        report = DreamReport(
            units_total=report.units_total, promoted=report.promoted,
            rejected=report.rejected, skipped=report.skipped,
            memory_merged=report.memory_merged, memory_archived=report.memory_archived,
            report_path=report_path,
        )
        # 收尾标记:DreamProgressEvent docstring 列了 done 阶段,管道必须真 emit 它,
        # 否则 done 是空头承诺。放在 dream_report 之前(进度先到尾,再发结果汇总)。
        self._emit("dream_progress", stage="done", detail="", ts=ts)
        self._emit(
            "dream_report",
            units_total=report.units_total, promoted=report.promoted,
            rejected=report.rejected, skipped=report.skipped,
            memory_merged=report.memory_merged, memory_archived=report.memory_archived,
            report_path=report.report_path, ts=ts,
        )
        return report

    async def _process_unit(self, unit: "DreamUnit") -> tuple[int, int, int]:
        """处理单个整合单元。返回 (promoted, rejected, skipped) 增量(各 0/1)。"""
        import inspect

        from argos.learning.candidates import mark_consumed
        from argos.learning.promotion_gate import promote

        # ① 叙述层:模型调用在本层(async 友好),失败模板兜底。
        narrative: "str | None" = None
        if self._narrate is not None:
            try:
                raw = self._narrate(narrative_prompt(unit))
                narrative = (await raw) if inspect.isawaitable(raw) else raw
            except Exception as e:  # noqa: BLE001 — 叙述失败不致命,模板兜底
                log.warning("dream: 叙述生成失败,模板兜底: %s", e)
                narrative = None

        # ② 综合候选
        cand = synthesize(unit, narrative=narrative)
        if cand is None:
            return (0, 0, 1)

        # ③ 构造 A/B 语料;workspace_gone 源永远拿不到证据 → 标 consumed 防夜夜重复
        tasks, gone = build_eval_tasks(unit)
        for s in gone:
            mark_consumed(s.path, reason="workspace_gone")
        if not tasks:
            # 全是 gone 源(本轮无可跑语料);live 源(若有)不消费,下晚重试。
            return (0, 0, 1)

        # ④ A/B 晋升评估(A=裸 runner,B=带 hint runner)。
        # promote 是同步 CPU/子进程密集(真 A/B eval 含 verify 子进程)——
        # 放进线程池跑,避免阻塞 daemon 事件循环(并让单飞锁在 await 点真正生效)。
        import asyncio
        res = await asyncio.to_thread(
            promote,
            candidate=cand, tasks=tasks,
            runner=self._runner_factory(None),
            runner_b=self._runner_factory(cand.body_markdown),
            skills_root=self._skills_root,
        )

        # ⑤ 按判决消费 live 源(gone 已消费,不重复)
        live = [s for s in unit.sources if s not in gone]
        if res.promoted:
            for s in live:
                mark_consumed(s.path, reason="promoted")
            result = (1, 0, 0)
        # promotion_gate reason 格式: 'no_improvement(a=N/T,b=N/T)' — 改格式需同步此处
        elif res.reason.startswith("no_improvement"):
            for s in live:
                mark_consumed(s.path, reason="rejected_ab")
            result = (0, 1, 0)
        elif res.reason.startswith("name_collision:"):
            # 确定性冲突:非学习技能同名 → 消费源防死循环。
            # name_collision_unreadable(瞬态 I/O 失败)不在此处,留给 else 重试。
            for s in live:
                mark_consumed(s.path, reason="name_collision")
            result = (0, 0, 1)
        else:
            # runner_error / name_collision_unreadable / write_failed 等:不消费,下晚重试。
            result = (0, 0, 1)

        import time
        self._emit("dream_progress", stage="promote",
                   detail=res.reason, ts=time.time())
        return result

    def _write_report_line(self, report: "DreamReport", *, ts: float) -> str:
        """写报告行到 <dreams_dir>/<YYYY-MM-DD>.jsonl。失败 log + 返 ""。"""
        from datetime import datetime

        from argos.jsonl_log import append_line
        try:
            day = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
            path = self._dreams_dir / f"{day}.jsonl"
            append_line(path, {
                "ts": ts,
                "units_total": report.units_total,
                "promoted": report.promoted,
                "rejected": report.rejected,
                "skipped": report.skipped,
                "memory_merged": report.memory_merged,
                "memory_archived": report.memory_archived,
            })
            return str(path)
        except Exception as e:  # noqa: BLE001 — 报告落盘失败不致命
            log.warning("dream: 报告落盘失败: %s", e)
            return ""

    def _emit(self, kind: str, **payload) -> None:
        """广播一条 dream 事件。broadcast_fn 为 None → 直接返;失败 log 不抛。

        async-aware:若 broadcast_fn 是协程函数,调用后返回 coroutine,
        用 asyncio.get_running_loop().create_task() 调度,确保 T9 daemon 的
        async fanout 不会被静默垃圾回收(coroutine never awaited)。
        """
        if self._broadcast_fn is None:
            return
        try:
            result = self._broadcast_fn({"kind": kind, **payload})
            if inspect.iscoroutine(result):
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(result)
                except RuntimeError:
                    # 无运行中的 event loop(同步调用场景)—— 关闭并同步执行
                    asyncio.run(result)
        except Exception as e:  # noqa: BLE001 — 广播失败不挂管道
            log.warning("dream: 事件广播失败(%s): %s", kind, e)
