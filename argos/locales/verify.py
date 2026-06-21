"""verify/* + skills_runtime/builtin/verify 用户可见文案 (Wave 3).

key 命名空间: verify.*
ZH 值 = 重构前的原始串 verbatim (一字不差)。
EN 值 = 语义对等的自然英文,以 "Error:" 开头对应 ZH "错误:" 开头。
"""
from __future__ import annotations

EN: dict[str, str] = {
    # ── verify/strategy.py ──────────────────────────────────────────────────

    # VerifyStrategy.__post_init__
    "verify.strategy.confidence_range": (
        "confidence must be in [0,1]; got {value!r}"
    ),
    "verify.strategy.l5_kind_required": (
        "L5-level strategy kind must be evidence_trail"
    ),

    # _l5_fallback
    "verify.strategy.l5_human": (
        "I cannot automatically verify whether this was done correctly — "
        "please take a look to confirm.{reason}"
        " The result has been recorded in the Ledger and can be reviewed at any time."
    ),

    # _l1_pytest
    "verify.strategy.l1_pytest_rationale": (
        "Run pytest ({cmd}); exit code 0 = all tests pass = task done correctly."
    ),
    "verify.strategy.l1_pytest_hint": (
        " From capability hint: {hint!r}."
    ),

    # _l1_cargo_test
    "verify.strategy.l1_cargo_rationale": (
        "Run cargo test; exit code 0 = all Rust tests pass = implementation correct."
    ),

    # _l1_npm_test
    "verify.strategy.l1_npm_rationale": (
        "Run npm test; exit code 0 = all JS/TS tests pass."
    ),

    # _l1_make_test
    "verify.strategy.l1_make_rationale": (
        "Run make test; Makefile test target passes = task complete."
    ),

    # _l1_go_test
    "verify.strategy.l1_go_rationale": (
        "Run go test ./...; exit code 0 = all Go tests pass."
    ),

    # _l2_artifact_exists
    "verify.strategy.l2_artifact_exists_rationale": (
        "Check that file {file_path!r} exists = agent actually produced the declared artifact."
    ),
    "verify.strategy.l2_artifact_exists_hint": (
        " From capability hints: {hints!r}."
    ),

    # _l2_artifact_exists_dir
    "verify.strategy.l2_artifact_exists_dir_rationale": (
        "Check that directory {dir_path!r} exists = agent actually created/organized the declared output directory."
    ),

    # _l2_content_assert_json
    "verify.strategy.l2_json_rationale": (
        "Validate that {file_path!r} is valid JSON — structured output correctly serialized."
    ),

    # _l2_content_assert_csv
    "verify.strategy.l2_csv_rationale": (
        "Validate that {file_path!r} is valid CSV — structured output is parseable."
    ),

    # _l3_dom_assert
    "verify.strategy.l3_dom_no_url": (
        "_l3_dom_assert: no url, should not be called"
    ),
    "verify.strategy.l3_dom_strong_rationale": (
        "At {url!r} confirm page text contains {expected_text!r} — "
        "declarative content assertion, machine-verifiable (strong evidence path)."
    ),
    "verify.strategy.l3_dom_weak_rationale": (
        "At {url!r} check DOM selector {selector!r} related content — "
        "only a weak text hint, no structural DOM verification channel; "
        "result is at most unverifiable (not passed). "
        "For machine-verifiable assertion, provide expected_text in propose_dom_verify()."
    ),

    # generate() — send-pattern L5 reason
    "verify.strategy.send_l5_reason": (
        "Send/notify/purchase task: transport-layer success does not equal task correctness"
        " (wrong recipient/content can still return 200)."
    ),

    # generate() — structured output fallback rationale strings
    "verify.strategy.json_output_rationale": (
        "Goal contains JSON output signal; validating output file is valid JSON."
    ),
    "verify.strategy.csv_output_rationale": (
        "Goal contains CSV output signal; validating output file is parseable."
    ),

    # ── verify/dom_probe.py ────────────────────────────────────────────────

    "verify.dom_probe.no_browser": (
        "DomProber not connected to a browser controller (browser=None)."
    ),
    "verify.dom_probe.exception": (
        "DOM probe exception: {exc_type}: {exc}"
    ),
    "verify.dom_probe.nav_failed": (
        "Navigation failed: {result}"
    ),
    "verify.dom_probe.snapshot_failed": (
        "Page snapshot failed: {result}"
    ),
    "verify.dom_probe.weak_evidence": (
        "Only a weak text hint (selector {selector!r} → hint {hint!r}), "
        "no structural DOM verification channel, cannot machine-verify element truly exists. "
        "For machine verification, provide explicit expected_text in propose_dom_verify()."
    ),

    # ── verify/gui_probe.py ────────────────────────────────────────────────

    "verify.gui_probe.no_expected_text": (
        "expected_text not provided — no machine-verifiable criterion for GUI state, cannot determine (unverifiable)."
    ),
    "verify.gui_probe.no_executor": (
        "GuiProber not connected to ComputerExecutor (executor=None)."
    ),
    "verify.gui_probe.screenshot_failed": (
        "Screenshot failed, cannot machine-verify GUI state: {detail}"
    ),
    "verify.gui_probe.ocr_unavailable": (
        "OCR unavailable (pytesseract / tesseract not installed) — GUI state cannot be machine-verified → unverifiable."
    ),
    "verify.gui_probe.exception": (
        "GUI probe exception: {exc_type}: {exc}"
    ),

    # ── verify/self_test.py ───────────────────────────────────────────────

    "verify.self_test.workspace_missing": (
        "workspace does not exist: {workspace}"
    ),
    "verify.self_test.canary_failed": (
        "canary failed: running {cmd!r} on empty workspace also exits 0 — "
        "test does not depend on agent output, cannot distinguish 'done correctly vs not done' "
        "→ discarding, falling back to unverifiable"
    ),

    # ── skills_runtime/builtin/verify.py ─────────────────────────────────

    "verify.skill.self_verified_summary": (
        "/verify · <1ms · self_verified (weaker: system-generated test; not user-level verify)\nverify_cmd: {cmd}"
    ),
}

