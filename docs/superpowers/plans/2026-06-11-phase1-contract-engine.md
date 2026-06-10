# Phase 1: 契约引擎 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 verify 从"只认 exit code"泛化为"任务契约"——4 种检查类型、三态执行、模型合成 + fail-closed 解析,并接进现有 loop(有契约走契约,无契约走旧路径)。

**Architecture:** 新建 `argos_agent/contracts/` 包(types/runner/synthesize 三个文件,纯 Python 无新框架)。exit_code 检查通过注入的 `run_cmd` 回调委托给现有 `Verifier._run_verify`(白名单 + verify_dir 隔离原样保留);产物类检查纯本地文件断言。聚合判决复用 `core.types.Verdict` 三态,fail-closed:无检查/检查本身出错 → unverifiable,绝不蒙混成 passed。

**Tech Stack:** Python 3.12, dataclasses(frozen), pytest。无新依赖(schema 检查用最小自实现,YAGNI)。

**Files:**
- Create: `argos_agent/contracts/__init__.py`, `types.py`, `runner.py`, `synthesize.py`
- Modify: `argos_agent/core/verify_gate.py`(加 `verify_contract` 方法)
- Test: `tests/contracts/__init__.py`, `test_types.py`, `test_runner.py`, `test_synthesize.py`, `test_verifier_contract.py`

---

### Task 1: Check / Contract 类型 + 校验

**Files:**
- Create: `argos_agent/contracts/__init__.py`, `argos_agent/contracts/types.py`
- Test: `tests/contracts/__init__.py`, `tests/contracts/test_types.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/contracts/test_types.py
"""Check/Contract 类型:字段约束 + fail-closed 校验(坏契约必须被拒,不带病放行)。"""
from argos_agent.contracts.types import Check, Contract


def test_exit_code_check_requires_cmd():
    assert Check(kind="exit_code", cmd="pytest -q").validate() is None
    assert Check(kind="exit_code").validate() is not None          # 缺 cmd → 错误串


def test_exit_code_rejects_trivial_cmd_anti_fake_green():
    """反假绿:echo/true/: 这类恒真命令不配当检查(对齐 verify 门禁既有铁律)。"""
    for cmd in ("echo ok", "true", ":", "exit 0"):
        assert Check(kind="exit_code", cmd=cmd).validate() is not None


def test_artifact_checks_require_path():
    assert Check(kind="artifact_exists", path="dist/report.md").validate() is None
    assert Check(kind="artifact_exists").validate() is not None
    assert Check(kind="artifact_schema", path="o.json",
                 schema={"required": ["title"]}).validate() is None
    assert Check(kind="artifact_schema", path="o.json").validate() is not None  # 缺 schema


def test_content_assert_requires_contains_or_regex():
    assert Check(kind="content_assert", path="r.md", contains="来源").validate() is None
    assert Check(kind="content_assert", path="r.md", regex=r"https?://").validate() is None
    assert Check(kind="content_assert", path="r.md").validate() is not None


def test_unknown_kind_rejected():
    assert Check(kind="vibes", cmd="x").validate() is not None  # type: ignore[arg-type]


def test_contract_validate_aggregates_and_requires_checks():
    good = Contract(goal="写调研报告", deliverables=("report.md",),
                    checks=(Check(kind="artifact_exists", path="report.md"),))
    assert good.validate() == []
    empty = Contract(goal="g", deliverables=(), checks=())
    assert any("至少" in e for e in empty.validate())             # 无检查的契约非法
    bad = Contract(goal="g", deliverables=("a",),
                   checks=(Check(kind="exit_code"),))
    assert len(bad.validate()) == 1                               # 子检查错误向上聚合
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/contracts/test_types.py --no-cov -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'argos_agent.contracts'`

- [ ] **Step 3: Write the implementation**

```python
# argos_agent/contracts/__init__.py
"""任务契约(Factory P1):完成的定义先于执行。"""
from argos_agent.contracts.types import Check, Contract  # noqa: F401
```

