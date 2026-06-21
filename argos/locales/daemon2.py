"""Daemon server / worker / client / conductor_supervisor / tui.daemon_source 用户可见文案。

key 命名空间:daemon.srv.*。
ZH 值 = 原始中文串(逐字照搬,保证既有测试 assert 仍通过)。
EN 值 = 对应的自然英文翻译。
"""
from __future__ import annotations

EN: dict[str, str] = {
    # server.py — no-key rejections
    "daemon.srv.no_key_run": (
        "daemon has no API key configured; cannot execute run. "
        "Run `argos setup` to configure a model key, then restart the daemon."
    ),
    "daemon.srv.no_key_run_confirm": (
        "daemon has no API key configured; cannot execute run. "
        "Run `argos setup` to configure a model key, then restart the daemon."
    ),
    # server.py — undo: ledger missing
    "daemon.srv.undo_no_ledger": (
        "this run has no behavior ledger (ledger not enabled or run has no side-effect actions)"
    ),
    # server.py — undo: bad entry_seq
    "daemon.srv.undo_entry_seq_must_be_int": "entry_seq must be an integer",
    # server.py — undo: already undone (run level)
    "daemon.srv.undo_already_done": "this run has already been undone; cannot undo again",
    # server.py — undo: nothing to undo (run level)
    "daemon.srv.undo_nothing_available": (
        "this run has no reversible operations (all operations are irreversible or already voided)"
    ),
    # server.py — undo: no snapshot (run level)
    "daemon.srv.undo_no_snapshot": (
        "no snapshot available (run start snapshot missing or path lost); cannot restore filesystem"
    ),
    # server.py — undo: snapshot file missing (run level)
    "daemon.srv.undo_snap_missing": "snapshot file does not exist: {snap_path}",
    # server.py — undo: no workspace (run level)
    "daemon.srv.undo_no_workspace_run": (
        "run has no workspace path; cannot restore filesystem"
    ),
    # server.py — undo: workspace missing (run level)
    "daemon.srv.undo_workspace_missing": "workspace does not exist: {workspace}",
    # server.py — undo: partial restore note
    "daemon.srv.undo_partial_note": (
        "partial restore: snapshot applied but some files failed to restore (see error_detail). "
        "Ledger marked."
    ),
    # server.py — undo: success note (run level)
    "daemon.srv.undo_done_note": (
        "restored file changes from run start "
        "(note: undo restores all file changes for the entire run, at run granularity)."
    ),
    # server.py — undo entry: entry not found
    "daemon.srv.undo_entry_not_found": "ledger has no entry with seq={entry_seq}",
    # server.py — undo entry: not a file entry
    "daemon.srv.undo_entry_not_file": (
        "entry seq={entry_seq} is not a file entry (undo_token has no 'file:' prefix)"
    ),
    # server.py — undo entry: not reversible
    "daemon.srv.undo_entry_not_reversible": (
        "entry seq={entry_seq} is not reversible (reversible={reversible!r}); cannot undo"
    ),
    # server.py — undo entry: already undone
    "daemon.srv.undo_entry_already_done": (
        "entry seq={entry_seq} has already been undone (undo_state=done); cannot undo again"
    ),
    # server.py — undo entry: no snapshot for file-level restore
    "daemon.srv.undo_entry_no_snapshot": (
        "cannot find run start snapshot path; cannot perform file-level restore"
    ),
    # server.py — undo entry: snapshot file missing (file level)
    "daemon.srv.undo_entry_snap_missing": "snapshot file does not exist: {snap_path}",
    # server.py — undo entry: no workspace (file level)
    "daemon.srv.undo_entry_no_workspace": (
        "run has no workspace path; cannot perform file-level restore"
    ),
    # server.py — undo entry: workspace missing (file level)
    "daemon.srv.undo_entry_workspace_missing": "workspace does not exist: {workspace}",
    # server.py — undo entry: restore failed
    "daemon.srv.undo_entry_restore_failed": "Error: file restore failed: {error_detail}",
    # server.py — undo entry: note for newly-created file (deletion)
    "daemon.srv.undo_entry_new_file_note": (
        "this file was created during the task; undo means deletion (deleted: {file_path})"
    ),
    # server.py — undo entry: note for restored file
    "daemon.srv.undo_entry_restored_note": "restored file: {file_path}",
    # server.py — conductor unavailable (confirm suggestion)
    "daemon.srv.conductor_unavailable_confirm": "conductor not started; cannot confirm suggestion",
    # server.py — conductor unavailable (dismiss suggestion)
    "daemon.srv.conductor_unavailable_dismiss": "conductor not started",
    # server.py — busy with suggestion pending (acquire slot)
    "daemon.srv.busy_suggestion_capacity": (
        "max_concurrent_runs_reached (max={max_concurrent}, "
        "active={active_count}); suggestion registered, please retry later"
    ),
    # server.py — busy with suggestion pending (timeout)
    "daemon.srv.busy_suggestion_timeout": (
        "max_concurrent_runs_reached (max={max_concurrent}); "
        "suggestion registered, please retry later"
    ),
    # server.py — narrate system prompt (Dream pipeline)
    "daemon.srv.dream_narrate_system": (
        "You are a skill documentation writer. Output text only, no code."
    ),
    # server.py — no key for Dream
    "daemon.srv.no_key_dream": (
        "daemon has no API key configured; cannot run Dream. "
        "Run `argos setup` to configure a model key, then restart the daemon."
    ),
    # server.py — Dream already running
    "daemon.srv.dream_busy": "a nightly consolidation is already running; please try again later.",
    # worker.py — approval timeout fail-closed
    "daemon.srv.approval_timeout": (
        "approval timed out (action={action!r}, run={run_id!r}, call_id={call_id!r}); "
        "rejected fail-closed."
    ),
    # worker.py — ledger summary: file modified with diff
    "daemon.srv.ledger_modified_diff": "modified {basename} (+{added}/-{removed})",
    # worker.py — ledger summary: file modified (no diff)
    "daemon.srv.ledger_modified": "modified {basename}",
    # client.py — daemon unresponsive timeout
    "daemon.srv.client_timeout": (
        "daemon unresponsive (exceeded {timeout:.0f}s): {method} {path} — may be busy or hung"
    ),
    # conductor_supervisor.py — dream standing order utterance
    "daemon.srv.dream_order_utterance": (
        "nightly consolidation: cross-run synthesis + memory tidy (Dream)"
    ),
    # tui/daemon_source.py — reconnect failure
    "daemon.srv.reconnect_failed": (
        "daemon connection lost (run={run_id!r}); "
        "reconnected {max_retries} times but still failing: {error}"
    ),
}

