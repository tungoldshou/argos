"""distiller:从一条 passed 轨迹提炼"可复用技能"候选 SKILL.md(模板化产物)。

关键设计:
- 不调真模型提炼(spec 假定"模型提炼"会编"未验证"内容,违反"只存被验证过的"铁律)。
  走模板化产物:从轨迹抽 code_action 段 + verify 脚本,产出结构化 markdown。
- 候选 SKILL.md 含 frontmatter(enabled: false 沿用 install 的 user review gate 约定)
  + body(goal / 通过的步骤 / 代码片段 / verify 脚本)。
- builtin 名字硬拒(下层 promotion_gate 拒;distill 不拒 —— 候选阶段是"可能升级",判定在 promote)。

事件读取:不走 daemon.store.RunStore.replay()(它要求第一行是 run_meta,daemon 严格契约;
distill 是消费者,可读任意 JSONL,坏行跳过)。store 字段保留 RunStore-like 接口(.replay)
以兼容未来 daemon 集成 —— 测试场景 distill 用 read_events() 兜底。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Protocol


class _EventSource(Protocol):
    """distill 接受的事件源:有 .replay(run_id) -> Iterable[dict] 即可。"""
    def replay(self, run_id: str) -> Iterable[dict]: ...  # noqa: D401, ANN001


@dataclass(frozen=True, slots=True)
class SkillCandidate:
    """distill 产出的可晋升候选。"""

    name: str
    body_markdown: str
    verify_cmd: str | None
    skill_md_path: Path


# 名字清洗:从 goal 抽短 slug,降长、剔特殊字符,空则用 fallback
def slugify_goal(goal: str, fallback: str = "learned") -> str:
    g = (goal or "").strip().lower()
    if not g:
        return fallback
    # 只留字母数字 + 连字符,折叠连续 -
    g = re.sub(r"[^a-z0-9]+", "-", g)
    g = re.sub(r"-+", "-", g).strip("-")
    if not g:
        return fallback
    return g[:40]  # 上限 40 字符


# 旧名别名:dream/distiller 跨模块统一用公开名 slugify_goal,保留旧名免破坏内部引用
_slugify_goal = slugify_goal


def _format_code_block(snippets: list[str]) -> str:
    """拼所有 code_action 片段到一个 markdown 代码块。"""
    if not snippets:
        return ""
    body = "\n\n".join(snippets)
    return f"```python\n{body.rstrip()}\n```"


def _build_markdown(
    *,
    name: str,
    goal: str,
    verify_cmd: str | None,
    code_snippets: list[str],
    source_run_id: str,
) -> str:
    """构造 SKILL.md 内容(frontmatter + body)。"""
    fm_lines = [
        "---",
        f"name: {name}",
        "capabilities: []",
        "enabled: false",   # 沿用 install 的 user review gate 约定
        f"source_run: {source_run_id}",
        "---",
        "",
        f"# {name}",
        "",
        f"**Goal**: {goal or '(no goal)'}",
        "",
        "## What worked",
        "",
        "本技能来自一次通过 verify 的实际 run(可重放)。",
        "",
    ]
    body = "\n".join(fm_lines)
    if code_snippets:
        body += "### Key code\n\n"
        body += _format_code_block(code_snippets) + "\n\n"
    if verify_cmd:
        body += "## Verify (re-runnable)\n\n"
        body += f"```bash\n{verify_cmd}\n```\n\n"
        body += "退出码 0 = 通过(本技能晋升要求 A/B 实测通过率严格 > 基线)。\n"
    return body


def _read_jsonl_relaxed(path: Path) -> list[dict]:
    """直接读 JSONL,坏行跳过(不要求第一行是 run_meta;distill 是消费者)。"""
    out: list[dict] = []
    if not path.exists():
        return out
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _events_from_store(store: Any, run_id: str) -> list[dict]:
    """从 store 抽 events:三道兜底(按数据源差异)。

    1) store 有 .replay 且能跑(daemon RunStore)→ 用它(契约)
    2) store 有 .runs_dir → 直接读 JSONL(测试场景,无 run_meta 守卫)
    3) 其他 → []
    """
    # 1) RunStore-like(daemon 真路径,replay 有 run_meta 守卫)
    try:
        if hasattr(store, "replay"):
            return list(store.replay(run_id))
    except Exception:  # noqa: BLE001 — run_meta 守卫挂了就走宽松路径
        pass
    # 2) 宽松:有 runs_dir 直接读 JSONL
    runs_dir = getattr(store, "runs_dir", None) or getattr(store, "_runs_dir", None)
    if runs_dir is not None:
        p = Path(runs_dir) / f"{run_id}.jsonl"
        return _read_jsonl_relaxed(p)
    return []


def distill_run_to_skill(
    *,
    run_id: str,
    store: Any,
    goal: str,
    verify_cmd: str | None,
    skills_root: Path,
) -> SkillCandidate | None:
    """从一条 passed run 抽轨迹 → 候选 SkillCandidate。

    不落盘 —— 落盘由 promotion_gate 决定(晋升后才写 skills_root/<name>/SKILL.md)。

    失败模式:
    - store 读不到 / 跑挂 → 返 None
    - 没抽到任何 code_action → 返 None(产物无意义)
    """
    events = _events_from_store(store, run_id)
    if not events:
        return None

    snippets: list[str] = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        kind = ev.get("kind")
        if kind == "code_action":
            code = ev.get("code")
            if isinstance(code, str) and code.strip():
                snippets.append(code.strip())

    if not snippets:
        return None

    name = _slugify_goal(goal, fallback=f"learned-{run_id[:8]}")
    body = _build_markdown(
        name=name, goal=goal, verify_cmd=verify_cmd,
        code_snippets=snippets, source_run_id=run_id,
    )
    skill_md_path = skills_root / name / "SKILL.md"
    return SkillCandidate(
        name=name, body_markdown=body,
        verify_cmd=verify_cmd, skill_md_path=skill_md_path,
    )