```python
# argos_agent/contracts/types.py
"""Check / Contract 类型(Factory P1 spec)。

契约 = 任务开始前签订的"完成的定义":人类可读产物清单 + 机器可跑检查集。
fail-closed:validate() 返回错误的契约绝不进入执行;无检查的契约非法
(诚实铁律:没有检查就没有 passed 的资格——那叫 unverifiable)。
"""
from __future__ import annotations

import re as _re
from dataclasses import dataclass, field
from typing import Literal

CheckKind = Literal["exit_code", "artifact_exists", "artifact_schema", "content_assert"]

_VALID_KINDS: frozenset[str] = frozenset(
    {"exit_code", "artifact_exists", "artifact_schema", "content_assert"})

# 反假绿(对齐 loop 的 trivial 命令拒绝):恒真命令不配当检查。
_TRIVIAL_CMD = _re.compile(r"^\s*(echo\b|true\b|:\s*$|exit\s+0\b)")


@dataclass(frozen=True, slots=True)
class Check:
    """单条机器可跑检查。kind 决定必填字段:
    exit_code → cmd;artifact_exists → path;
    artifact_schema → path + schema({"required": [keys]} 最小子集);
    content_assert → path + (contains 或 regex)。"""
    kind: CheckKind
    cmd: str | None = None
    path: str | None = None
    schema: dict | None = None
    contains: str | None = None
    regex: str | None = None
    description: str = ""

    def validate(self) -> str | None:
        """合法返 None,否则返人类可读错误(供合成回喂模型重写)。"""
        if self.kind not in _VALID_KINDS:
            return f"未知检查类型 {self.kind!r}(合法:{sorted(_VALID_KINDS)})"
        if self.kind == "exit_code":
            if not self.cmd or not self.cmd.strip():
                return "exit_code 检查缺 cmd"
            if _TRIVIAL_CMD.match(self.cmd):
                return f"恒真命令 {self.cmd!r} 不配当检查(反假绿)"
            return None
        if not self.path:
            return f"{self.kind} 检查缺 path"
        if self.kind == "artifact_schema":
            req = (self.schema or {}).get("required")
            if not isinstance(req, list) or not req:
                return "artifact_schema 检查缺 schema.required(非空 key 列表)"
        if self.kind == "content_assert" and not (self.contains or self.regex):
            return "content_assert 检查需 contains 或 regex 至少一个"
        if self.regex is not None:
            try:
                _re.compile(self.regex)
            except _re.error as e:
                return f"regex 不合法:{e}"
        return None


@dataclass(frozen=True, slots=True)
class Contract:
    """任务契约。goal 是人类语言;deliverables 是人类可读产物清单(给意图卡/交付页);
    checks 是机器裁决的唯一依据。"""
    goal: str
    deliverables: tuple[str, ...]
    checks: tuple[Check, ...]
    out_of_scope: tuple[str, ...] = field(default=())

    def validate(self) -> list[str]:
        """全部合法返 [];否则返错误列表(fail-closed:有错即拒)。"""
        errors: list[str] = []
        if not self.goal.strip():
            errors.append("契约缺 goal")
        if not self.checks:
            errors.append("契约至少需要 1 条检查(无检查=unverifiable,没有 passed 资格)")
        for i, c in enumerate(self.checks):
            err = c.validate()
            if err:
                errors.append(f"checks[{i}]: {err}")
        return errors
```

```python
# tests/contracts/__init__.py
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/contracts/test_types.py --no-cov -q`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
rtk git add argos_agent/contracts tests/contracts
rtk git commit -m "feat(contracts): P1 契约类型 Check/Contract + fail-closed 校验"
```

---

### Task 2: 契约执行器(产物类检查 + 三态聚合)

**Files:**
- Create: `argos_agent/contracts/runner.py`
- Test: `tests/contracts/test_runner.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/contracts/test_runner.py
"""run_contract 三态聚合:全过=passed / 任一败=failed / 无检查或检查自身出错=unverifiable。"""
import json

import pytest

from argos_agent.contracts.types import Check, Contract
from argos_agent.contracts.runner import run_contract


def _ok_run_cmd(cmd):           # Verifier._run_verify 同构签名:(ok, detail, timed_out)
    return True, "exit 0", False


def _contract(*checks):
    return Contract(goal="g", deliverables=("d",), checks=tuple(checks))


