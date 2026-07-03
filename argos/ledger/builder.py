from __future__ import annotations

from argos.ledger.entry import LedgerEntry, Reversible, UndoState
from argos.ledger.summary import summarize

_FS_REVERSIBLE_ACTIONS = frozenset({
    "write_file", "create_file", "edit_file", "patch_file",
    "delete_file", "mkdir", "makedirs",
})

_IRREVERSIBLE_ACTIONS = frozenset({
    "web_fetch", "http_get", "http_post", "fetch", "post",
    "web_search",
    "browser_navigate", "navigate",
    "browser_click", "click",
    "browser_fill", "fill", "type",
    "browser_screenshot", "screenshot",
    "computer_screenshot",
    "computer_click",
    "computer_double_click",
    "computer_type_text",
    "computer_key",
    "computer_scroll",
    "computer_open_app",
})


def _classify_reversible(action: str, undo_token: str | None) -> Reversible:
    a = action.lower()
    if a in _FS_REVERSIBLE_ACTIONS:
        return "yes" if undo_token else "unknown"
    if a in _IRREVERSIBLE_ACTIONS:
        return "no"
    return "unknown"


def _classify_undo_state(reversible: Reversible) -> UndoState:
    if reversible == "yes":
        return "available"
    return "impossible"


def build_entry(
    *,
    receipt,          # argos.tools.receipts.Receipt
    run_id: str,
    seq: int,
    args: dict | None = None,
    undo_token: str | None = None,
) -> LedgerEntry:
    if args is None:
        args = {}

    action = receipt.action
    summary = summarize(action, args)
    reversible = _classify_reversible(action, undo_token)
    undo_state = _classify_undo_state(reversible)

    a = action.lower()
    if a in _IRREVERSIBLE_ACTIONS:
        risk = "high"
    elif a in ("run_shell", "run_command", "bash", "shell", "exec"):
        risk = "medium"
    else:
        risk = "low"

    sig_truncated = (receipt.sig or "")[:16]

    return LedgerEntry(
        ts=float(receipt.ts),
        run_id=run_id,
        seq=seq,
        action=action,
        summary_human=summary,
        risk=risk,
        reversible=reversible,
        undo_token=undo_token if reversible == "yes" else None,
        receipt_sig=sig_truncated,
        undo_state=undo_state,
    )
