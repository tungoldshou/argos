# write_file Broker Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route `write_file` / `edit_file` mutations through the CapabilityBroker so the moat's three pillars — hard rules, secret detection, and the signed receipt chain — actually cover file writes, while the byte-level write stays kernel-confined inside the Seatbelt child (Codex-style workspace-write, auto-applied).

**Architecture:** Today file writes are `_pure()` functions injected directly into the sandbox child namespace (`argos/tools/__init__.py:348-358`); they execute inside the Seatbelt subprocess (`argos/tools/files.py:84-166`) and **never touch the broker** — no receipt, no hard-path denylist, no secret detection. The evaluator HAS write-file governance logic (`argos/permissions/evaluator.py:130-164`) but it only runs from `ApprovalGate.request()`, which the synchronous sandbox bridge (`CapabilityBroker.execute_sync`, used by `broker_handler` in `argos/app_factory.py:165-167`) never calls. This plan makes file writes **gate-only broker actions**: the child's `write_file`/`edit_file` wrapper first asks the broker for a host-side decision (`broker.request` → `_BrokerStub` → `broker_handler` → `broker.execute_sync`), the host runs the *synchronous* hard-path + secret checks and signs a receipt, and **only the child performs the actual write** (so OS-kernel confinement is preserved). The broker is the gate; the sandbox child is the executor.

**Tech Stack:** Python 3.12, pytest (+ `pytest-asyncio`), HMAC receipts (`argos/tools/receipts.py`), smolagents `LocalPythonExecutor` in a macOS Seatbelt subprocess.

---

## Design decisions (per the user's "Codex 那种" steer — review before executing)

These were chosen on 2026-06-15. If any is wrong, correct it before writing code.

1. **Write stays in the Seatbelt child (NOT host-side).** Like OpenAI Codex's `workspace-write` sandbox, the OS sandbox is the enforcement boundary and edits within the workspace are auto-applied. We do **not** move the write to `broker._execute` host-side. The broker is a *gate-only* decision point for file writes: it validates + signs a receipt and returns an approval sentinel; the child does the `p.write_text(...)`.

2. **Governance added on top of the Codex-style execution:** host-side **hard-path denylist** (`/etc/`, `~/.ssh/`, …) and **secret detection** (D8) run synchronously in the broker before the write is approved, plus a **signed HMAC receipt** per approved write (the moat). This is the part Codex does not have.

3. **fail-closed only on hard rules + secrets.** On the synchronous bridge (`execute_sync`) interactive "ask" cannot await a user, so:
   - `evaluate()` `decision == "deny"` (hard-path system path) → **deny, no write, no receipt**.
   - `evaluate()` flags a `secret_pattern` → **deny** with an honest message ("possible secret; remove it or ask the user to allow"), no write, no receipt.
   - everything else — including the normal `ask` that `evaluate()` returns under the default `CONFIRM` level — **auto-proceeds** (sign receipt + return sentinel). This matches how `run_command` already behaves on the sync bridge (`execute_sync` deliberately skips ② interactive approval, per `argos/sandbox/broker.py:142-175`), and IS the Codex auto-apply behavior. **Critical:** do not treat a bare `ask` as deny — that would block every write under the default gate level.

4. **Interactive per-write approval is deferred (out of scope).** The sandbox runs synchronously (`argos/core/loop.py:1334` calls `self._sandbox.exec_code(code)` with no `await`, blocking the event loop), so a mid-exec `await gate.request(...)` cannot get a UI response. Closing this for *all* sandbox tool calls (incl. `run_command`) is the broader sync-bridge gap and belongs with item 1 (the loop architecture flip), consistent with the existing `execute_sync` "approval 留 v1.1" note. The async `request()` path is still wired (Task 4) so interactive approval works if/when a caller uses it.

5. **Receipt attests the approved decision**, signed over `{action, args}` with `result = WRITE_APPROVED_SENTINEL`. It means "broker approved a write of `<path>` with `<content-hash>`". The child then writes exactly that. (Receipt-attests-completed-write would need a second round-trip; not worth it for item 3.)

