# P4 集成注记

本文件记录 P4 并行轨各组件完成后、集成阶段统一接线时需要处理的接入点。
由各子组件实现者追加，集成阶段按节处理。

---

## 组件1：intent/ — NL→Goal 意图引擎（2026-06-11）

**交付文件：**
- `argos_agent/intent/__init__.py`
- `argos_agent/intent/card.py` — `IntentCard` frozen dataclass
- `argos_agent/intent/engine.py` — `IntentEngine`（`parse` + `render_confirmation`）
- `tests/intent/__init__.py`
- `tests/intent/test_intent_engine.py` — 32 个测试全绿

---

### A. loop.py 接入点（run() 之前的预处理）

`AgentLoop.run(goal, ...)` 在进入四阶段循环前，应先经 `IntentEngine.parse()` 将口语 goal 转为结构化 `IntentCard`。

推荐接线位置：`core/loop.py` 的 `run()` 开头，在构建系统提示和记忆召回之前：

```python
# 推荐写法（loop.py run() 最前部）
from argos_agent.intent import IntentEngine, IntentCard

intent_card: IntentCard = await IntentEngine().parse(goal, self._model)
if intent_card.confirmation_required:
    # 投出确认请求事件，等用户确认后继续
    await self._bus.put(IntentConfirmRequest(
        call_id=_new_id(),
        card_json=dataclasses.asdict(intent_card),
        confirmation_text=IntentEngine.render_confirmation(intent_card),
    ))
    await self._intent_confirm_event.wait()  # 挂起等确认
    if not self._intent_confirmed:
        # 用户取消 → 诚实收尾
        return
# 用确认后的 goal 继续
effective_goal = intent_card.goal
```

接线时**不得修改**禁区文件以外的路径；推荐在 `run()` 中以新增局部变量方式接入，不改现有四阶段门逻辑。

---

### B. 新事件提案：`IntentConfirmRequest`

与 `PlanDecisionRequest`（`protocol/events.py:227`）**同构**的确认事件，需加入 `protocol/events.py`：

```python
@dataclass(frozen=True, slots=True)
class IntentConfirmRequest:
    """意图确认请求事件。
    loop 在检测到 confirmation_required=True 时投出此事件，
    挂起等用户通过 TUI/daemon 响应。
    超时 fail-closed：默认取消，诚实退出（不擅自执行不确定意图）。
    """
    kind = "intent_confirm_request"
    call_id: str                        # 12 hex，与响应事件对应
    confirmation_text: str              # IntentEngine.render_confirmation() 产出的人话文本
    card_json: dict                     # IntentCard 的 asdict() 序列化，供 daemon 路径独立消费
```

对应响应事件（Command 类型，客户端→内核方向）：

```python
@dataclass(frozen=True, slots=True)
class IntentConfirmResponse:
    kind = "intent_confirm_response"
    call_id: str
    confirmed: bool
    revised_goal: str | None = None     # 用户可选择修改 goal 后再确认
```

---

### C. daemon create_run 的 intent 参数提案

`POST /runs` 建议增加可选参数，默认 `false` 保持向后兼容：

```json
{
  "goal": "原始口语",
  "intent_preparse": false
}
```

`intent_preparse=true` → daemon 侧调 `IntentEngine.parse()` 再投 `IntentConfirmRequest`；`false` → goal 直接透传（当前行为）。

---

### D. 约束与限制

1. `IntentEngine.parse()` 需要一个 `_ModelLike` duck-type（`stream(messages, *, system, ...)`）。集成时直接传 `ModelClient` 实例，与 loop 共享同一 model，无需额外实例化。
2. 高风险词表（`_RISK_WORDS`）在 `intent/engine.py` 内定义；如需外部配置，可在 `IntentEngine.__init__` 增加 `extra_risk_words` 参数合并。
3. `IntentCard` 是 frozen dataclass，可安全穿越 asyncio 边界（`dataclasses.asdict()` 直接可用）。
4. 所有 fail-closed 路径已有测试覆盖：垃圾 JSON / 空 response / 缺字段 / goal 为空 / 模型异常 → 全部降级到 `goal=原话, confirmation_required=True`。

---

## 组件3：Trust Dial（`argos_agent/permissions/trust_dial.py`）

### 已完成

- `TrustLevel`（IntEnum L0-L4）+ `label_human` / `description` 属性
- `to_approval_semantics(level)` → dict（映射到 ApprovalLevel 枚举值字符串）
- `hard_rules_immune()` 契约函数（永远 True）
- `escalation_warning(from_level, to_level)` 升档警示（升档非空 / 降档空串）
- `suggest_escalation(history, ...)` 阈值建议（绝不自动升档，建议永带警示）
- `EscalationSuggestion` frozen dataclass（warning 空串时 __post_init__ 抛 ValueError）
- 83 个测试全绿（`tests/permissions/test_trust_dial.py`）