ZH: dict[str, str] = {
    # ── verify/strategy.py ──────────────────────────────────────────────────

    "verify.strategy.confidence_range": (
        "confidence 必须在 [0,1] 区间，实际值：{value!r}"
    ),
    "verify.strategy.l5_kind_required": (
        "L5 级策略 kind 必须是 evidence_trail"
    ),

    # _l5_fallback
    "verify.strategy.l5_human": (
        "这件事我没法自动验证对错，需要你看一眼确认。{reason}"
        "结果已记录在 Ledger 中，可随时复盘。"
    ),

    # _l1_pytest
    "verify.strategy.l1_pytest_rationale": (
        "运行 pytest（{cmd}）；退出码 0 = 所有测试通过 = 任务做对了。"
    ),
    "verify.strategy.l1_pytest_hint": (
        " 来自 capability hint: {hint!r}。"
    ),

    # _l1_cargo_test
    "verify.strategy.l1_cargo_rationale": (
        "运行 cargo test；退出码 0 = Rust 测试全过 = 实现正确。"
    ),

    # _l1_npm_test
    "verify.strategy.l1_npm_rationale": (
        "运行 npm test；退出码 0 = JS/TS 测试全过。"
    ),

    # _l1_make_test
    "verify.strategy.l1_make_rationale": (
        "运行 make test；Makefile 定义的测试目标通过 = 任务完成。"
    ),

    # _l1_go_test
    "verify.strategy.l1_go_rationale": (
        "运行 go test ./...；退出码 0 = Go 测试全过。"
    ),

    # _l2_artifact_exists
    "verify.strategy.l2_artifact_exists_rationale": (
        "检查文件 {file_path!r} 存在 = agent 确实生成了声明的产物。"
    ),
    "verify.strategy.l2_artifact_exists_hint": (
        " 来自 capability hints: {hints!r}。"
    ),

    # _l2_artifact_exists_dir
    "verify.strategy.l2_artifact_exists_dir_rationale": (
        "检查目录 {dir_path!r} 存在 = agent 确实创建/整理了声明的输出目录。"
    ),

    # _l2_content_assert_json
    "verify.strategy.l2_json_rationale": (
        "验证 {file_path!r} 是合法 JSON —— 结构化输出正确序列化。"
    ),

    # _l2_content_assert_csv
    "verify.strategy.l2_csv_rationale": (
        "验证 {file_path!r} 是合法 CSV —— 结构化输出可解析。"
    ),

    # _l3_dom_assert
    "verify.strategy.l3_dom_no_url": (
        "_l3_dom_assert: 无 url，不应调用"
    ),
    "verify.strategy.l3_dom_strong_rationale": (
        "在 {url!r} 确认页面文本包含 {expected_text!r} —— "
        "声明式内容断言，可机检判定（强证据路径）。"
    ),
    "verify.strategy.l3_dom_weak_rationale": (
        "在 {url!r} 检查 DOM 选择器 {selector!r} 相关内容 —— "
        "仅有文本弱提示，无结构性 DOM 校验通道；"
        "结果最高为 unverifiable（非 passed）。"
        "如需机检断言，请在 propose_dom_verify() 中提供 expected_text。"
    ),

    # generate() — send-pattern L5 reason
    "verify.strategy.send_l5_reason": (
        "发送/通知/购买类任务：传输层返回成功不等于任务内容正确"
        "（收错人/发错内容仍可能 200）。"
    ),

    # generate() — structured output fallback rationale strings
    "verify.strategy.json_output_rationale": (
        "目标含 JSON 输出信号，验证输出文件是合法 JSON。"
    ),
    "verify.strategy.csv_output_rationale": (
        "目标含 CSV 输出信号，验证输出文件可解析。"
    ),

    # ── verify/dom_probe.py ────────────────────────────────────────────────

    "verify.dom_probe.no_browser": (
        "DomProber 未接入浏览器控制器（browser=None）。"
    ),
    "verify.dom_probe.exception": (
        "DOM 探针异常：{exc_type}: {exc}"
    ),
    "verify.dom_probe.nav_failed": (
        "导航失败：{result}"
    ),
    "verify.dom_probe.snapshot_failed": (
        "页面快照失败：{result}"
    ),
    "verify.dom_probe.weak_evidence": (
        "仅有文本弱提示（选择器 {selector!r} → 提示 {hint!r}），"
        "无结构性 DOM 校验通道，无法机检判定元素是否真实存在。"
        "如需机检验证，请在 propose_dom_verify() 中提供显式 expected_text。"
    ),

    # ── verify/gui_probe.py ────────────────────────────────────────────────

    "verify.gui_probe.no_expected_text": (
        "未提供 expected_text —— GUI 状态无机检判据,无法判定(unverifiable)。"
    ),
    "verify.gui_probe.no_executor": (
        "GuiProber 未接入 ComputerExecutor(executor=None)。"
    ),
    "verify.gui_probe.screenshot_failed": (
        "截图失败,无法机检 GUI 状态:{detail}"
    ),
    "verify.gui_probe.ocr_unavailable": (
        "OCR 不可用(未装 pytesseract / tesseract)—— GUI 状态无法机检判定 → unverifiable。"
    ),
    "verify.gui_probe.exception": (
        "GUI 探针异常:{exc_type}: {exc}"
    ),

    # ── verify/self_test.py ───────────────────────────────────────────────

    "verify.self_test.workspace_missing": (
        "workspace 不存在:{workspace}"
    ),
    "verify.self_test.canary_failed": (
        "canary 失败:在空 workspace 上跑 {cmd!r} 也 exit 0 —— 测试不依赖 "
        "agent 产出,无法区分'做对 vs 没做' → 丢弃,回退 unverifiable"
    ),

    # ── skills_runtime/builtin/verify.py ─────────────────────────────────

    "verify.skill.self_verified_summary": (
        "/verify · <1ms · self_verified (较弱:系统自造测试;非用户级 verify)\nverify_cmd: {cmd}"
    ),
}