### Out of scope (do not do here)
- Interactive approval for sandbox-issued tools (the sync-bridge gap; item 1).
- Multiple receipts per act-step (`loop.py:1427` takes only the last `take_receipt()`; pre-existing).
- Moving `run_command` hard-shell rules onto the sync bridge (separate; this plan only fixes file writes).
- Linux `bwrap` no-isolation fallback honesty (spec §6 second bullet; separate task).

---

## File structure

| File | Change | Responsibility after change |
|---|---|---|
| `argos/permissions/evaluator.py` | unchanged | Already has write-file hard-path (`_check_hard_path_write`, 71-93) + secret (153-164) logic. |
| `argos/approval.py` | +1 method | Expose `evaluate_sync()` so the broker can get a synchronous decision without `await`. |
| `argos/tools/files.py` | +1 constant | `WRITE_APPROVED_SENTINEL` — the host→child approval marker. |
| `argos/sandbox/broker.py` | +`_RISK` entries, +`_FILE_WRITE_ACTIONS`, +gate-only branches in `execute_sync` & `request`, +`_describe` cases, +`import files` | Gate-only governance for file writes; signs receipt; returns sentinel. Never executes the write. |
| `argos/tools/__init__.py` | move `write_file`/`edit_file` from `_pure()` into `_make_gated()` as round-trip-then-write wrappers | Child write tools now broker-gated; pure (no-broker) namespace has no write tools (honest fail-closed). |
| `argos/capability/builtins.py` | unchanged | `write_file`/`edit_file` already registered (76-91). |
| `argos/core/loop.py` | unchanged | `made_changes` text-detection (1338) + LSP sync (1344-1371) + `take_receipt` (1427-1430) all keep working — the namespace key is still `write_file`/`edit_file`. |
| `tests/test_approval_evaluate_sync.py` | create | Unit-test `evaluate_sync`. |
| `tests/test_broker_execute_sync.py` | extend | Sync-bridge write gate (the real path). |
| `tests/test_broker_request.py` | extend | Async write gate (symmetry/interactive). |
| `tests/test_tools_write_gated.py` | create | Child wrapper round-trip + local write + no-broker namespace. |
| `CLAUDE.md`, design spec | doc | Reframe tools/ description; record the decision. |

---

## Task 1: `ApprovalGate.evaluate_sync` — synchronous decision accessor

**Files:**
- Modify: `argos/approval.py` (add method near `_evaluate`, after line 289)
- Test: `tests/test_approval_evaluate_sync.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_approval_evaluate_sync.py
"""evaluate_sync:同步暴露 evaluator 决策,供 broker 同步桥跑 hard-path 拒 + 密钥检测。"""
from __future__ import annotations

from argos.approval import ApprovalGate, ApprovalLevel


def test_evaluate_sync_system_path_denied():
    gate = ApprovalGate(ApprovalLevel.AUTO)
    meta = gate.evaluate_sync("write_file", {"path": "/etc/passwd", "content": "x"})
    assert meta is not None and meta.decision == "deny"
    assert "system_path" in meta.trigger or "/etc/" in meta.reason


def test_evaluate_sync_secret_flagged():
    gate = ApprovalGate(ApprovalLevel.AUTO)
    # AWS 示例 access-key(test_secret_writes.py 同款模式)
    meta = gate.evaluate_sync("write_file", {"path": "a.py", "content": "AKIAIOSFODNN7EXAMPLE"})
    assert meta is not None and meta.secret_pattern is not None


def test_evaluate_sync_workspace_write_not_denied():
    gate = ApprovalGate(ApprovalLevel.AUTO)
    meta = gate.evaluate_sync("write_file", {"path": "a.py", "content": "print(1)"})
    assert meta is not None and meta.decision != "deny"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_approval_evaluate_sync.py -q`
Expected: FAIL — `AttributeError: 'ApprovalGate' object has no attribute 'evaluate_sync'`

- [ ] **Step 3: Write minimal implementation**

In `argos/approval.py`, immediately after `_evaluate` ends (after line 289), add:

```python
    def evaluate_sync(self, action: str, args: dict[str, Any]) -> "DecisionMeta | None":
        """同步暴露 evaluator 决策(hard → secret → soft → level),供 broker 同步桥
        (execute_sync,无法 await gate)跑 hard-path 拒 + 密钥检测。
        返回 None = evaluator 不可用(import/config 坏)→ 调用方退回既有语义,绝不阻塞。"""
        return self._evaluate(action, args)
```

(If `DecisionMeta` isn't already importable at type-check time, the string annotation needs no runtime import; `_evaluate` already returns it.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_approval_evaluate_sync.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add argos/approval.py tests/test_approval_evaluate_sync.py
git commit -m "feat(approval): add evaluate_sync for synchronous broker-side governance"
```

---

## Task 2: `WRITE_APPROVED_SENTINEL` constant in files.py

**Files:**
- Modify: `argos/tools/files.py` (add constant after `WORKSPACE`, ~line 16)
- Test: folded into Task 5 (the wrapper tests consume it); add a trivial guard here.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tools_write_gated.py  (create — Task 5 extends it)
from argos.tools import files


def test_write_approved_sentinel_is_distinctive_str():
    s = files.WRITE_APPROVED_SENTINEL
    assert isinstance(s, str) and len(s) > 0
    # 不能与任何正常工具返回串/文件内容碰撞
    assert "\x00" in s
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tools_write_gated.py::test_write_approved_sentinel_is_distinctive_str -q`
Expected: FAIL — `AttributeError: module 'argos.tools.files' has no attribute 'WRITE_APPROVED_SENTINEL'`

- [ ] **Step 3: Write minimal implementation**

In `argos/tools/files.py`, after the `WORKSPACE = ...` line (line 15), add:

```python
# host→child 放行哨兵:broker(host)对一次文件写做完治理裁决并签回执后,把它回灌给沙箱子进程;
# 子进程内的 write_file/edit_file 包装识别到它才真正落盘(Codex 式:写留在 Seatbelt 内)。
# 含 NUL,绝不与正常工具返回串/文件内容碰撞。
WRITE_APPROVED_SENTINEL = "\x00__ARGOS_WRITE_APPROVED__\x00"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_tools_write_gated.py::test_write_approved_sentinel_is_distinctive_str -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add argos/tools/files.py tests/test_tools_write_gated.py
git commit -m "feat(tools): add WRITE_APPROVED_SENTINEL host->child write-approval marker"
```

---

## Task 3: Broker gate-only governance on the synchronous bridge (the real path)

**Files:**
- Modify: `argos/sandbox/broker.py` — add `import`, `_RISK` entries, `_FILE_WRITE_ACTIONS`, a helper, an `execute_sync` branch, `_describe` cases.
- Test: `tests/test_broker_execute_sync.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_broker_execute_sync.py`:

```python
def test_execute_sync_write_file_workspace_approved_signs_receipt(tmp_path):
    """workspace 写在同步桥放行(Codex 式自动应用),签回执,返回放行哨兵。"""
    from argos.tools.files import WRITE_APPROVED_SENTINEL
    br = _broker(workspace=tmp_path)
    br.gate.set_workspace(str(tmp_path))
    value, code = br.execute_sync("write_file", {"path": "a.py", "content": "print(1)"})
    assert value == WRITE_APPROVED_SENTINEL and code == 0
    rec = br.take_receipt()
    assert rec is not None and rec.action == "write_file"


def test_execute_sync_write_file_confirm_level_auto_proceeds(tmp_path):
    """CONFIRM 档下 evaluator 返 ask(level:confirm),同步桥无法 await → 自动放行,
    绝不被误当 deny(否则默认档会阻断一切写)。"""
    from argos.tools.files import WRITE_APPROVED_SENTINEL
    gate = ApprovalGate(level=ApprovalLevel.CONFIRM)
    gate.set_workspace(str(tmp_path))
    egress = EgressPolicy(llm_hosts=set(), search_hosts=set(), mcp_hosts=set())
    br = CapabilityBroker(gate=gate, egress=egress,
                          signer=ReceiptSigner(key=b"k"), workspace=tmp_path)
    value, code = br.execute_sync("write_file", {"path": "a.py", "content": "ok"})
    assert value == WRITE_APPROVED_SENTINEL and code == 0


def test_execute_sync_write_file_system_path_denied():
    """hard-path 系统路径 fail-closed:不放行、不签回执。"""
    br = _broker()
    value, code = br.execute_sync("write_file", {"path": "/etc/passwd", "content": "x"})
    assert ("/etc/" in str(value)) or ("拒绝" in str(value))
    assert code == 1
    assert br.take_receipt() is None


def test_execute_sync_write_file_secret_denied():
    """密钥命中 → fail-closed deny(同步桥无法 await 确认),不签回执。"""
    br = _broker()
    value, code = br.execute_sync("write_file", {"path": "a.py", "content": "AKIAIOSFODNN7EXAMPLE"})
    assert "密钥" in str(value)
    assert code == 1 and br.take_receipt() is None


def test_execute_sync_edit_file_secret_checks_new_text():
    """edit_file 密钥检测看替换后的新文本(args['content']=new)。"""
    br = _broker()
    value, code = br.execute_sync("edit_file", {
        "path": "a.py", "old": "x", "new": "AKIAIOSFODNN7EXAMPLE",
        "content": "AKIAIOSFODNN7EXAMPLE", "all_occurrences": False,
    })
    assert "密钥" in str(value) and code == 1
```

(`test_broker_execute_sync.py` already imports `ApprovalGate, ApprovalLevel, CapabilityBroker, EgressPolicy, ReceiptSigner` and defines `_broker(workspace=None)`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_broker_execute_sync.py -q`
Expected: FAIL — the new tests fail because `write_file` is rejected as unknown action (`错误:未知/不支持的特权动作 'write_file'`) and no sentinel/receipt is produced.

- [ ] **Step 3: Write minimal implementation**

In `argos/sandbox/broker.py`:

(a) Add import near the other tools imports (after line 19):

```python
from argos.tools import files as _files
```

(b) Add file-write actions to `_RISK` (so the no-registry fallback path accepts them) — inside the `_RISK` dict (after line 33 `"web_extract": "low",`):

```python
    # 文件写:gate-only(host 裁决+回执;落盘在 Seatbelt 子进程)。registry 已声明它们,
    # 这里给无 registry 的 fallback 路径(headless/旧测试)也认得 → fail-closed 不误拒。
    "write_file": "low",
    "edit_file": "low",
```

(c) Add the action set + helper near `_FORCE_CONFIRM_ACTIONS` (after line 53):

```python
# 文件写动作:broker 只做 host 侧 gate-only 治理(裁决 + 回执),真正落盘留在 Seatbelt 子进程。
_FILE_WRITE_ACTIONS: set[str] = {"write_file", "edit_file"}
```

(d) Add the synchronous helper as a method on `CapabilityBroker` (place it right after `execute_sync`, before `_derive_network_actions`):

```python
    def _gate_only_write_sync(self, action: str, args: dict[str, Any]) -> tuple[Any, int | None]:
        """write_file/edit_file 的同步治理裁决(execute_sync 路径,无法 await 交互审批)。

        - hard-path 系统路径命中(evaluator decision==deny)→ deny,不签回执(无副作用)。
        - 密钥命中 → fail-closed deny(同步桥无法 await 确认;诚实告知模型),不签回执。
        - 其余(含因档位/软规则本应 ask 的)→ 自动放行 —— 与 run_command 同步桥跳过②审批一致
          (= Codex 式:OS 沙箱限死 workspace + 自动应用)。签回执(治理铁证),返回放行哨兵;
          真正落盘由子进程 write_file_gated 包装在 Seatbelt 内执行。
        """
        meta = self._gate.evaluate_sync(action, args)
        if meta is not None:
            if meta.decision == "deny":
                return (meta.reason or f"{action} 被硬规则拒绝。"), 1
            if meta.secret_pattern or (meta.trigger or "").startswith("secret:"):
                return (
                    f"⚠ 可能含密钥({meta.secret_pattern or '?'})—— 已拒绝写入。"
                    "请去掉密钥后重试,或请用户显式放行该写入。"
                ), 1
        # 放行:签回执;落盘交子进程。
        self.last_receipt = self._signer.sign(
            action=action, args=args, result=_files.WRITE_APPROVED_SENTINEL, exit_code=0,
        )
        return _files.WRITE_APPROVED_SENTINEL, 0
```

(e) In `execute_sync`, after the fail-closed action check (after line 160, before the `① egress` block at line 161), add:

```python
        # 文件写:gate-only 治理(host 侧裁决 + 回执;落盘留 Seatbelt 子进程)。非网络,跳过 egress。
        if action in _FILE_WRITE_ACTIONS:
            return self._gate_only_write_sync(action, args)
```

(f) Add `_describe` cases (after line 410 web_extract case) so the async approval UI has text:

```python
        if action == "write_file":
            return f"写文件 {args.get('path', '')}"
        if action == "edit_file":
            return f"编辑文件 {args.get('path', '')}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_broker_execute_sync.py -q`
Expected: PASS (all original + 5 new tests)

- [ ] **Step 5: Commit**

```bash
git add argos/sandbox/broker.py tests/test_broker_execute_sync.py
git commit -m "feat(broker): gate-only governance for file writes on the sync bridge"
```

---

## Task 4: Broker gate-only governance on the async `request()` path (symmetry + interactive)

**Files:**
- Modify: `argos/sandbox/broker.py` — add a file-write branch in `request()`.
- Test: `tests/test_broker_request.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_broker_request.py` (it already has `_broker(...)` and asyncio tests; mirror its helpers):

```python
@pytest.mark.asyncio
async def test_request_write_file_system_path_denied():
    """async 路径:系统路径写在 AUTO 档仍被 evaluator hard-path deny,不签回执。"""
    br = _broker()  # AUTO 档
    value = await br.request("write_file", {"path": "/etc/shadow", "content": "x"})
    assert ("/etc/" in str(value)) or ("拒绝" in str(value))
    assert br.last_receipt is None


@pytest.mark.asyncio
async def test_request_write_file_approved_returns_sentinel(tmp_path):
    """async 路径:workspace 写经审批放行 → 返回放行哨兵 + 签回执。"""
    from argos.tools.files import WRITE_APPROVED_SENTINEL
    br = _broker(workspace=tmp_path)
    br.gate.set_workspace(str(tmp_path))
    value = await br.request("write_file", {"path": "a.py", "content": "ok"})
    assert value == WRITE_APPROVED_SENTINEL
    assert br.last_receipt is not None and br.last_receipt.action == "write_file"
```

Verify `tests/test_broker_request.py`'s `_broker(...)` helper signature matches (it builds `CapabilityBroker` with `gate=ApprovalGate(...)`); if its `_broker` has no `workspace` kwarg, construct the broker inline in the second test like Task 3's CONFIRM test.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_broker_request.py -k write_file -q`
Expected: FAIL — `request` currently routes `write_file` to `_execute` which returns `错误:动作 'write_file' 暂未实现 host 执行。` (and signs a receipt for it), so neither assertion holds.

- [ ] **Step 3: Write minimal implementation**

In `argos/sandbox/broker.py` `request()`, after the fail-closed action check (after line 106) and before the `① egress` block (line 108), add:

```python
        # 文件写:gate-only 治理(async 路径可 await 交互审批);落盘留子进程,broker 不执行写。
        if action in _FILE_WRITE_ACTIONS:
            decision = await self._request_decision(
                action, args, None, registry_risk=_registry_risk,
            )
            if not decision.approved:
                return (
                    f"用户拒绝该写入({decision.reason or '未提供原因'})。"
                    "请尝试其他做法或向用户解释为什么需要它。"
                )
            self.last_receipt = self._signer.sign(
                action=action, args=args, result=_files.WRITE_APPROVED_SENTINEL, exit_code=0,
            )
            return _files.WRITE_APPROVED_SENTINEL
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_broker_request.py -k write_file -q`
Expected: PASS (2 new)

- [ ] **Step 5: Commit**

```bash
git add argos/sandbox/broker.py tests/test_broker_request.py
git commit -m "feat(broker): gate-only governance for file writes on the async request path"
```

---

## Task 5: Make the child's write tools broker-gated (round-trip then write on approval)

**Files:**
- Modify: `argos/tools/__init__.py` — `_make_gated` (138-240) add wrappers + return entries; `_pure` (348-358) remove `write_file`/`edit_file`.
- Test: `tests/test_tools_write_gated.py` (extend the Task-2 file)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tools_write_gated.py`:

```python
def test_write_file_gated_writes_on_approval(tmp_path, monkeypatch):
    from argos.tools import build_child_namespace, files
    monkeypatch.setattr(files, "WORKSPACE", tmp_path.resolve())

    class _OkBroker:
        def request(self, action, args):
            return files.WRITE_APPROVED_SENTINEL

    ns = build_child_namespace(_OkBroker())
    assert "write_file" in ns
    out = ns["write_file"]("a.txt", "hello")
    assert "已写入" in out
    assert (tmp_path / "a.txt").read_text() == "hello"


def test_write_file_gated_denied_no_write(tmp_path, monkeypatch):
    from argos.tools import build_child_namespace, files
    monkeypatch.setattr(files, "WORKSPACE", tmp_path.resolve())

    class _DenyBroker:
        def request(self, action, args):
            return "用户拒绝该写入(系统路径)。"

    ns = build_child_namespace(_DenyBroker())
    out = ns["write_file"]("a.txt", "hello")
    assert "拒绝" in out
    assert not (tmp_path / "a.txt").exists()


def test_edit_file_gated_passes_new_as_content(tmp_path, monkeypatch):
    from argos.tools import build_child_namespace, files
    monkeypatch.setattr(files, "WORKSPACE", tmp_path.resolve())
    files.write_file("a.py", "old")
    seen: dict = {}

    class _SpyBroker:
        def request(self, action, args):
            seen.update(args)
            return files.WRITE_APPROVED_SENTINEL

    ns = build_child_namespace(_SpyBroker())
    ns["edit_file"]("a.py", "old", "newval")
    assert seen.get("content") == "newval"          # 密钥检测能看到替换后的新文本
    assert (tmp_path / "a.py").read_text() == "newval"


def test_pure_namespace_has_no_write_without_broker():
    """无 broker(纯沙箱)= 无写工具(诚实 fail-closed:不能治理就不给写),只读工具仍在。"""
    from argos.tools import build_child_namespace
    ns = build_child_namespace(None)
    assert "write_file" not in ns and "edit_file" not in ns
    assert "read_file" in ns and "search_files" in ns
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tools_write_gated.py -q`
Expected: FAIL — currently `build_child_namespace(None)` DOES contain `write_file` (from `_pure()`), and the gated wrappers don't exist, so `test_pure_namespace_has_no_write_without_broker` fails and the others don't round-trip through the broker.

- [ ] **Step 3: Write minimal implementation**

In `argos/tools/__init__.py`:

(a) Inside `_make_gated(broker)`, before the `return {` (line 217), add the two wrappers:

```python
    # 文件写 —— broker-gated(gate-only):先问 broker 要 host 侧治理裁决(hard-path/密钥/回执),
    # 放行后由本包装在【沙箱子进程内】真正落盘(Codex 式:OS 沙箱限死 workspace + 自动应用)。
    def write_file_gated(path: str, content: str) -> str:
        verdict = broker.request(action="write_file", args={"path": path, "content": content})
        if verdict == files.WRITE_APPROVED_SENTINEL:
            return files.write_file(path, content)
        return verdict

    def edit_file_gated(path: str, old: str, new: str, all_occurrences: bool = False) -> str:
        # content=new 让 evaluator 密钥检测命中替换后的新文本(evaluator.py:156-164)。
        verdict = broker.request(action="edit_file", args={
            "path": path, "old": old, "new": new,
            "all_occurrences": all_occurrences, "content": new,
        })
        if verdict == files.WRITE_APPROVED_SENTINEL:
            return files.edit_file(path, old, new, all_occurrences)
        return verdict
```

(b) In the `return {` dict of `_make_gated` (after line 218 `"run_command": run_command_gated,`), add:

```python
        "write_file": write_file_gated,
        "edit_file": edit_file_gated,
```

(c) In `_pure()` (line 349-358), DELETE the two lines:

```python
        "write_file": files.write_file,
        "edit_file": files.edit_file,
```

(keep `read_file`, `search_files`, and the `propose_*`/`update_plan` entries).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools_write_gated.py -q`
Expected: PASS (4 + the sentinel guard)

- [ ] **Step 5: Commit**

```bash
git add argos/tools/__init__.py tests/test_tools_write_gated.py
git commit -m "feat(tools): route child write_file/edit_file through the broker (gate-only)"
```

---

## Task 6: Full-suite triage — update tests that encoded the old (ungoverned) behavior

**Files:** whatever the suite surfaces. Likely candidates from the code map:
- `tests/test_loop_per_step_receipt.py` — `StepBroker` mock (61-84) + `test_no_receipt_when_no_broker_action` (131). A code block that writes now produces a receipt; mocks must implement `.request("write_file", …)` returning the sentinel (or the test scenario must avoid writes where it asserts "no receipt").
- `tests/e2e/conftest.py` (`build_real_loop`, 48-86) and `tests/workflow/conftest.py` (`workflow_loop`, 15-63) — real broker bridge: writes now go child→`execute_sync`→sentinel→child writes. Workspace-relative paths approve (not system paths), so writes still happen, but a **new `ToolReceipt` event** now appears for each write — update any test asserting an exact event sequence.
- Any test building `build_child_namespace(None)` (or `build_namespace`) and calling `write_file`/`edit_file` from the namespace — must pass a broker now, or call `files.write_file` directly.

- [ ] **Step 1: Run the targeted suites first**

```bash
uv run pytest tests/test_loop_per_step_receipt.py tests/test_tools_files.py \
  tests/e2e tests/workflow -q -m "not slow"
```
Expected: identify failures. `tests/test_tools_files.py` imports `files.*` directly → should still pass.

- [ ] **Step 2: Fix each failure at its root**

For each failure, decide: does it encode the **moat** (keep, and the new receipt is correct) or the **old ungoverned behavior** (update)? Update mocks to handle `write_file`/`edit_file` (return `files.WRITE_APPROVED_SENTINEL`), and add the now-expected `ToolReceipt` to sequence assertions. Show the diff in the PR; do not weaken a moat assertion to make a test pass.

- [ ] **Step 3: Run the full suite (parallel)**

```bash
uv run pytest -n auto --dist loadgroup -q
```
Expected: green except known pre-existing failures (the Docker test noted in observation 6608). Coverage ≥ 80% on the full run.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "test: update mocks/sequences for broker-gated file writes"
```

---

## Task 7: Documentation — reframe and record the decision

**Files:**
- Modify: `CLAUDE.md` (the `tools/` row, ~line 124)
- Modify: `docs/superpowers/specs/2026-06-15-strategic-pivot-verify-moat-design.md` (decision log §10)

- [ ] **Step 1: Update `CLAUDE.md` tools/ description**

Replace the `tools/` table row so it is now *true*: file writes are broker-gated (gate-only — host decides + receipts, the Seatbelt child executes the write). Keep it one line.

```
| `tools/` | broker-gated tools: shell/web/browser/mcp execute host-side; **file writes are gate-only** — the host broker runs hard-path + secret checks and signs a receipt, the Seatbelt child performs the write; read_file/search_files are pure-sandbox |
```

- [ ] **Step 2: Append to the design spec decision log (§10)**

```markdown
- Item 3 implemented (2026-06-15): write_file/edit_file routed through the broker as
  **gate-only** actions — host-side hard-path denylist + secret detection (fail-closed) +
  signed receipt; the actual write stays in the Seatbelt child ("Codex 那种": OS sandbox is
  the boundary, workspace writes auto-apply). Interactive per-write approval deferred to the
  sync-bridge/loop work (item 1), consistent with execute_sync's existing "approval 留 v1.1".
  _(user picked the keep-write-in-sandbox option; "Codex 那种")_
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md docs/superpowers/specs/2026-06-15-strategic-pivot-verify-moat-design.md
git commit -m "docs: file writes are broker gate-only; record item-3 decision"
```

---

## Task 8: Final verification

- [ ] **Step 1: Full suite + coverage**

```bash
uv run pytest -n auto --dist loadgroup -q
```
Expected: green (modulo the known Docker pre-existing failure); coverage ≥ 80%.

- [ ] **Step 2: Confirm the moat actually engages end-to-end (manual smoke)**

```bash
uv run pytest tests/test_broker_execute_sync.py tests/test_broker_request.py \
  tests/test_tools_write_gated.py tests/test_approval_evaluate_sync.py -q
```
Expected: PASS. Spot-check: a `write_file` of `/etc/passwd` is denied with no receipt; a workspace write returns the sentinel and produces a `write_file` receipt.

- [ ] **Step 3: Branch hygiene note**

This work is unrelated to the current `feat/tui-obsidian-eye-widgets` branch. Execute on a fresh branch off `main` (e.g. `feat/write-file-broker-gate`). The untracked repo-root artifacts (`test_core.py`, `test_dev_null.py`, `test_import.py`, `test_pytest_log.py`, `test_temp.py`, `test_verify.py`, `NONE`, `pytest.ini`, `.argos_run.sb`, `.argos_sandbox.sb`) are stray sandbox/verify run output — do NOT add them; confirm with the user before deleting.

---

## Self-review

**Spec coverage (against the design spec §6 / §7 item 3):**
- "Route file mutations through the broker" → Tasks 3, 4, 5 (child wrapper → broker → child write). ✓
- "receipt chain … complete" → Task 3/4 sign a receipt per approved write; ledger picks it up via the existing `loop.py:1427-1430` `take_receipt` → `ToolReceipt`. ✓
- "hard rules … complete" → Task 1 + Task 3 run the synchronous hard-path denylist + secret detection on the real (sync-bridge) write path. ✓
- "OS sandbox preserved" → write stays in the Seatbelt child (Design decision 1). ✓
- Linux `bwrap` no-isolation honesty → explicitly out of scope (separate task). Noted.

**Placeholder scan:** every code step shows the actual code; commands have expected output; no "TBD"/"add error handling". The one empirical task (Task 6) cannot enumerate failures in advance, so it gives the candidate list + the decision rule (moat vs old-behavior) instead of fake code — this is correct for a triage step.

**Type/name consistency:** `WRITE_APPROVED_SENTINEL` defined in `files.py` (Task 2), imported as `_files.WRITE_APPROVED_SENTINEL` in broker (Task 3) and `files.WRITE_APPROVED_SENTINEL` in tools/__init__ (Task 5) and tests — consistent. `_FILE_WRITE_ACTIONS` defined once (Task 3), used in `execute_sync` (Task 3) and `request` (Task 4). `evaluate_sync` signature `(action, args) -> DecisionMeta | None` matches `_evaluate` and its use in `_gate_only_write_sync`. `edit_file` broker args include `content=new`, matching the evaluator's edit_file secret branch (`evaluator.py:156-164`). ✓

**Risk check (spec §8):** the verify gate, three-state verdict, tamper detection, and Seatbelt profile are untouched. `made_changes` text-detection (`loop.py:1338`) and LSP sync still key on the `write_file(`/`edit_file(` source text, which is unchanged (the namespace key stays the same). The only behavior change for coding runs is an added `ToolReceipt` per write + fail-closed on hard-path/secret — both strengthen the moat.
