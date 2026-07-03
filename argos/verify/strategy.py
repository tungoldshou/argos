"""Internal documentation."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from argos.i18n import t


Level = Literal["L1", "L2", "L3", "L5"]
Kind = Literal[
    "exit_code",
    "artifact_exists",
    "artifact_schema",
    "content_assert",
    "dom_assert",
    "evidence_trail",
]


@dataclass(frozen=True, slots=True)
class VerifyStrategy:
    """Internal documentation."""

    level: Level
    kind: Kind
    cmd: str | None
    target: str | None
    rationale_human: str
    confidence: float

    def __post_init__(self) -> None:
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(t("verify.strategy.confidence_range", value=self.confidence))
        if self.level == "L5" and self.kind != "evidence_trail":
            raise ValueError(t("verify.strategy.l5_kind_required"))


# ── WorkspaceFacts ───────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class WorkspaceFacts:
    """Internal documentation."""

    has_pytest: bool = False
    has_cargo: bool = False
    has_package_json: bool = False
    has_makefile: bool = False
    has_go_mod: bool = False
    declared_files: tuple[str, ...] = ()
    json_output: bool = False
    csv_output: bool = False


def _has_test_files(path: Path) -> bool:
    """Internal documentation."""
    import os as _os

    def _is_test(name: str) -> bool:
        return (name.startswith("test_") and name.endswith(".py")) or name.endswith("_test.py")

    for pat in ("test_*.py", "*_test.py"):
        if next(path.glob(pat), None) is not None:
            return True
    for d in ("tests", "test"):
        tdir = path / d
        if not tdir.is_dir():
            continue
        walked = 0
        for _root, _dirs, files in _os.walk(tdir):
            if any(_is_test(fn) for fn in files):
                return True
            walked += 1
            if walked >= 500:
                break
    return False


def probe_workspace(path: Path) -> WorkspaceFacts:
    """Internal documentation."""
    if not path.is_dir():
        return WorkspaceFacts()

    def _exists(*names: str) -> bool:
        return any((path / n).exists() for n in names)

    has_pytest = _exists("pytest.ini", "conftest.py") or _has_test_files(path)
    has_cargo = _exists("Cargo.toml")
    has_package_json = _exists("package.json")
    has_makefile = _exists("Makefile", "makefile", "GNUmakefile")
    has_go_mod = _exists("go.mod")

    json_output = any(p.suffix == ".json" for p in path.iterdir() if p.is_file())
    csv_output = any(p.suffix == ".csv" for p in path.iterdir() if p.is_file())

    return WorkspaceFacts(
        has_pytest=has_pytest,
        has_cargo=has_cargo,
        has_package_json=has_package_json,
        has_makefile=has_makefile,
        has_go_mod=has_go_mod,
        json_output=json_output,
        csv_output=csv_output,
    )



_SEND_PATTERN = re.compile(
    r"\b(send|email|mail|sms|message|notify|notification|tweet|post|publish|submit"
    r"|buy|purchase|order|checkout|pay|charge|invoice|book|reserve|subscribe"
    r"|upload|deploy)\b"
    r"|发(送|邮|短信|消息|通知|布|帖|推|文)|通知|发布|购买|下单|付款|结账|订单|预订|支付",
    re.I,
)

_CODE_PATTERN = re.compile(
    r"\b(implement|write|create|add|fix|refactor|test|build|compile|run|develop"
    r"|function|class|module|script|code|program|api|endpoint)\b"
    r"|实现|编写|创建|添加|修复|重构|测试|构建|编译|开发|函数|类|模块|脚本|代码|接口",
    re.I,
)

_WEB_PATTERN = re.compile(
    r"\b(webpage|website|html|dom|css|browser|page|element|click|navigate|scrape"
    r"|render|frontend|ui)\b"
    r"|网页|页面|浏览器|前端|元素|点击|爬取",
    re.I,
)

_FILE_PATTERN = re.compile(
    r"\b[\w\-]+\.(?:json|yaml|yml|csv|txt|xml|html|md|log|out|db|sqlite)\b",
    re.I,
)

_ZH_DIR_VERB_PATTERN = re.compile(
    r"(?:"
    r"(?:整理到|保存到|放到|移动到|移到|归档到)\s*([\w一-鿿][\w一-鿿\-_./]*?)\s*子?(?:文件夹|目录)"
    r"|(?:organize|move|save)\b.*?\b(?:into|to)\s+([\w][\w\-_./]+)\s+(?:folder|directory|dir)\b"
    r")",
    re.I,
)

_ZH_CREATE_DIR_PATTERN = re.compile(
    r"(?:"
    r"(?:创建|新建|生成)\s*([\w一-鿿][\w一-鿿\-_./]*?)\s*子?(?:文件夹|目录)"
    r"|(?:create|mkdir)\s+([\w][\w\-_./]*?)\s+(?:folder|directory|dir)"
    r")",
    re.I,
)

_ZH_CREATE_FILE_PATTERN = re.compile(
    r"(?:"
    r"(?:创建|新建|生成|写)\s*([\w一-鿿][\w一-鿿\-_.]*?\.[\w]{1,8})"
    r"|(?:create|generate|write)\s+([\w][\w\-_.]*?\.[\w]{1,8})\b"
    r")",
    re.I,
)

_NEGATION_BEFORE = re.compile(
    r"(?:不要|别|保持不变|不动|不要动|不能动|禁止动|don[''']t\s+(?:touch|move|modify|change)|keep\s+(?:unchanged|as.is))\s*$",
    re.I,
)

_TEMPLATE_PLACEHOLDER = re.compile(
    r"(?:"
    r"(?<![a-z])YYYY(?![a-z])"
    r"|(?<![a-z])MM(?![a-z])"
    r"|(?<![a-z])DD(?![a-z])"
    r"|(?<![a-z])HH(?![a-z])"
    r"|(?<![a-z])SS(?![a-z])"
    r"|\bYY\b|\bXX\b|\bNN\b"
    r"|\*"
    r"|<[^>]+>"
    r"|\{[^}]+\}"
    r"|\[[^\]]+\]"
    r"|\d{4}-\d{2}-\d{2}"
    r")"
)


def _is_valid_artifact_path(s: str) -> bool:
    """Internal documentation."""
    if s != s.strip():
        return False
    s = s.strip()
    if not s:
        return False
    if s.startswith("../") or s.startswith("./"):
        return False
    if _TEMPLATE_PLACEHOLDER.search(s):
        return False
    return True


def _is_negation_context(goal: str, match_start: int) -> bool:
    """Internal documentation."""
    prefix = goal[max(0, match_start - 20):match_start]
    return bool(_NEGATION_BEFORE.search(prefix))


def _extract_zh_dir_targets(goal: str) -> list[str]:
    """Internal documentation."""
    results: list[str] = []
    seen: set[str] = set()

    for pattern in (_ZH_DIR_VERB_PATTERN, _ZH_CREATE_DIR_PATTERN):
        for m in pattern.finditer(goal):
            target = m.group(1) or m.group(2) or ""
            target = target.strip()
            if not target:
                continue
            if _is_negation_context(goal, m.start()):
                continue
            if not _is_valid_artifact_path(target):
                continue
            if target not in seen:
                seen.add(target)
                results.append(target)

    return results


def _extract_zh_file_targets(goal: str) -> list[str]:
    """Internal documentation."""
    results: list[str] = []
    seen: set[str] = set()

    for m in _ZH_CREATE_FILE_PATTERN.finditer(goal):
        target = m.group(1) or m.group(2) or ""
        target = target.strip()
        if not target:
            continue
        if _is_negation_context(goal, m.start()):
            continue
        if not _is_valid_artifact_path(target):
            continue
        if target not in seen:
            seen.add(target)
            results.append(target)

    return results

_STRUCTURED_OUTPUT_PATTERN = re.compile(
    r"\b(json|csv|yaml|yml|xml)\b.*\b(output|file|result|report|export|save|write|generate)\b"
    r"|\b(output|result|report|export)\b.*\b(json|csv|yaml|yml)\b"
    r"|生成.*\b(json|csv|yaml|yml)\b|\b(json|csv|yaml|yml)\b.*文件",
    re.I,
)

_URL_PATTERN = re.compile(r'https?://[^\s\'"<>]+', re.I)



def _l5_fallback(reason: str = "") -> VerifyStrategy:
    """Internal documentation."""
    reason_part = (" " + reason) if reason else ""
    human = t("verify.strategy.l5_human", reason=reason_part)
    return VerifyStrategy(
        level="L5",
        kind="evidence_trail",
        cmd=None,
        target=None,
        rationale_human=human.strip(),
        confidence=0.0,
    )



def _l1_pytest(hints: dict[str, str]) -> VerifyStrategy:
    cmd = hints.get("pytest_cmd", "pytest")
    rationale = t("verify.strategy.l1_pytest_rationale", cmd=cmd)
    if "pytest_cmd" in hints:
        rationale += t("verify.strategy.l1_pytest_hint", hint=hints["pytest_cmd"])
    return VerifyStrategy(
        level="L1", kind="exit_code",
        cmd=cmd, target=None,
        rationale_human=rationale, confidence=0.95,
    )


def _l1_cargo_test() -> VerifyStrategy:
    return VerifyStrategy(
        level="L1", kind="exit_code",
        cmd="cargo test", target=None,
        rationale_human=t("verify.strategy.l1_cargo_rationale"),
        confidence=0.95,
    )


def _l1_npm_test() -> VerifyStrategy:
    return VerifyStrategy(
        level="L1", kind="exit_code",
        cmd="npm test", target=None,
        rationale_human=t("verify.strategy.l1_npm_rationale"),
        confidence=0.90,
    )


def _l1_make_test() -> VerifyStrategy:
    return VerifyStrategy(
        level="L1", kind="exit_code",
        cmd="make test", target=None,
        rationale_human=t("verify.strategy.l1_make_rationale"),
        confidence=0.85,
    )


def _l1_go_test() -> VerifyStrategy:
    return VerifyStrategy(
        level="L1", kind="exit_code",
        cmd="go test ./...", target=None,
        rationale_human=t("verify.strategy.l1_go_rationale"),
        confidence=0.90,
    )


def _l2_artifact_exists(file_path: str, hints: dict[str, str]) -> VerifyStrategy:
    rationale = t("verify.strategy.l2_artifact_exists_rationale", file_path=file_path)
    if hints:
        rationale += t("verify.strategy.l2_artifact_exists_hint", hints=list(hints))
    return VerifyStrategy(
        level="L2", kind="artifact_exists",
        cmd=f"test -f {file_path}", target=file_path,
        rationale_human=rationale, confidence=0.75,
    )


def _l2_artifact_exists_dir(dir_path: str) -> VerifyStrategy:
    """Internal documentation."""
    rationale = t("verify.strategy.l2_artifact_exists_dir_rationale", dir_path=dir_path)
    return VerifyStrategy(
        level="L2", kind="artifact_exists",
        cmd=f"test -d {dir_path}", target=dir_path,
        rationale_human=rationale, confidence=0.75,
    )


def _l2_content_assert_json(file_path: str) -> VerifyStrategy:
    return VerifyStrategy(
        level="L2", kind="artifact_schema",
        cmd=f"python -c \"import json, sys; json.load(open('{file_path}'))\"",
        target=file_path,
        rationale_human=t("verify.strategy.l2_json_rationale", file_path=file_path),
        confidence=0.70,
    )


def _l2_content_assert_csv(file_path: str) -> VerifyStrategy:
    return VerifyStrategy(
        level="L2", kind="content_assert",
        cmd=f"python -c \"import csv, sys; list(csv.reader(open('{file_path}')))\"",
        target=file_path,
        rationale_human=t("verify.strategy.l2_csv_rationale", file_path=file_path),
        confidence=0.70,
    )


def _l3_dom_assert(hints: dict[str, str], goal_url: str | None = None) -> VerifyStrategy:
    """Internal documentation."""
    selector = hints.get("dom_selector", "body")
    url = hints.get("dom_url") or goal_url or ""
    if not url:
        raise ValueError(t("verify.strategy.l3_dom_no_url"))
    expected_text = hints.get("dom_expected_text") or ""
    if expected_text:
        rationale = t(
            "verify.strategy.l3_dom_strong_rationale",
            url=url,
            expected_text=expected_text,
        )
    else:
        rationale = t(
            "verify.strategy.l3_dom_weak_rationale",
            url=url,
            selector=selector,
        )
    return VerifyStrategy(
        level="L3", kind="dom_assert",
        cmd=None,
        target=f"{url}#{selector}",
        rationale_human=rationale,
        confidence=0.60 if expected_text else 0.30,
    )



def generate(
    goal: str,
    *,
    workspace_facts: WorkspaceFacts,
    capability_hints: dict[str, str] | None = None,
) -> tuple[VerifyStrategy, ...]:
    """Internal documentation."""
    hints: dict[str, str] = capability_hints or {}
    candidates: list[VerifyStrategy] = []

    if _SEND_PATTERN.search(goal) and not _CODE_PATTERN.search(goal):
        return (
            _l5_fallback(t("verify.strategy.send_l5_reason")),
        )

    if "verify_file" in hints:
        vf = hints["verify_file"]
        candidates.append(_l2_artifact_exists(vf, hints))

    is_code_task = bool(_CODE_PATTERN.search(goal))

    has_any_framework = (
        workspace_facts.has_pytest
        or workspace_facts.has_cargo
        or workspace_facts.has_go_mod
        or workspace_facts.has_package_json
        or workspace_facts.has_makefile
    )
    if is_code_task or has_any_framework:
        if workspace_facts.has_pytest or (is_code_task and "pytest_cmd" in hints):
            candidates.append(_l1_pytest(hints))
        if workspace_facts.has_cargo:
            candidates.append(_l1_cargo_test())
        if workspace_facts.has_go_mod:
            candidates.append(_l1_go_test())
        if workspace_facts.has_package_json:
            candidates.append(_l1_npm_test())
        if workspace_facts.has_makefile and not (
            workspace_facts.has_pytest or workspace_facts.has_cargo
        ):
            candidates.append(_l1_make_test())

    declared = list(workspace_facts.declared_files)

    for m in _FILE_PATTERN.finditer(goal):
        fname = m.group(0)
        if fname not in declared:
            declared.append(fname)

    for fname in declared:
        candidates.append(_l2_artifact_exists(fname, hints))
        if fname.endswith(".json"):
            candidates.append(_l2_content_assert_json(fname))
        elif fname.endswith(".csv"):
            candidates.append(_l2_content_assert_csv(fname))

    dir_targets = _extract_zh_dir_targets(goal)
    for dname in dir_targets:
        candidates.append(_l2_artifact_exists_dir(dname))

    file_targets = _extract_zh_file_targets(goal)
    for fpath in file_targets:
        if fpath not in declared:
            candidates.append(_l2_artifact_exists(fpath, {}))
            if fpath.endswith(".json"):
                candidates.append(_l2_content_assert_json(fpath))
            elif fpath.endswith(".csv"):
                candidates.append(_l2_content_assert_csv(fpath))

    if not declared:
        if workspace_facts.json_output and _STRUCTURED_OUTPUT_PATTERN.search(goal):
            candidates.append(
                VerifyStrategy(
                    level="L2", kind="content_assert",
                    cmd=None,
                    target="*.json",
                    rationale_human=t("verify.strategy.json_output_rationale"),
                    confidence=0.55,
                )
            )
        elif workspace_facts.csv_output and _STRUCTURED_OUTPUT_PATTERN.search(goal):
            candidates.append(
                VerifyStrategy(
                    level="L2", kind="content_assert",
                    cmd=None,
                    target="*.csv",
                    rationale_human=t("verify.strategy.csv_output_rationale"),
                    confidence=0.55,
                )
            )

    if _WEB_PATTERN.search(goal) and "dom_selector" in hints:
        _dom_url = hints.get("dom_url") or ""
        if not _dom_url:
            _url_matches = _URL_PATTERN.findall(goal)
            _dom_url = _url_matches[0] if _url_matches else ""
        if _dom_url:
            try:
                candidates.append(_l3_dom_assert(hints, goal_url=_dom_url))
            except ValueError:
                pass

    candidates.append(_l5_fallback())

    seen: set[tuple] = set()
    deduped: list[VerifyStrategy] = []
    for s in candidates:
        key = (s.level, s.kind, s.cmd, s.target)
        if key not in seen:
            seen.add(key)
            deduped.append(s)

    return tuple(deduped)
