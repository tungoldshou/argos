"""Core loop / harness 用户可见文案。

key 命名空间:loop.* / verdict_detail.*。
仅覆盖 loop.py 和 harness.py 中渲染给用户的串;内部日志/注释/系统提示词不走此目录。

ZH 值 = 当前代码里的原始串(verbatim,一字不差)。
EN 值 = 语义对等的自然英文,口吻与 README 一致(冷静、精准)。
"""
from __future__ import annotations

# ── 429 / 网络错误 ────────────────────────────────────────────────────────────
# loop.py run() 顶层兜底:友好可操作提示(原始错误截 120/200 字拼入)。

EN: dict[str, str] = {
    # ── todos summary header ─────────────────────────────────────────────────
    "loop.todos.header": "[Argos Task List {done}/{total}]",

    # ── DOM probe ────────────────────────────────────────────────────────────
    "loop.dom_probe.thread_error": "DOM probe thread error: {result_type}: {exc}",
    "loop.dom_probe.error_detail": "[L3 DOM probe] {rationale}\nProbe error (unverifiable): {error}",
    "loop.dom_probe.no_excerpt": "(no text excerpt)",
    "loop.dom_probe.found_detail": "[L3 DOM probe] {rationale}\nElement {selector!r} found. Excerpt: {excerpt}",
    "loop.dom_probe.not_found_detail": (
        "[L3 DOM probe] {rationale}\n"
        "Element {selector!r} not found on page (or expected_text not matched). "
        "Check whether the page change has taken effect, or verify your selector."
    ),

    # ── GUI probe ────────────────────────────────────────────────────────────
    "loop.gui_probe.thread_error": "GUI probe thread error: {exc_type}: {exc}",
    "loop.gui_probe.unverifiable_detail": "[GUI probe] On-screen text assertion cannot be machine-checked (unverifiable): {error}",
    "loop.gui_probe.no_excerpt": "(no excerpt)",
    "loop.gui_probe.found_detail": "[GUI probe] On-screen confirmed: {expected_text!r} present. OCR excerpt: {excerpt}",
    "loop.gui_probe.not_found_detail": (
        "[GUI probe] {expected_text!r} not found on screen (OCR miss). "
        "Check whether the GUI action has taken effect."
    ),

    # ── vision unsupported ───────────────────────────────────────────────────
    "loop.vision.unsupported": (
        "Current model {model_name!r} cannot process images. "
        "Switch to a vision-capable model, "
        "or set a multimodal override for this profile in config."
    ),

    # ── screenshot pixel note (appended to feedback message) ─────────────────
    "loop.screenshot.pixel_note": (
        "\n[Screenshot {w}x{h} px; use this image's pixel coordinates for click targets]"
    ),

    # ── verify gate rejection messages (fed back to model) ───────────────────
    "loop.verify_gate.fstring_rejected": (
        "[Argos Verify Gate] `{cmd}` looks like an f-string (contains {{}} placeholders). "
        "The host runs verification independently and cannot evaluate f-strings with your sandbox "
        "variables. Use a plain string literal with the full command "
        "(e.g. propose_verify('pytest -q tests/test_x.py'))."
    ),
    "loop.verify_gate.bridge_locked": (
        "[Argos Verify Gate] You proposed verify command `{cmd}`, but verification for this task "
        "is already configured by the bridge (it will run automatically — no need to propose again). "
        "Continue your code changes; the bridge will run verification independently at the end and "
        "give a three-state verdict based on exit code."
    ),
    "loop.verify_gate.trivial_rejected": (
        "[Argos Verify Gate] `{cmd}` is not a valid verification command "
        "(it always passes and verifies nothing). "
        "propose_verify requires a real test/compile/lint command that can determine correctness "
        "(e.g. pytest, cargo test, ruff, mypy, tsc). "
        "If this project genuinely has no machine-checkable verification, "
        "skip the declaration and explain the situation instead."
    ),

    # ── hook rejection ───────────────────────────────────────────────────────
    "loop.hook.no_reason": "(no reason)",
    "loop.hook.pretooluse_rejected": (
        "[Argos Hook] PreToolUse hook rejected the tool call:\n"
        "{reason}\n"
        "Adjust your approach and try again, or communicate with the user."
    ),

    # ── workflow notes ───────────────────────────────────────────────────────
    "loop.workflow.not_enabled": (
        "[note] Workflows are disabled (ARGOS_WORKFLOWS=0); "
        "your propose_workflow will not be executed. "
        "Complete the task in a single thread directly, without waiting for it to run."
    ),

    # ── no-code nudge (model claimed done without executing anything) ─────────
    "loop.nudge.no_code_action": (
        "You stopped without producing any ```python code action. "
        "If you need to do something, output a code block and actually execute it; "
        "if you confirm no action is needed to answer, give your final reply directly "
        "(I will wrap up accordingly)."
    ),

    # ── verify nudge (code changed but no verify declared) ───────────────────
    "loop.nudge.verify_missing": (
        "You made code changes but did not declare a verification command. "
        "Use `propose_verify('<test/compile/lint command>')` to declare how to "
        "machine-check this change (e.g. pytest, cargo test, ruff, mypy, tsc); "
        "I will run it independently and use the exit code as the verdict. "
        "If this project genuinely has no machine-checkable verification, "
        "just explain that (I will honestly label it 'unverified' at wrap-up)."
    ),

    # ── unverifiable autonomy gate ───────────────────────────────────────────
    "loop.verify_gate.unverifiable_needs_confirmation": (
        "verify untrustworthy, needs human confirmation: {reason}"
    ),

    # ── user rejected unverifiable bounce ────────────────────────────────────
    "loop.verify_gate.user_rejected_bounce": (
        "[Argos Verify Gate] Verification `{verify_cmd}` is untrustworthy, "
        "user declined to continue: {detail}. Please fix and try again."
    ),

    # ── verify gate bounce (failed / unverifiable with cmd set) ──────────────
    "loop.verify_gate.bounce": (
        "[Argos Verify Gate] You claimed completion, but verification `{verify_cmd}` "
        "did not pass / is untrustworthy:\n{detail}\n"
        "Use tools to locate and fix the issue, then claim completion again."
    ),

    # ── workflow engine / spec / result ──────────────────────────────────────
    "loop.workflow.no_engine": "[Workflow engine not connected; cannot orchestrate. Continue in single-thread mode.]",
    "loop.workflow.spec_invalid": "[Workflow rejected: invalid spec — {error}. Fix it or continue in single-thread mode.]",
    "loop.workflow.rejected": "[Workflow rejected; continuing in single-thread mode.]",
    "loop.workflow.no_result": "(no workflow result)",
    "loop.workflow.result_summary": "[Workflow \"{name}\" result]\n{synthesis}",
    "loop.workflow.result_notes": "\nNotes: {notes}",

    # ── plan mode timeout / decision error ────────────────────────────────────
    "loop.plan.timeout": (
        "plan decision timed out ({timeout:.0f}s): client disconnected or unresponsive, "
        "run cancelled (fail-closed)."
    ),
    "loop.plan.decision_none": (
        "plan decision error: _plan_decision is None (internal error), "
        "run cancelled (fail-closed)."
    ),

    # ── exec feedback ────────────────────────────────────────────────────────
    "loop.exec.exception": "[Execution error]\n{exc}",
    "loop.exec.value_repr": "\n[Return value] {value_repr}",
    "loop.exec.result": "[Execution result]\n{out}",
    "loop.exec.no_output": "[Execution complete, no output]",

    # 429 rate-limit
    "loop.error.rate_limit": (
        "Rate limited (429): current key QPS is insufficient. "
        "Try again in a few seconds, configure multiple comma-separated keys for rotation "
        "in config, or reduce best-of-N concurrency. "
        "(raw: {raw_msg})"
    ),
    # Network / DNS failure
    "loop.error.network": (
        "Cannot reach model endpoint (network or DNS issue): "
        "check your connection, or verify base_url in config. "
        "raw: {raw_msg}"
    ),

    # ── report_note values ───────────────────────────────────────────────────
    "loop.report_note.no_test": "unverified (no test command)",
    "loop.report_note.no_test_compacted": (
        "unverified (no test command)"
        "; context was compacted (lossy) — no test command to re-verify progress"
    ),
    "loop.report_note.compacted_reverified": (
        "context was compacted (lossy); verification re-run confirmed passing"
    ),
    "loop.report_note.unverifiable_user_confirmed": (
        "verification untrustworthy ({verdict_status}); user confirmed to continue"
    ),
    "loop.report_note.unverifiable_user_confirmed_compacted": (
        "verification untrustworthy ({verdict_status}); user confirmed to continue"
        "; context was compacted (lossy)"
    ),

    # ── persisted placeholder (written to DB when final assistant text is empty)
    "loop.persisted.escalated": "(run ended: verification failed, escalated)",
    "loop.persisted.with_note": "(run complete: {report_note})",
    "loop.persisted.done": "(run complete)",

    # ── visible completion lines (yielded as TokenDelta to TUI / transcript) ─
    "loop.done.escalated": (
        "⚠️ Could not pass verification within the allowed rounds"
        " — escalated as reported above.\n"
    ),
    "loop.done.with_note": "✅ Done. {report_note}\n",
    "loop.done.verified": "✅ Done, verification passed (all tests/checks green).\n",
    "loop.done.self_verified": (
        "\U0001f7e1 Done, self-verified (system-generated test; not user-level verify).\n"
    ),
    "loop.done.verdict_bad": (
        "⚠️ Run ended: verification failed or untrustworthy (see above).\n"
    ),
    "loop.done.generic": "✅ Run complete.\n",

    # ── harness escalation reason ─────────────────────────────────────────────
    "verdict_detail.escalation_reason": (
        "Tried {attempt} time(s) but could not pass verification "
        "for `{verify_cmd}` (bounce limit: {max_rounds} rounds)"
        " — I'm stuck and need your guidance; not pretending to be done."
    ),
}