ZH: dict[str, str] = {
    # server.py — no-key rejections
    "daemon.srv.no_key_run": (
        "daemon 未配置 API key,无法执行 run。"
        "请运行 `argos setup` 配置模型 key 后重启 daemon。"
    ),
    "daemon.srv.no_key_run_confirm": (
        "daemon 未配置 API key，无法执行 run。请运行 `argos setup` 配置模型 key 后重启 daemon。"
    ),
    # server.py — undo: ledger missing
    "daemon.srv.undo_no_ledger": (
        "此 run 无行为账本(ledger 未启用或 run 无副作用动作)"
    ),
    # server.py — undo: bad entry_seq
    "daemon.srv.undo_entry_seq_must_be_int": "entry_seq 必须为整数",
    # server.py — undo: already undone (run level)
    "daemon.srv.undo_already_done": "此 run 已执行过 undo,不可重复撤销",
    # server.py — undo: nothing to undo (run level)
    "daemon.srv.undo_nothing_available": (
        "此 run 无可撤销的操作(所有操作均不可逆或已无效)"
    ),
    # server.py — undo: no snapshot (run level)
    "daemon.srv.undo_no_snapshot": (
        "无可用快照(run 起点快照不存在或路径丢失),无法执行文件系统还原"
    ),
    # server.py — undo: snapshot file missing (run level)
    "daemon.srv.undo_snap_missing": "快照文件不存在:{snap_path}",
    # server.py — undo: no workspace (run level)
    "daemon.srv.undo_no_workspace_run": (
        "run 无 workspace 路径,无法执行文件系统还原"
    ),
    # server.py — undo: workspace missing (run level)
    "daemon.srv.undo_workspace_missing": "workspace 不存在:{workspace}",
    # server.py — undo: partial restore note
    "daemon.srv.undo_partial_note": (
        "部分还原:快照已应用,但部分文件还原失败(见 error_detail)。账本已标记。"
    ),
    # server.py — undo: success note (run level)
    "daemon.srv.undo_done_note": (
        "已还原 run 起点的文件改动(注:撤销还原整个 run 的文件改动,粒度为 run 级)。"
    ),
    # server.py — undo entry: entry not found
    "daemon.srv.undo_entry_not_found": "账本中不存在 seq={entry_seq} 的条目",
    # server.py — undo entry: not a file entry
    "daemon.srv.undo_entry_not_file": (
        "seq={entry_seq} 的条目不是文件类条目(undo_token 无 file: 前缀)"
    ),
    # server.py — undo entry: not reversible
    "daemon.srv.undo_entry_not_reversible": (
        "seq={entry_seq} 的条目不可逆(reversible={reversible!r}),无法撤销"
    ),
    # server.py — undo entry: already undone
    "daemon.srv.undo_entry_already_done": (
        "seq={entry_seq} 的条目已经撤销(undo_state=done),不可重复撤销"
    ),
    # server.py — undo entry: no snapshot for file-level restore
    "daemon.srv.undo_entry_no_snapshot": (
        "无法找到 run 起点快照路径,无法执行文件粒度还原"
    ),
    # server.py — undo entry: snapshot file missing (file level)
    "daemon.srv.undo_entry_snap_missing": "快照文件不存在:{snap_path}",
    # server.py — undo entry: no workspace (file level)
    "daemon.srv.undo_entry_no_workspace": (
        "run 无 workspace 路径,无法执行文件粒度还原"
    ),
    # server.py — undo entry: workspace missing (file level)
    "daemon.srv.undo_entry_workspace_missing": "workspace 不存在:{workspace}",
    # server.py — undo entry: restore failed
    "daemon.srv.undo_entry_restore_failed": "错误:文件还原失败:{error_detail}",
    # server.py — undo entry: note for newly-created file (deletion)
    "daemon.srv.undo_entry_new_file_note": (
        "此文件是任务中新建的,撤销即删除(已删除:{file_path})"
    ),
    # server.py — undo entry: note for restored file
    "daemon.srv.undo_entry_restored_note": "已还原文件:{file_path}",
    # server.py — conductor unavailable (confirm suggestion)
    "daemon.srv.conductor_unavailable_confirm": "conductor 未启动，无法确认建议",
    # server.py — conductor unavailable (dismiss suggestion)
    "daemon.srv.conductor_unavailable_dismiss": "conductor 未启动",
    # server.py — busy with suggestion pending (acquire slot)
    "daemon.srv.busy_suggestion_capacity": (
        "max_concurrent_runs_reached (max={max_concurrent}, "
        "active={active_count})；建议已登记，请稍后重试确认"
    ),
    # server.py — busy with suggestion pending (timeout)
    "daemon.srv.busy_suggestion_timeout": (
        "max_concurrent_runs_reached (max={max_concurrent})；"
        "建议已登记，请稍后重试确认"
    ),
    # server.py — narrate system prompt (Dream pipeline)
    "daemon.srv.dream_narrate_system": (
        "你是技能文档撰写者。只输出文字,不输出代码。"
    ),
    # server.py — no key for Dream
    "daemon.srv.no_key_dream": (
        "daemon 未配置 API key，无法执行 Dream。请运行 `argos setup` 配置模型 key 后重启 daemon。"
    ),
    # server.py — Dream already running
    "daemon.srv.dream_busy": "已有一次夜间整合在跑，请稍后再试。",
    # worker.py — approval timeout fail-closed
    "daemon.srv.approval_timeout": (
        "审批超时(action={action!r},run={run_id!r},"
        "call_id={call_id!r}),已按 fail-closed 拒绝。"
    ),
    # worker.py — ledger summary: file modified with diff
    "daemon.srv.ledger_modified_diff": "修改了 {basename}(+{added}/-{removed})",
    # worker.py — ledger summary: file modified (no diff)
    "daemon.srv.ledger_modified": "修改了 {basename}",
    # client.py — daemon unresponsive timeout
    "daemon.srv.client_timeout": (
        "daemon 无响应(超过 {timeout:.0f}s):{method} {path} —— 可能繁忙或卡死"
    ),
    # conductor_supervisor.py — dream standing order utterance
    "daemon.srv.dream_order_utterance": (
        "夜间整合:跨 run 综合蒸馏 + 记忆整理(Dream)"
    ),
    # tui/daemon_source.py — reconnect failure
    "daemon.srv.reconnect_failed": (
        "daemon 连接断开（run={run_id!r}），"
        "重连 {max_retries} 次仍失败：{error}"
    ),
}