### 集成接线点

#### 1. `approval.py` / `ApprovalGate.set_level` 接线

**接入点**：`ApprovalGate.set_level(level: ApprovalLevel)` 已存在。

**集成方案**：在 `ApprovalGate`（或其上层装配函数）添加一个辅助方法：

```python
from argos_agent.permissions.trust_dial import TrustLevel, to_approval_semantics
from argos_agent.approval import ApprovalLevel

def apply_trust_level(gate: ApprovalGate, trust: TrustLevel) -> None:
    """将 TrustLevel 映射到 ApprovalLevel 并写入 gate。"""
    sem = to_approval_semantics(trust)
    al = ApprovalLevel(sem["approval_level"])
    gate.set_level(al)
    # L0 的 ask_readonly=True 需要 gate 额外记录（当前 gate 无此字段，集成时酌情扩展或用 evaluator soft-rules 实现）
    # L2 的 reversible_check=True 需要 P2 Capability manifest reversible 字段就位
```

**注意**：
- `to_approval_semantics` 返回 `approval_level` 为字符串，需通过 `ApprovalLevel(value)` 转换。
- L2 `reversible_check=True` 依赖 P2 能力 manifest 的 `reversible` 字段，P2 未完成前 L2 退化为 L1 行为（只看 risk level 过滤）。集成时应在文案/TUI 提示中明确标注。

#### 2. TUI `/trust` 命令提案

**接入点**：`tui/app.py` slash 命令注册（现有 `/yolo` 命令为参考）。

**提案**：

```
/trust l0      → 设置 L0_EVERY_STEP（最保守）
/trust l1      → 设置 L1_DANGEROUS_ONLY
/trust l2      → 设置 L2_IRREVERSIBLE_ONLY
/trust l3      → 设置 L3_SESSION_TRUSTED
/trust l4      → 设置 L4_AUTONOMOUS（全自治，头部显示红色 ⏻ 灯）
/trust status  → 显示当前档位、label_human、description
```

升档时 TUI 必须先展示 `escalation_warning(current, new)` 返回的文案，等用户确认后才调用 `apply_trust_level`。

旧 `/yolo` 命令可作为 `/trust l4` 的别名，并在输出中提示"旧命令 /yolo 已映射到 /trust l4"。

#### 3. `daemon` `create_run` 的 `trust_level` 参数提案

**接入点**：`daemon/` 中的 run 创建路径（具体文件由 P1 内核通电确定）。

**提案**：在 `create_run` 的请求参数中增加可选的 `trust_level: str | None`（L0-L4 名称或整数字符串）：

```python
# ACP Command: create_run
{
    "kind": "create_run",
    "task": "...",
    "trust_level": "L1_DANGEROUS_ONLY",   # 可选，默认 L0_EVERY_STEP
    ...
}
```

`daemon` 在装配 `ApprovalGate` 时：

```python
trust = TrustLevel[data.get("trust_level", "L0_EVERY_STEP")]
apply_trust_level(gate, trust)
```

自治面（Conductor，P5）的自治 run 建议默认使用 `L1_DANGEROUS_ONLY`（仅危险操作问）而非 L4（全自治），以保留最低安全网。

#### 4. `suggest_escalation` 与行为账本 Ledger（P3b）集成

**接入点**：Ledger 的条目列表（`LedgerEntry` 列表）可直接作为 `suggest_escalation(history, ...)` 的 `history` 参数，前提是 `LedgerEntry` 含 `action` 和 `decision` 字段。

**提案**：在会话结束前或定期，将 Ledger 条目转换为 history 格式，调用 `suggest_escalation` 生成建议，通过 `LedgerEntryEvent`（或专用 `TrustSuggestionEvent`）推送给 TUI。TUI 展示建议时必须带上 `EscalationSuggestion.warning` 文案，等用户显式确认。

---

---

## 组件2：verify/strategy.py — Verify Strategy Generator（2026-06-11）

**交付文件：**
- `argos_agent/verify/strategy.py` — `VerifyStrategy`、`WorkspaceFacts`、`probe_workspace`、`generate`
- `tests/verify_strategy/__init__.py`
- `tests/verify_strategy/test_strategy.py` — 64 个测试全绿

---

### A. loop verify 阶段接入点（`verify_cmd is None` 分支）

**接入文件**：`argos_agent/core/loop.py`（禁区，集成阶段接线）