ZH: dict[str, str] = {
    # ── todos summary header ─────────────────────────────────────────────────
    "loop.todos.header": "[Argos 任务清单 {done}/{total}]",

    # ── DOM 探针 ─────────────────────────────────────────────────────────────
    "loop.dom_probe.thread_error": "DOM 探针线程异常：{result_type}: {exc}",
    "loop.dom_probe.error_detail": "[L3 DOM 探针] {rationale}\n探针错误（unverifiable）：{error}",
    "loop.dom_probe.no_excerpt": "（无文本摘录）",
    "loop.dom_probe.found_detail": "[L3 DOM 探针] {rationale}\n元素 {selector!r} 存在。摘录：{excerpt}",
    "loop.dom_probe.not_found_detail": (
        "[L3 DOM 探针] {rationale}\n"
        "元素 {selector!r} 在页面中未找到（或 expected_text 不匹配）。"
        "请检查网页改动是否已生效，或检查选择器是否正确。"
    ),

    # ── GUI 探针 ─────────────────────────────────────────────────────────────
    "loop.gui_probe.thread_error": "GUI 探针线程异常:{exc_type}: {exc}",
    "loop.gui_probe.unverifiable_detail": "[GUI 探针] 屏上文本断言无法机检(unverifiable):{error}",
    "loop.gui_probe.no_excerpt": "(无摘录)",
    "loop.gui_probe.found_detail": "[GUI 探针] 屏上确认含 {expected_text!r}。OCR 摘录:{excerpt}",
    "loop.gui_probe.not_found_detail": (
        "[GUI 探针] 屏上未找到 {expected_text!r}(OCR 未命中)。"
        "请检查 GUI 操作是否已生效。"
    ),

    # ── 视觉能力不支持 ────────────────────────────────────────────────────────
    "loop.vision.unsupported": (
        "当前模型 {model_name!r} 看不了图。请换一个支持视觉的模型,"
        "或在 config 给该 profile 设 multimodal override。"
    ),

    # ── 截图像素注记 ──────────────────────────────────────────────────────────
    "loop.screenshot.pixel_note": (
        "\n[截图 {w}x{h} 像素;点击坐标请用这张图的像素坐标]"
    ),

    # ── 验证门拒绝回灌 ────────────────────────────────────────────────────────
    "loop.verify_gate.fstring_rejected": (
        "[Argos 验证门] `{cmd}` 像是 f-string(含 {{}} 占位)。host 侧"
        "独立跑验证、拿不到你沙箱里的变量,无法求值 f-string。请改用普通字符串字面量、"
        "填入完整命令(如 propose_verify('pytest -q tests/test_x.py'))。"
    ),
    "loop.verify_gate.bridge_locked": (
        "[Argos 验证门] 你提出 verify 命令 `{cmd}`,但本次任务已由桥接"
        "统一配置了验证(会自动跑、不需要你再 propose)。请继续完成你手上的代码改动,不要"
        "再次声明 verify —— 收尾时桥接会独立跑验证并按退出码给三态裁决。"
    ),
    "loop.verify_gate.trivial_rejected": (
        "[Argos 验证门] `{cmd}` 不是有效的验证命令(它永远通过、什么都不验证)。"
        "propose_verify 需要真正能判定对错的测试/编译/lint 命令(如 pytest、cargo test、"
        "ruff、mypy、tsc)。若此项目确实无可机检验证,就别声明、直接说明情况。"
    ),

    # ── hook 拒绝 ─────────────────────────────────────────────────────────────
    "loop.hook.no_reason": "(无理由)",
    "loop.hook.pretooluse_rejected": (
        "[Argos Hook] PreToolUse 工具调用被 hook 拒绝:\n"
        "{reason}\n"
        "请调整方案后再试,或与用户沟通。"
    ),

    # ── 工作流注记 ────────────────────────────────────────────────────────────
    "loop.workflow.not_enabled": (
        "[note] 工作流已禁用(ARGOS_WORKFLOWS=0),你的 propose_workflow 不会被执行;"
        "请直接单线程完成任务,不要等待它运行。"
    ),

    # ── 无代码块催促 ──────────────────────────────────────────────────────────
    "loop.nudge.no_code_action": (
        "你还没有产出任何 ```python 代码动作就停了。如果要做事,请输出代码块真正执行;"
        "如果确认无需任何动作即可回答,请直接给出最终答复(我会据此收尾)。"
    ),

    # ── 验证催促 ──────────────────────────────────────────────────────────────
    "loop.nudge.verify_missing": (
        "你改动了代码但没有声明验证命令。请用 `propose_verify('<测试/编译/lint 命令>')` "
        "声明如何机检本次改动(如 pytest、cargo test、ruff、mypy、tsc),我会独立运行它以退出码为准。"
        "若此项目确实无可机检验证,直接说明即可(我会如实标'未机检验证'收尾)。"
    ),

    # ── 不可信自主门 ──────────────────────────────────────────────────────────
    "loop.verify_gate.unverifiable_needs_confirmation": (
        "verify 不可信,需人确认:{reason}"
    ),

    # ── 用户拒绝不可信验证 ────────────────────────────────────────────────────
    "loop.verify_gate.user_rejected_bounce": (
        "[Argos 验证门] 验证 `{verify_cmd}` 不可信,"
        "用户拒绝继续: {detail}。请修复后再试。"
    ),

    # ── 验证门 bounce（failed / 配了 cmd 却 unverifiable）────────────────────
    "loop.verify_gate.bounce": (
        "[Argos 验证门] 你声称完成,但验证 `{verify_cmd}` 未通过/不可信:\n"
        "{detail}\n"
        "请用工具定位并修复,改完再说完成。"
    ),

    # ── 工作流引擎 / 规格 / 结果 ──────────────────────────────────────────────
    "loop.workflow.no_engine": "[工作流引擎未接入,无法编排;请单线程继续。]",
    "loop.workflow.spec_invalid": "[工作流被拒:规格非法 — {error}。请修正或单线程继续。]",
    "loop.workflow.rejected": "[工作流被拒,单线程继续。]",
    "loop.workflow.no_result": "(工作流无结果)",
    "loop.workflow.result_summary": "[工作流「{name}」结果]\n{synthesis}",
    "loop.workflow.result_notes": "\n注记:{notes}",

    # ── plan 决策超时 / None ──────────────────────────────────────────────────
    "loop.plan.timeout": (
        "plan 决策超时({timeout:.0f}s):客户端断连或无响应,"
        " run 已取消(fail-closed)。"
    ),
    "loop.plan.decision_none": (
        "plan 决策异常:_plan_decision 为 None(内部错误),run 已取消(fail-closed)。"
    ),

    # ── exec 反馈 ─────────────────────────────────────────────────────────────
    "loop.exec.exception": "[执行异常]\n{exc}",
    "loop.exec.value_repr": "\n[返回值] {value_repr}",
    "loop.exec.result": "[执行结果]\n{out}",
    "loop.exec.no_output": "[执行完成,无输出]",

    # 429 rate-limit(verbatim from loop.py lines 907-910)
    "loop.error.rate_limit": (
        "模型限流(429):当前 key QPS 不足。"
        "建议:等几秒后重试,或在 config 里配多个逗号分隔的 key 轮换,或降低 best-of-N 并发。"
        "(原始:{raw_msg})"
    ),
    # Network / DNS(verbatim from loop.py lines 915-918)
    "loop.error.network": (
        "连不上模型端点(网络或 DNS 问题):"
        "请检查网络连接,或确认 config 里的 base_url 是否正确。"
        "原始:{raw_msg}"
    ),

    # ── report_note 值 ───────────────────────────────────────────────────────
    # verbatim from loop.py line 1818
    "loop.report_note.no_test": "未机检验证 (no test command)",
    # verbatim from loop.py lines 1818+1820 (concatenated)
    "loop.report_note.no_test_compacted": (
        "未机检验证 (no test command)"
        "；上下文经过压缩(有损),无机检命令可重验确认进度"
    ),
    # verbatim from loop.py line 1812
    "loop.report_note.compacted_reverified": "上下文经过压缩(有损),已重跑验证确认通过",
    # verbatim from loop.py lines 1768-1769
    "loop.report_note.unverifiable_user_confirmed": (
        "verify 不可信({verdict_status}),用户已确认继续"
    ),
    # verbatim from loop.py lines 1768-1772 (compacted branch)
    "loop.report_note.unverifiable_user_confirmed_compacted": (
        "verify 不可信({verdict_status}),用户已确认继续;上下文经过压缩(有损)"
    ),

    # ── persisted 占位 ────────────────────────────────────────────────────────
    # verbatim from loop.py line 1906
    "loop.persisted.escalated": "(本轮结束:未通过验证,已上报)",
    # verbatim from loop.py line 1908 (note: {report_note} is the placeholder)
    "loop.persisted.with_note": "(本轮完成:{report_note})",
    # verbatim from loop.py line 1910
    "loop.persisted.done": "(本轮完成)",

    # ── 可见完成行 ─────────────────────────────────────────────────────────────
    # verbatim from loop.py line 1926
    "loop.done.escalated": "⚠️ 未能在限定轮内通过验证,已如实上报(见上方升级提示)。\n",
    # verbatim from loop.py line 1928
    "loop.done.with_note": "✅ 完成。{report_note}\n",
    # verbatim from loop.py line 1932
    "loop.done.verified": "✅ 完成,验证通过(测试/检查全绿)。\n",
    # verbatim from loop.py line 1937
    "loop.done.self_verified": "🟡 完成,自验证通过(系统自造测试;非用户级 verify)。\n",
    # verbatim from loop.py line 1939
    "loop.done.verdict_bad": "⚠️ 本轮结束:验证未通过/不可信(详见上)。\n",
    # verbatim from loop.py line 1941
    "loop.done.generic": "✅ 本轮结束。\n",

    # ── harness escalation reason(verbatim from harness.py lines 116-118) ────
    "verdict_detail.escalation_reason": (
        "已尝试 {attempt} 次仍无法通过验证 "
        "`{verify_cmd}`(bounce 上限 {max_rounds} 轮)"
        " —— 我没搞定,需要你介入指路,不会假装完成。"
    ),
}
