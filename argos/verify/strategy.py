"""verify/strategy.py —— 验证梯子策略生成器（设计 §2.3，v6 最大赌注）。

无 verify_cmd 的任务 → 按确定性规则生成机检策略候选序列（梯子降序）；
生不出有效策略 → 最后必是诚实 L5 退路，绝不假绿。

梯子等级（本期实现 L1/L2/L3/L5，L4=VLM 留 P6）：
  L1 exit_code       命令退出码（pytest/cargo test/make test…）   最强
  L2 artifact_exists 产物文件存在断言                              强
  L2 artifact_schema 产物文件 JSON/YAML 结构断言                   强
  L2 content_assert  产物文件内容关键字/正则断言                    强
  L3 dom_assert      网页 DOM 内容断言                              中
  L5 evidence_trail  无机检证据，诚实 unverifiable + 人话           兜底

红线（写成代码 + 测试）：
  · 传输层成功 ≠ 任务正确：发送/购买/通知类任务（send/buy/notify…）
    → 直接 L5，绝不产 L3 / cmd 型策略。
  · 策略集中若出现 cmd 含 curl/http/wget 给发送类任务 → 这是 bug。
  · 空 goal / 胡乱输入 → 仍返回含 L5 的候选（fallback 永远存在）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

# ── 类型定义 ────────────────────────────────────────────────────

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
    """单条验证策略（不可变值对象）。

    Attributes:
        level:          梯子等级（L1 最强 → L5 诚实退路）
        kind:           策略种类（见 Kind）
        cmd:            可执行命令（None = 无机检，L5 专用）
        target:         产物路径 / CSS 选择器 / 正则模式（可 None）
        rationale_human: 人话：为什么这能证明任务做成了
        confidence:     置信度 [0.0, 1.0]
    """

    level: Level
    kind: Kind
    cmd: str | None
    target: str | None
    rationale_human: str
    confidence: float

    def __post_init__(self) -> None:
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"confidence 必须在 [0,1] 区间，实际值：{self.confidence!r}")
        if self.level == "L5" and self.kind != "evidence_trail":
            raise ValueError("L5 级策略 kind 必须是 evidence_trail")


# ── WorkspaceFacts ───────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class WorkspaceFacts:
    """工作区探测结果注入（只读快照，不调模型）。

    Attributes:
        has_pytest:      pytest 可运行（有 pytest.ini / pyproject.toml[tool.pytest.ini_options] / conftest.py）
        has_cargo:       Cargo.toml 存在
        has_package_json: package.json 存在（含 npm/pnpm/yarn 项目）
        has_makefile:    Makefile 存在（make test 可能可用）
        has_go_mod:      go.mod 存在
        declared_files:  Goal 中显式提及的产物文件名列表（由 generate 侧传入或 probe 侧探测）
        json_output:     工作区根存在 .json 格式产物文件（content_assert 启发）
        csv_output:      工作区根存在 .csv 格式产物文件
    """

    has_pytest: bool = False
    has_cargo: bool = False
    has_package_json: bool = False
    has_makefile: bool = False
    has_go_mod: bool = False
    declared_files: tuple[str, ...] = ()
    json_output: bool = False
    csv_output: bool = False


def _has_test_files(path: Path) -> bool:
    """是否存在可被 pytest 收集的测试文件（test_*.py / *_test.py）。
    顶层 glob + 常见测试目录（tests/ test/）。用 os.walk(followlinks=False) 而非 rglob：
    不跟软链（避免 tests/ 下的循环软链在 3.12 把探针挂死，2026-06-20 review #8），且 walk 目录数
    封顶 —— 只读、省时、命中即停。"""
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
        for _root, _dirs, files in _os.walk(tdir):  # followlinks=False(默认）→ 无软链环
            if any(_is_test(fn) for fn in files):
                return True
            walked += 1
            if walked >= 500:   # 防御:超大非测试树扫够即停(测试通常第一层就命中)
                break
    return False


def probe_workspace(path: Path) -> WorkspaceFacts:
    """只读扫描工作区，返回 WorkspaceFacts。不创建文件，不修改任何状态。

    Args:
        path: 要探测的工作区目录（不存在则返回全 False 默认值）
    """
    if not path.is_dir():
        return WorkspaceFacts()

    def _exists(*names: str) -> bool:
        return any((path / n).exists() for n in names)

    # pytest 信号（Phase 5.2，2026-06-20）：deliberate 测试设施（pytest.ini / conftest.py）直接算；
    # 弱信号（pyproject.toml / setup.cfg）单独不算 —— 几乎每个现代 Python 项目都有 pyproject.toml，
    # 但没测试时推 pytest 会收集 0 个测试、以退出码 5 误判失败。只在【真有可收集的测试文件】时才算。
    has_pytest = _exists("pytest.ini", "conftest.py") or _has_test_files(path)
    has_cargo = _exists("Cargo.toml")
    has_package_json = _exists("package.json")
    has_makefile = _exists("Makefile", "makefile", "GNUmakefile")
    has_go_mod = _exists("go.mod")

    # 简单扫顶层（不递归，只读、省时）
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


# ── 任务类型信号正则 ─────────────────────────────────────────────

# 发送/通知/购买类（传输层成功 ≠ 任务正确 → 直接 L5）
_SEND_PATTERN = re.compile(
    r"\b(send|email|mail|sms|message|notify|notification|tweet|post|publish|submit"
    r"|buy|purchase|order|checkout|pay|charge|invoice|book|reserve|subscribe"
    r"|upload|deploy)\b"
    r"|发(送|邮|短信|消息|通知|布|帖|推|文)|通知|发布|购买|下单|付款|结账|订单|预订|支付",
    re.I,
)

# 代码任务信号
_CODE_PATTERN = re.compile(
    r"\b(implement|write|create|add|fix|refactor|test|build|compile|run|develop"
    r"|function|class|module|script|code|program|api|endpoint)\b"
    r"|实现|编写|创建|添加|修复|重构|测试|构建|编译|开发|函数|类|模块|脚本|代码|接口",
    re.I,
)

# 网页/DOM 操作信号
_WEB_PATTERN = re.compile(
    r"\b(webpage|website|html|dom|css|browser|page|element|click|navigate|scrape"
    r"|render|frontend|ui)\b"
    r"|网页|页面|浏览器|前端|元素|点击|爬取",
    re.I,
)

# 产物文件信号（从 goal 中提取文件名）
_FILE_PATTERN = re.compile(
    r"\b[\w\-]+\.(?:json|yaml|yml|csv|txt|xml|html|md|log|out|db|sqlite)\b",
    re.I,
)

# ── 中文/英文动词锚定目录提取 ────────────────────────────────────
# 匹配格式：<动词> <目标路径> <子?文件夹|目录>
# 捕获组 1：目标目录名（可含中文、字母、数字、横线、下划线、点、斜杠，但不能以 ./ 或 ../ 开头）
_ZH_DIR_VERB_PATTERN = re.compile(
    r"(?:"
    # 中文动词锚定：整理到/保存到/放到/移动到/移到/归档到 X 子?文件夹|目录
    r"(?:整理到|保存到|放到|移动到|移到|归档到)\s*([\w一-鿿][\w一-鿿\-_./]*?)\s*子?(?:文件夹|目录)"
    # 英文动词锚定：organize/move/save … into/to X folder/directory
    # 使用 .*? 跳过动词后的多余词语（如 "meeting notes into"）
    r"|(?:organize|move|save)\b.*?\b(?:into|to)\s+([\w][\w\-_./]+)\s+(?:folder|directory|dir)\b"
    r")",
    re.I,
)

# 中文/英文动词锚定创建目录提取
# 格式：创建/新建/生成 X 文件夹|目录
_ZH_CREATE_DIR_PATTERN = re.compile(
    r"(?:"
    r"(?:创建|新建|生成)\s*([\w一-鿿][\w一-鿿\-_./]*?)\s*子?(?:文件夹|目录)"
    r"|(?:create|mkdir)\s+([\w][\w\-_./]*?)\s+(?:folder|directory|dir)"
    r")",
    re.I,
)

# 中文/英文动词锚定创建文件提取
# 格式：创建/新建/生成/写 X.ext（必须有扩展名才算文件）
_ZH_CREATE_FILE_PATTERN = re.compile(
    r"(?:"
    r"(?:创建|新建|生成|写)\s*([\w一-鿿][\w一-鿿\-_.]*?\.[\w]{1,8})"
    r"|(?:create|generate|write)\s+([\w][\w\-_.]*?\.[\w]{1,8})\b"
    r")",
    re.I,
)

# 否定语境词，出现在 X 周围时该 X 不提取
_NEGATION_BEFORE = re.compile(
    r"(?:不要|别|保持不变|不动|不要动|不能动|禁止动|don[''']t\s+(?:touch|move|modify|change)|keep\s+(?:unchanged|as.is))\s*$",
    re.I,
)

# 模板占位符检测（含此类字符串的目标不字面断言）
# 规则：
#   · 大写 YYYY/MM/DD/HH/SS — 全大写占位符（不被小写字母包围），含 report_YYYY.csv 场景
#   · \d{4}-\d{2}-\d{2} — 日期格式字符串（含具体日期，视为格式模板）
#   · 通配符 * — 路径不应含 *
#   · <...> / {...} / [...] — 尖括号/花括号/方括号包裹的占位符
#   · \bYY\b / \bXX\b / \bNN\b — 短占位符（须有词边界，避免误伤 `xx.json` → x 不算 XX）
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
    """判断提取到的字符串是否为合法产物路径片段。

    红线：
      a) 以空格开头/结尾 → 不合法
      b) 以 ../ 或 ./ 开头 → 不合法（路径遍历风险）
      c) 含有模板占位符 → 不合法（YYYY/MM/DD/*/XX 等是格式模板，不是字面路径）
      d) 空字符串 → 不合法
    """
    # a) 先检查原始字符串是否有前后空格（strip 前比较）
    if s != s.strip():
        return False
    s = s.strip()
    if not s:
        return False
    # b) 路径遍历
    if s.startswith("../") or s.startswith("./"):
        return False
    # c) 模板占位符
    if _TEMPLATE_PLACEHOLDER.search(s):
        return False
    return True


def _is_negation_context(goal: str, match_start: int) -> bool:
    """检查匹配位置之前是否存在否定语境词（不要/别/don't touch 等）。

    在匹配起始位置前取最多 20 个字符，检查是否含否定词。
    """
    prefix = goal[max(0, match_start - 20):match_start]
    return bool(_NEGATION_BEFORE.search(prefix))


def _extract_zh_dir_targets(goal: str) -> list[str]:
    """从 goal 中用动词锚定提取目录类产物目标（含否定过滤 + 路径合法性检查）。

    Returns:
        合法目录路径字符串列表（去重，保留首次出现顺序）
    """
    results: list[str] = []
    seen: set[str] = set()

    for pattern in (_ZH_DIR_VERB_PATTERN, _ZH_CREATE_DIR_PATTERN):
        for m in pattern.finditer(goal):
            # 两个捕获组分别对应中文/英文
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
    """从 goal 中用动词锚定提取文件类产物目标（含否定过滤 + 路径合法性检查）。

    Returns:
        合法文件路径字符串列表（去重，保留首次出现顺序）
    """
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

# 结构化输出信号（json/csv 输出）
_STRUCTURED_OUTPUT_PATTERN = re.compile(
    r"\b(json|csv|yaml|yml|xml)\b.*\b(output|file|result|report|export|save|write|generate)\b"
    r"|\b(output|result|report|export)\b.*\b(json|csv|yaml|yml)\b"
    r"|生成.*\b(json|csv|yaml|yml)\b|\b(json|csv|yaml|yml)\b.*文件",
    re.I,
)

# 从 goal 文本中提取显式 URL（http/https），用于 L3 dom_assert url 来源
_URL_PATTERN = re.compile(r'https?://[^\s\'"<>]+', re.I)


# ── L5 诚实退路（永远是最后一个）────────────────────────────────

def _l5_fallback(reason: str = "") -> VerifyStrategy:
    """生成 L5 evidence_trail 诚实退路策略。"""
    human = (
        "这件事我没法自动验证对错，需要你看一眼确认。"
        f"{(' ' + reason) if reason else ''}"
        "结果已记录在 Ledger 中，可随时复盘。"
    )
    return VerifyStrategy(
        level="L5",
        kind="evidence_trail",
        cmd=None,
        target=None,
        rationale_human=human.strip(),
        confidence=0.0,
    )


# ── 候选策略构建器 ────────────────────────────────────────────────

def _l1_pytest(hints: dict[str, str]) -> VerifyStrategy:
    cmd = hints.get("pytest_cmd", "pytest")
    rationale = f"运行 pytest（{cmd}）；退出码 0 = 所有测试通过 = 任务做对了。"
    if "pytest_cmd" in hints:
        rationale += f" 来自 capability hint: {hints['pytest_cmd']!r}。"
    return VerifyStrategy(
        level="L1", kind="exit_code",
        cmd=cmd, target=None,
        rationale_human=rationale, confidence=0.95,
    )


def _l1_cargo_test() -> VerifyStrategy:
    return VerifyStrategy(
        level="L1", kind="exit_code",
        cmd="cargo test", target=None,
        rationale_human="运行 cargo test；退出码 0 = Rust 测试全过 = 实现正确。",
        confidence=0.95,
    )


def _l1_npm_test() -> VerifyStrategy:
    return VerifyStrategy(
        level="L1", kind="exit_code",
        cmd="npm test", target=None,
        rationale_human="运行 npm test；退出码 0 = JS/TS 测试全过。",
        confidence=0.90,
    )


def _l1_make_test() -> VerifyStrategy:
    return VerifyStrategy(
        level="L1", kind="exit_code",
        cmd="make test", target=None,
        rationale_human="运行 make test；Makefile 定义的测试目标通过 = 任务完成。",
        confidence=0.85,
    )


def _l1_go_test() -> VerifyStrategy:
    return VerifyStrategy(
        level="L1", kind="exit_code",
        cmd="go test ./...", target=None,
        rationale_human="运行 go test ./...；退出码 0 = Go 测试全过。",
        confidence=0.90,
    )


def _l2_artifact_exists(file_path: str, hints: dict[str, str]) -> VerifyStrategy:
    rationale = f"检查文件 {file_path!r} 存在 = agent 确实生成了声明的产物。"
    if hints:
        rationale += f" 来自 capability hints: {list(hints)!r}。"
    return VerifyStrategy(
        level="L2", kind="artifact_exists",
        cmd=f"test -f {file_path}", target=file_path,
        rationale_human=rationale, confidence=0.75,
    )


def _l2_artifact_exists_dir(dir_path: str) -> VerifyStrategy:
    """构造目录存在断言（L2 artifact_exists，用 test -d）。

    Args:
        dir_path: 目录路径（从 goal 动词锚定提取）
    """
    rationale = f"检查目录 {dir_path!r} 存在 = agent 确实创建/整理了声明的输出目录。"
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
        rationale_human=(
            f"验证 {file_path!r} 是合法 JSON —— 结构化输出正确序列化。"
        ),
        confidence=0.70,
    )


def _l2_content_assert_csv(file_path: str) -> VerifyStrategy:
    return VerifyStrategy(
        level="L2", kind="content_assert",
        cmd=f"python -c \"import csv, sys; list(csv.reader(open('{file_path}')))\"",
        target=file_path,
        rationale_human=(
            f"验证 {file_path!r} 是合法 CSV —— 结构化输出可解析。"
        ),
        confidence=0.70,
    )


def _l3_dom_assert(hints: dict[str, str], goal_url: str | None = None) -> VerifyStrategy:
    """构造 L3 dom_assert 策略。

    url 来源优先级：hints['dom_url'] > goal 中提取的显式 URL > 无（不生成 L3）。
    selector 来源：hints['dom_selector']（必须存在，否则调用方不应调此函数）。
    expected_text 来源：hints['dom_expected_text']（可选；提供时走强证据路径，可产 passed/failed；
        不提供时 DomProber 走弱证据路径，最高只能 unverifiable——见 dom_probe.py 三态注释）。
    """
    selector = hints.get("dom_selector", "body")
    url = hints.get("dom_url") or goal_url or ""
    if not url:
        # 无法确定目标 URL → 不生成（调用方已做 guard，此处保险再判一次）
        # 此分支不应被触达；若触达则返回一个标记策略（level L5 退路由 generate 追加）
        raise ValueError("_l3_dom_assert: 无 url，不应调用")
    expected_text = hints.get("dom_expected_text") or ""
    if expected_text:
        rationale = (
            f"在 {url!r} 确认页面文本包含 {expected_text!r} —— "
            "声明式内容断言，可机检判定（强证据路径）。"
        )
    else:
        rationale = (
            f"在 {url!r} 检查 DOM 选择器 {selector!r} 相关内容 —— "
            "仅有文本弱提示，无结构性 DOM 校验通道；"
            "结果最高为 unverifiable（非 passed）。"
            "如需机检断言，请在 propose_dom_verify() 中提供 expected_text。"
        )
    return VerifyStrategy(
        level="L3", kind="dom_assert",
        cmd=None,  # DOM 断言需外部浏览器探针（DomProber）；cmd 留 None，接线层走探针路径
        target=f"{url}#{selector}",
        rationale_human=rationale,
        confidence=0.60 if expected_text else 0.30,
    )


# ── 主入口 generate ──────────────────────────────────────────────

def generate(
    goal: str,
    *,
    workspace_facts: WorkspaceFacts,
    capability_hints: dict[str, str] | None = None,
) -> tuple[VerifyStrategy, ...]:
    """按验证梯子降序生成候选策略序列，永远非空（最后必是 L5 退路）。

    规则核心（确定性，不调模型）：
      1. 发送/购买/通知类 → 直接 L5（红线：传输层成功 ≠ 任务正确）
      2. 代码任务 + 测试框架存在 → L1（跑该框架）
      3. goal 显式声明产物文件 → L2 artifact_exists / schema
      4. 结构化输出（JSON/CSV）信号 → L2 content_assert 模板
      5. 网页改动信号 → L3 dom_assert 模板（如有 hints）
      6. 最后永远追加 L5 evidence_trail 诚实退路

    Args:
        goal:             任务自然语言描述
        workspace_facts:  工作区探测快照
        capability_hints: 能力注册时附带的 verify_hint 字典（可选）
                          支持键：pytest_cmd / dom_selector / dom_url / verify_file
    """
    hints: dict[str, str] = capability_hints or {}
    candidates: list[VerifyStrategy] = []

    # ── 红线：纯发送/购买/通知类 → 直接 L5 ───────────────────────
    # 只在【无代码任务信号】时早退:"fix the bug and push"/"implement an order book"
    # 是代码任务,交付物可被 L1/L2 机检,不应整体退化 L5(终审 major 修正)。
    # 混合任务(代码+发送)仍生成代码侧策略;发送侧的不可验证性由末位 L5 退路如实承接。
    # 全局不变量不变:任何任务都绝不生成"传输层响应码=verified"型策略。
    if _SEND_PATTERN.search(goal) and not _CODE_PATTERN.search(goal):
        return (
            _l5_fallback(
                "发送/通知/购买类任务：传输层返回成功不等于任务内容正确"
                "（收错人/发错内容仍可能 200）。"
            ),
        )

    # ── capability hint 优先注入 ──────────────────────────────────
    if "verify_file" in hints:
        vf = hints["verify_file"]
        candidates.append(_l2_artifact_exists(vf, hints))

    # ── L1：代码任务 + 测试框架 ───────────────────────────────────
    is_code_task = bool(_CODE_PATTERN.search(goal))

    has_any_framework = (
        workspace_facts.has_pytest
        or workspace_facts.has_cargo
        or workspace_facts.has_go_mod
        or workspace_facts.has_package_json
        or workspace_facts.has_makefile
    )
    if is_code_task or has_any_framework:
        # pytest：需要工作区有 pytest 信号，或 goal 是代码任务 + capability hint 提供了 pytest_cmd
        if workspace_facts.has_pytest or (is_code_task and "pytest_cmd" in hints):
            candidates.append(_l1_pytest(hints))
        # 其他框架只在工作区实际存在时生成（不按 goal 推断）
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

    # ── L2：声明产物文件 ──────────────────────────────────────────
    declared = list(workspace_facts.declared_files)

    # 也从 goal 文本中提取文件名（启发式）
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

    # ── L2：中文/英文动词锚定目录产物提取 ───────────────────────
    # 防过度提取：否定语境 + 模板占位符 + 路径合法性 已在提取函数内把关
    dir_targets = _extract_zh_dir_targets(goal)
    for dname in dir_targets:
        candidates.append(_l2_artifact_exists_dir(dname))

    # ── L2：中文/英文动词锚定文件产物提取（create/write 语境）──
    file_targets = _extract_zh_file_targets(goal)
    for fpath in file_targets:
        if fpath not in declared:  # 避免与上方 declared 重复
            candidates.append(_l2_artifact_exists(fpath, {}))
            if fpath.endswith(".json"):
                candidates.append(_l2_content_assert_json(fpath))
            elif fpath.endswith(".csv"):
                candidates.append(_l2_content_assert_csv(fpath))

    # ── L2：结构化输出信号（JSON/CSV 工作区存量）──────────────────
    if not declared:  # 没有显式声明文件才走工作区扫描兜底
        if workspace_facts.json_output and _STRUCTURED_OUTPUT_PATTERN.search(goal):
            candidates.append(
                VerifyStrategy(
                    level="L2", kind="content_assert",
                    cmd=None,  # 具体文件名未知；接线层需填充
                    target="*.json",
                    rationale_human="目标含 JSON 输出信号，验证输出文件是合法 JSON。",
                    confidence=0.55,
                )
            )
        elif workspace_facts.csv_output and _STRUCTURED_OUTPUT_PATTERN.search(goal):
            candidates.append(
                VerifyStrategy(
                    level="L2", kind="content_assert",
                    cmd=None,
                    target="*.csv",
                    rationale_human="目标含 CSV 输出信号，验证输出文件可解析。",
                    confidence=0.55,
                )
            )

    # ── L3：网页/DOM 信号 ─────────────────────────────────────────
    # 生成条件（同时满足）：
    #   1. goal 含网页/DOM 信号
    #   2. hints 提供了 dom_selector（确定要检查哪个元素）
    #   3. URL 可解析：hints['dom_url'] 或 goal 中含显式 http(s) URL
    #      → 捕不到 URL 就诚实不生成（绝不假造 localhost 默认值）
    # 不放宽发送类红线：纯发送任务已在入口早退，此处不会到达。
    if _WEB_PATTERN.search(goal) and "dom_selector" in hints:
        # URL 来源：hints 优先；其次从 goal 文本提取显式 URL
        _dom_url = hints.get("dom_url") or ""
        if not _dom_url:
            _url_matches = _URL_PATTERN.findall(goal)
            _dom_url = _url_matches[0] if _url_matches else ""
        if _dom_url:
            try:
                candidates.append(_l3_dom_assert(hints, goal_url=_dom_url))
            except ValueError:
                pass  # 极端情况保险：url 仍空则跳过，L5 兜底

    # ── L5 诚实退路（永远最后）────────────────────────────────────
    candidates.append(_l5_fallback())

    # 去重：相同 (level, kind, cmd, target) 的保留第一条
    seen: set[tuple] = set()
    deduped: list[VerifyStrategy] = []
    for s in candidates:
        key = (s.level, s.kind, s.cmd, s.target)
        if key not in seen:
            seen.add(key)
            deduped.append(s)

    return tuple(deduped)
