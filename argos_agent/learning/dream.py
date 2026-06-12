"""dream:夜间整合 —— 跨 run 聚类 + 综合蒸馏(spec: 2026-06-13-dream-consolidation-design)。

铁律(与 distiller 同源):
- 可执行内容(代码段/verify 命令)逐字来自已验证源材料,绝不出自模型;
- narrative(模型产出,pipeline 层调用)只进叙述层,其中的 fenced code block 一律剥除;
- narrative 缺失/为空 → 模板叙述兜底,功能不死。

本模块只做纯函数层:cluster_candidates / synthesize / narrative_prompt。
管道编排(含真模型调用、async、IO)在 DreamPipeline 层(Task 8)追加,不污染纯函数。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from argos_agent.learning.candidates import StoredCandidate

if TYPE_CHECKING:
    from argos_agent.learning.distiller import SkillCandidate

log = logging.getLogger(__name__)

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
    from argos_agent.learning.distiller import slugify_goal
    # 双截断:slugify_goal 自身截 40,加 "dream-" 前缀后再截 40 → 有效 slug ≤34 字符
    return ("dream-" + slugify_goal(unit.sources[0].goal))[:40]


def narrative_prompt(unit: DreamUnit) -> str:
    """构造叙述层提示词(纯函数;模型调用在 DreamPipeline 层,async 友好)。"""
    return (
        "以下是多次已验证成功的任务经验,请用 2-4 句中文总结"
        "「何时适用」与「注意事项」。只写文字,不要代码:\n"
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

    from argos_agent.learning.distiller import SkillCandidate

    if not unit.sources:
        return None
    name = _merged_name(unit)
    runs = [s.source_run for s in unit.sources]

    # 叙述层:剥代码(铁律:模型输出永远不许携带可执行内容) or 模板兜底
    text = _strip_code_blocks(narrative or "")
    if not text:
        text = "本技能综合自 %d 次已验证通过的 run(目标见下),适用于同类任务。" % len(unit.sources)

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
        truncated = self.hint[:self.max_hint_len]
        hinted = dataclasses.replace(
            task, goal=f"可参考以下已验证经验:\n{truncated}\n\n---\n\n{task.goal}")
        return self.inner.run(hinted, model_tier=model_tier)


def build_eval_tasks(unit: DreamUnit) -> tuple[list, list]:
    """从 unit 源构造 A/B 语料。返回 (tasks, workspace_gone_sources)。

    workspace 不存在或无 verify_cmd 的源进 gone 列表(消费规则:证据永远
    拿不到 → caller 标记 consumed)。
    """
    from pathlib import Path as _Path

    from argos_agent.eval.corpus import EvalTask

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