**接入位置**：loop verify 阶段，`verify_cmd is None → Verdict.unverifiable(...)` 的分支之前。

**推荐接线伪代码**：

```python
from argos_agent.verify.strategy import generate, probe_workspace, WorkspaceFacts

if verify_cmd is None:
    ws_path = runtime.current().workspace
    facts = probe_workspace(ws_path) if ws_path and ws_path.is_dir() else WorkspaceFacts()
    # capability manifest 的 verify_hint 字典透传（P2 能力注册表 verify_hint 字段）
    cap_hints = getattr(current_capability_manifest, "verify_hint", None) or {}
    strategies = generate(goal, workspace_facts=facts, capability_hints=cap_hints)
    first = strategies[0]

    if first.level == "L5":
        # 诚实退路：维持现有 NO_TEST 路径，行为 100% 不变
        return Verdict.unverifiable(
            detail=f"(无 verify_cmd；{first.rationale_human})",
            tampered=[], attempts=attempts,
        )
    elif first.level in ("L1", "L2") and first.cmd:
        # 有可执行策略 → 走 Verifier._run_verify（白名单 + verify_dir 隔离全保留）
        ok, detail, timed_out = self._run_verify(first.cmd)
        if timed_out:
            return Verdict.unverifiable(detail=f"[策略超时] {detail}", tampered=[], attempts=attempts)
        if ok:
            return Verdict.passed(detail=f"[{first.level}/{first.kind}] {detail}", verify_cmd=first.cmd, attempts=attempts)
        return Verdict.failed(detail=f"[{first.level}/{first.kind}] {detail}", verify_cmd=first.cmd, attempts=attempts)
    else:
        # L3（dom_assert）或 cmd=None → 本期降 unverifiable，P6 computer-use 配套后接入
        return Verdict.unverifiable(
            detail=f"(策略 {first.level}/{first.kind} 需外部执行器，本期诚实降 unverifiable)",
            tampered=[], attempts=attempts,
        )
```

**诚实保证**：
- `L5` 维持现有 `NO_TEST` 路径，行为 100% 不变。
- `L1/L2` + `cmd` 走真实 `_run_verify`（退出码是 ground truth）。
- `L3`（dom_assert）和 `cmd=None` 的策略降 `unverifiable`，绝不假装通过。
- 发送/购买/通知类 goal 在 `generate()` 内已硬编码直接返回 L5，loop 侧无需额外判断。

---

### B. WorkspaceFacts.declared_files 填充建议

`generate()` 已能从 goal 文本正则提取 `.json/.csv/.yaml` 等文件名。
如 loop/plan 阶段有更精确的产物声明（plan 中 agent 明确提到的文件），可在调用前构造：

```python
facts = WorkspaceFacts(
    **probe_workspace(ws_path).__dict__,
    declared_files=tuple(plan_declared_artifacts),  # 覆盖探测结果
)
```

---

### C. 与 P1 契约引擎 contracts.py 的对齐

`VerifyStrategy.kind` 与 `contracts.py` 未来 `Check` 类型的直接映射：

| VerifyStrategy.kind | 对应 Check 形态（P1 契约引擎方向） |
|---|---|
| `exit_code` | `ExitCodeCheck(cmd, expected_returncode=0)` |
| `artifact_exists` | `FileExistsCheck(path)` |
| `artifact_schema` | `FileSchemaCheck(path, schema_type="json"/"yaml")` |
| `content_assert` | `ContentAssertCheck(path, pattern)` |
| `dom_assert` | `DomAssertCheck(url, selector, expected_content)` |
| `evidence_trail` | —（无机检；`contracts.classify→"none"` 路径）|

集成时可将 `VerifyStrategy` 直接序列化为 Check 形态，复用契约引擎的检查执行器。
`capability_hints["pytest_cmd"]` 对应契约引擎中 `[C-pytest]` 覆盖约定。

---

### D. 红线（已写成代码 + 测试，集成后禁止退化）

1. **发送/购买/通知类** 匹配 `_SEND_PATTERN` → 只返回 L5，绝无 L1/L2/L3。
   - 覆盖 12 个 parametrize 用例 + 工作区有框架/hints 时仍 L5。
2. **fallback 永远存在**：`generate()` 最后必追加 L5，tuple 永远非空。
3. **probe_workspace 只读**：不创建/修改文件（`test_does_not_create_files` 锁定）。
4. **梯子单调不减**：L1 ≤ L2 ≤ L3 ≤ L5（`TestLadderOrdering` 锁定）。

---

*最后更新：2026-06-11，组件2 Verify Strategy Generator 追加。*