def test_artifact_exists_pass_and_fail(tmp_path):
    (tmp_path / "report.md").write_text("x", encoding="utf-8")
    v = run_contract(_contract(Check(kind="artifact_exists", path="report.md")),
                     workspace=tmp_path, run_cmd=_ok_run_cmd)
    assert v.status == "passed"
    v = run_contract(_contract(Check(kind="artifact_exists", path="missing.md")),
                     workspace=tmp_path, run_cmd=_ok_run_cmd)
    assert v.status == "failed" and "missing.md" in v.detail


def test_artifact_schema_required_keys(tmp_path):
    (tmp_path / "o.json").write_text(json.dumps({"title": "t", "items": []}), encoding="utf-8")
    ck = Check(kind="artifact_schema", path="o.json", schema={"required": ["title", "items"]})
    assert run_contract(_contract(ck), workspace=tmp_path, run_cmd=_ok_run_cmd).status == "passed"
    ck2 = Check(kind="artifact_schema", path="o.json", schema={"required": ["author"]})
    v = run_contract(_contract(ck2), workspace=tmp_path, run_cmd=_ok_run_cmd)
    assert v.status == "failed" and "author" in v.detail


def test_artifact_schema_bad_json_is_failed_not_crash(tmp_path):
    (tmp_path / "o.json").write_text("{not json", encoding="utf-8")
    ck = Check(kind="artifact_schema", path="o.json", schema={"required": ["a"]})
    assert run_contract(_contract(ck), workspace=tmp_path, run_cmd=_ok_run_cmd).status == "failed"


def test_content_assert_contains_and_regex(tmp_path):
    (tmp_path / "r.md").write_text("来源: https://example.com", encoding="utf-8")
    ok = Check(kind="content_assert", path="r.md", contains="来源")
    rx = Check(kind="content_assert", path="r.md", regex=r"https?://\S+")
    assert run_contract(_contract(ok, rx), workspace=tmp_path, run_cmd=_ok_run_cmd).status == "passed"
    miss = Check(kind="content_assert", path="r.md", contains="参考文献")
    assert run_contract(_contract(miss), workspace=tmp_path, run_cmd=_ok_run_cmd).status == "failed"


def test_exit_code_delegates_to_run_cmd(tmp_path):
    calls = []
    def fake_run(cmd):
        calls.append(cmd)
        return False, "1 failed", False
    v = run_contract(_contract(Check(kind="exit_code", cmd="pytest -q")),
                     workspace=tmp_path, run_cmd=fake_run)
    assert calls == ["pytest -q"] and v.status == "failed"


def test_exit_code_timeout_degrades_to_unverifiable(tmp_path):
    def timeout_run(cmd):
        return False, "timeout", True
    v = run_contract(_contract(Check(kind="exit_code", cmd="pytest -q")),
                     workspace=tmp_path, run_cmd=timeout_run)
    assert v.status == "unverifiable"      # 超时≠失败≠通过:说不准就说 unverifiable


def test_invalid_contract_is_unverifiable_fail_closed(tmp_path):
    v = run_contract(Contract(goal="g", deliverables=(), checks=()),
                     workspace=tmp_path, run_cmd=_ok_run_cmd)
    assert v.status == "unverifiable"


def test_one_fail_beats_many_passes(tmp_path):
    (tmp_path / "a.md").write_text("x", encoding="utf-8")
    v = run_contract(_contract(Check(kind="artifact_exists", path="a.md"),
                               Check(kind="artifact_exists", path="b.md")),
                     workspace=tmp_path, run_cmd=_ok_run_cmd)
    assert v.status == "failed"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/contracts/test_runner.py --no-cov -q`
Expected: FAIL with `ImportError: cannot import name 'run_contract'`

- [ ] **Step 3: Write the implementation**

```python
# argos_agent/contracts/runner.py
"""契约执行器(Factory P1):逐条跑 Check → 三态聚合成 Verdict。

判决规则(fail-closed,顺序即优先级):
  契约自身非法 → unverifiable;任一检查执行异常/超时 → unverifiable;
  任一检查失败 → failed;全部通过 → passed。
exit_code 检查经注入的 run_cmd 委托(生产 = Verifier._run_verify:白名单 +
verify_dir 隔离原样保留;本模块绝不自己起子进程)。
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path

from argos_agent.contracts.types import Check, Contract
from argos_agent.core.types import Verdict

# 与 Verifier._run_verify 同构:(ok, detail, timed_out)
RunCmd = Callable[[str], tuple[bool, str, bool]]

_OK, _FAIL, _ERROR = "ok", "fail", "error"


def _run_check(check: Check, workspace: Path, run_cmd: RunCmd) -> tuple[str, str]:
    """单条检查 → (status, detail)。status ∈ {ok, fail, error}。"""
    label = check.description or check.kind
    if check.kind == "exit_code":
        assert check.cmd is not None  # validate() 已保证
        ok, detail, timed_out = run_cmd(check.cmd)
        if timed_out:
            return _ERROR, f"{label}: 超时({check.cmd})"
        return (_OK if ok else _FAIL), f"{label}: {detail}"
    assert check.path is not None  # validate() 已保证
    p = workspace / check.path
    if not p.is_file():
        return _FAIL, f"{label}: 产物缺失 {check.path}"
    if check.kind == "artifact_exists":
        return _OK, f"{label}: {check.path} 存在"
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as e:
        return _ERROR, f"{label}: 读取失败 {e}"
    if check.kind == "artifact_schema":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            return _FAIL, f"{label}: {check.path} 非合法 JSON({e})"
        if not isinstance(data, dict):
            return _FAIL, f"{label}: {check.path} 顶层须为对象"
        missing = [k for k in (check.schema or {}).get("required", []) if k not in data]
        if missing:
            return _FAIL, f"{label}: {check.path} 缺必需键 {missing}"
        return _OK, f"{label}: schema 通过"
    # content_assert
    if check.contains is not None and check.contains not in text:
        return _FAIL, f"{label}: {check.path} 不含 {check.contains!r}"
    if check.regex is not None and not re.search(check.regex, text):
        return _FAIL, f"{label}: {check.path} 不匹配 /{check.regex}/"
    return _OK, f"{label}: 内容断言通过"


def run_contract(contract: Contract, *, workspace: Path, run_cmd: RunCmd,
                 attempts: int = 1) -> Verdict:
    """跑完整契约 → 三态 Verdict(detail 含逐条检查结果,供诊断回喂)。"""
    errors = contract.validate()
    if errors:
        return Verdict.unverifiable(
            detail="契约非法,拒绝执行:" + "; ".join(errors), tampered=[], attempts=attempts)
    lines: list[str] = []
    worst = _OK
    for check in contract.checks:
        try:
            status, detail = _run_check(check, workspace, run_cmd)
        except Exception as e:  # noqa: BLE001 — 检查自身崩 = 说不准,绝不当通过
            status, detail = _ERROR, f"{check.kind}: 检查执行异常 {e}"
        lines.append(f"[{status}] {detail}")
        if status == _ERROR:
            worst = _ERROR
        elif status == _FAIL and worst != _ERROR:
            worst = _FAIL
    summary = "\n".join(lines)
    cmd_repr = f"contract({len(contract.checks)} checks)"
    if worst == _ERROR:
        return Verdict.unverifiable(detail=summary, tampered=[], attempts=attempts)
    if worst == _FAIL:
        return Verdict.failed(detail=summary, verify_cmd=cmd_repr, attempts=attempts)
    return Verdict.passed(detail=summary, verify_cmd=cmd_repr, attempts=attempts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/contracts/test_runner.py --no-cov -q`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
rtk git add argos_agent/contracts/runner.py tests/contracts/test_runner.py
rtk git commit -m "feat(contracts): P1 契约执行器——4 种检查三态聚合,exit_code 委托注入"
```

---

### Task 3: 契约合成(模型产出 JSON → fail-closed 解析)

**Files:**
- Create: `argos_agent/contracts/synthesize.py`
- Test: `tests/contracts/test_synthesize.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/contracts/test_synthesize.py
"""parse_contract:模型输出 → Contract。fail-closed:坏 JSON/坏字段返 (None, 原因),绝不带病放行。"""
import json

from argos_agent.contracts.synthesize import build_synthesis_prompt, parse_contract

_GOOD = json.dumps({
    "goal": "写一份竞品调研报告",
    "deliverables": ["report.md"],
    "out_of_scope": ["不做 PPT"],
    "checks": [
        {"kind": "artifact_exists", "path": "report.md"},
        {"kind": "content_assert", "path": "report.md", "regex": "https?://",
         "description": "至少一个带链接的来源"},
    ],
}, ensure_ascii=False)


def test_parse_plain_json():
    c, err = parse_contract(_GOOD)
    assert err is None and c is not None
    assert c.goal == "写一份竞品调研报告" and len(c.checks) == 2
    assert c.checks[1].regex == "https?://"


def test_parse_fenced_json_with_prose_around():
    text = f"好的,契约如下:\n```json\n{_GOOD}\n```\n请确认。"
    c, err = parse_contract(text)
    assert err is None and c is not None and len(c.checks) == 2


def test_parse_garbage_fails_closed():
    c, err = parse_contract("我觉得不需要契约,直接开干吧!")
    assert c is None and err is not None


def test_parse_invalid_check_fails_closed_with_reason():
    bad = json.dumps({"goal": "g", "deliverables": ["d"],
                      "checks": [{"kind": "exit_code", "cmd": "echo ok"}]})
    c, err = parse_contract(bad)
    assert c is None and "恒真" in err          # 校验错误透传,供回喂模型重写


def test_prompt_contains_goal_and_check_kinds():
    p = build_synthesis_prompt("做个博客")
    assert "做个博客" in p
    for kind in ("exit_code", "artifact_exists", "artifact_schema", "content_assert"):
        assert kind in p
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/contracts/test_synthesize.py --no-cov -q`
Expected: FAIL with `ModuleNotFoundError`(synthesize 不存在)

- [ ] **Step 3: Write the implementation**

```python
# argos_agent/contracts/synthesize.py
"""契约合成(Factory P1):goal → 提示模型产出契约 JSON → fail-closed 解析。

解析失败返回 (None, 原因)——调用方把原因回喂模型重写,或诚实降级走无契约旧路径
(NO_TEST 标注),绝不静默捏造契约。
"""
from __future__ import annotations

import json
import re

from argos_agent.contracts.types import Check, Contract

_PROMPT = """\
你在为以下任务起草"完成契约"。契约 = 任务完成的客观定义,由机器裁决,不由你自评。

任务目标:{goal}

输出一个 JSON 对象(仅 JSON,可用 ```json 围栏),字段:
- goal: 复述目标(一句话)
- deliverables: 产物清单(人类可读,字符串数组)
- out_of_scope: 明确不做什么(字符串数组,可空)
- checks: 检查数组,每条 {{"kind": ..., ...}},kind 四选一:
  · exit_code: 附 cmd(真实测试/构建命令;echo/true 等恒真命令会被拒绝)
  · artifact_exists: 附 path(相对 workspace)
  · artifact_schema: 附 path + schema({{"required": ["key", ...]}})
  · content_assert: 附 path + contains 或 regex
要求:每个 deliverable 至少被一条 check 覆盖;能用 exit_code 优先;检查要严到
"全过即可放心交付",但不许放无法满足的检查。"""

_FENCE = re.compile(r"```(?:json)?\s*\n(.*?)```", re.DOTALL)


def build_synthesis_prompt(goal: str) -> str:
    return _PROMPT.format(goal=goal)


def parse_contract(text: str) -> tuple[Contract | None, str | None]:
    """模型输出 → (Contract, None) 或 (None, 人类可读原因)。"""
    m = _FENCE.search(text)
    raw = m.group(1) if m else text
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        return None, "输出中找不到 JSON 对象"
    try:
        data = json.loads(raw[start:end + 1])
    except json.JSONDecodeError as e:
        return None, f"JSON 解析失败:{e}"
    if not isinstance(data, dict):
        return None, "顶层须为 JSON 对象"
    try:
        checks = tuple(
            Check(kind=c.get("kind"), cmd=c.get("cmd"), path=c.get("path"),
                  schema=c.get("schema"), contains=c.get("contains"),
                  regex=c.get("regex"), description=c.get("description", ""))
            for c in data.get("checks", []) if isinstance(c, dict)
        )
        contract = Contract(
            goal=str(data.get("goal", "")).strip(),
            deliverables=tuple(str(d) for d in data.get("deliverables", [])),
            checks=checks,
            out_of_scope=tuple(str(s) for s in data.get("out_of_scope", [])),
        )
    except (TypeError, ValueError) as e:
        return None, f"字段类型不合法:{e}"
    errors = contract.validate()
    if errors:
        return None, "; ".join(errors)
    return contract, None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/contracts/test_synthesize.py --no-cov -q`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
rtk git add argos_agent/contracts/synthesize.py tests/contracts/test_synthesize.py
rtk git commit -m "feat(contracts): P1 契约合成提示 + fail-closed JSON 解析"
```

---

### Task 4: Verifier.verify_contract(接进现有验证门)

**Files:**
- Modify: `argos_agent/core/verify_gate.py`(`Verifier` 类内,`verify` 方法之后追加)
- Test: `tests/contracts/test_verifier_contract.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/contracts/test_verifier_contract.py
"""Verifier.verify_contract:契约经真 Verifier 跑——exit_code 走 _run_verify
(白名单 + verify_dir 隔离原样保留),产物检查对 workspace。"""
from pathlib import Path

from argos_agent.contracts.types import Check, Contract
from argos_agent.core.verify_gate import Verifier


def _verifier(tmp_path: Path, *, fake=None) -> Verifier:
    v = Verifier(workspace=tmp_path)          # 按现有 Verifier.__init__ 签名构造
    if fake is not None:
        v._run_verify = fake                  # 单测桩掉真子进程(slow 测试另测真跑)
    return v


def test_contract_artifact_only_no_subprocess(tmp_path):
    (tmp_path / "report.md").write_text("来源: https://e.com", encoding="utf-8")
    c = Contract(goal="g", deliverables=("report.md",),
                 checks=(Check(kind="artifact_exists", path="report.md"),
                         Check(kind="content_assert", path="report.md", regex="https?://")))
    verdict = _verifier(tmp_path).verify_contract(c)
    assert verdict.status == "passed"


def test_contract_exit_code_goes_through_run_verify(tmp_path):
    calls = []
    def fake(cmd):
        calls.append(cmd)
        return True, "ok", False
    c = Contract(goal="g", deliverables=("d",),
                 checks=(Check(kind="exit_code", cmd="pytest -q"),))
    verdict = _verifier(tmp_path, fake=fake).verify_contract(c)
    assert calls == ["pytest -q"] and verdict.status == "passed"


def test_contract_failed_aggregation(tmp_path):
    c = Contract(goal="g", deliverables=("d",),
                 checks=(Check(kind="artifact_exists", path="nope.md"),))
    assert _verifier(tmp_path).verify_contract(c).status == "failed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/contracts/test_verifier_contract.py --no-cov -q`
Expected: FAIL with `AttributeError: 'Verifier' object has no attribute 'verify_contract'`
(若 `Verifier(workspace=...)` 构造签名不符,先 `grep -n "def __init__" argos_agent/core/verify_gate.py`
按真实签名修测试夹具——改夹具,不改产品语义。)

- [ ] **Step 3: Write the implementation**

在 `argos_agent/core/verify_gate.py` 的 `Verifier` 类内、`verify()` 方法之后追加:

```python
    def verify_contract(self, contract, *, attempts: int = 1):
        """跑任务契约 → 三态 Verdict(Factory P1)。

        exit_code 检查复用 self._run_verify(白名单 + verify_dir 隔离 + 超时降级
        全部原样保留——本方法不开新的子进程路径);产物检查对 self.workspace。
        契约非法 / 检查执行异常 → unverifiable(fail-closed,绝不蒙混 passed)。
        """
        from argos_agent.contracts.runner import run_contract
        return run_contract(contract, workspace=self.workspace,
                            run_cmd=self._run_verify, attempts=attempts)
```

(若 `Verifier` 的 workspace 属性名不同,先 `grep -n "workspace" argos_agent/core/verify_gate.py`
对齐真实属性名。)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/contracts/ --no-cov -q`
Expected: 全部 passed(Task 1-4 合计 22 个)

- [ ] **Step 5: Commit**

```bash
rtk git add argos_agent/core/verify_gate.py tests/contracts/test_verifier_contract.py
rtk git commit -m "feat(verify): Verifier.verify_contract——契约经真验证门,白名单/隔离原样保留"
```

---

### Task 5: loop 接线(有契约走契约,无契约走旧路径)

**Files:**
- Modify: `argos_agent/core/loop.py`(`run_verify_gate` 一带,先定位)
- Test: 在 `tests/test_loop.py` 风格上新增 `tests/contracts/test_loop_contract.py`

- [ ] **Step 1: 定位接缝**

Run: `grep -n "verifier.verify\|run_verify_gate" argos_agent/core/loop.py`
Expected: 找到 verify 阶段调用 `verifier.verify(verify_cmd, ...)` 的唯一主路径
(约 loop.py:1030 一带;1167 是 bailout 路径,本任务不动它)。

- [ ] **Step 2: Write the failing test**

```python
# tests/contracts/test_loop_contract.py
"""loop 接线:AgentLoop 带 contract 时 verify 阶段走 verify_contract;
无 contract 行为与旧路径完全一致(不回退既有语义)。"""
from unittest.mock import MagicMock

from argos_agent.contracts.types import Check, Contract


def test_loop_prefers_contract_when_set():
    """构造最小 loop 夹具(参照 tests/test_loop.py 既有夹具),设 loop.contract 后断言
    verifier.verify_contract 被调、verifier.verify 未被调;不设则相反。"""
    contract = Contract(goal="g", deliverables=("d",),
                        checks=(Check(kind="artifact_exists", path="d"),))
    verifier = MagicMock()
    # 夹具构造按 tests/test_loop.py 中现有 AgentLoop 构造方式复制,注入 mock verifier;
    # 跑到 verify 阶段后:
    #   loop.contract = contract  → verifier.verify_contract.assert_called_once()
    #   loop.contract = None      → verifier.verify.assert_called()
```

(此测试的夹具依赖 tests/test_loop.py 的既有构造模式——执行时先读该文件复制最小夹具,
断言目标如注释所写,不得弱化。)

- [ ] **Step 3: Write the implementation**

在 `AgentLoop.__init__` 增加属性(参数表末尾,默认 None,向后兼容):

```python
        # Factory P1:任务契约。设了它,verify 阶段走 verifier.verify_contract
        # (通用任务的"完成定义");None 走旧 verify_cmd 路径,行为不回退。
        self.contract = None
```

在 Step 1 定位的 verify 主路径,把 `verdict = self._verifier.verify(...)` 改为:

```python
            if self.contract is not None:
                verdict = self._harness.verifier.verify_contract(
                    self.contract, attempts=attempts)
            else:
                verdict = self._harness.verifier.verify(verify_cmd, attempts=attempts)
```

(以定位到的真实变量名为准——改分支,不改任何一侧的既有参数与后续 escalation 逻辑。)

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/contracts/ tests/test_loop.py --no-cov -q`
Expected: 全部 passed(契约测试 + loop 既有测试零回归)

- [ ] **Step 5: 全量回归 + Commit**

Run: `uv run pytest -q` → Expected: 0 failed,coverage ≥80%

```bash
rtk git add argos_agent/core/loop.py tests/contracts/test_loop_contract.py
rtk git commit -m "feat(loop): P1 接线——有契约走 verify_contract,无契约旧路径零回退"
```

---

## Self-Review 结论

- 覆盖:4 种 Check、三态聚合、fail-closed 合成解析、Verifier 复用隔离、loop 双路径——P1 验收全覆盖。
- 类型一致性:`RunCmd = (cmd) -> (ok, detail, timed_out)` 与 `Verifier._run_verify` 同构,Task 2/4 一致;`Verdict` 统一从 `core.types` 引入。
- 已知留白(显式声明,非占位):Task 4/5 的夹具构造依赖真实 `Verifier.__init__`/`AgentLoop` 签名,步骤里给了对齐用 grep 命令——改夹具不改语义。
- 后续阶段(意图卡确认闸里展示契约、TUI 渲染契约卡)在 P2 计划,本计划不做(YAGNI)。
