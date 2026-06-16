"""build_entry — 从 Receipt + 上下文构建 LedgerEntry(spec §6 信任面)。

可逆性判定规则(确定性,不调模型):
  reversible=yes    write_file / edit_file / create_file / patch_file / mkdir / delete_file
                    (文件系统类,存在 run 级快照可整体还原)
  reversible=no     网络请求(web_fetch / http_post / web_search)
                    浏览器动作(browser_* / navigate / click / fill)
                    delete_file 如果 undo_token 为 None 时降 unknown
                    (已发出的请求无法撤回;GUI 操作无法整体回滚 —— 诚实协议)
  reversible=unknown 其余:shell 命令 / 未知动作

说明:
  - v1 undo_token 是 run 级 RunSnapshot tar 路径,条目级 undo 本期登记 token 但
    执行走 run 级还原。诚实标注:"撤销将还原整个 run 的文件改动"。
  - 不可逆动作 undo_state=impossible。可逆 undo_state=available(未撤销)。
"""
from __future__ import annotations

from argos.ledger.entry import LedgerEntry, Reversible, UndoState
from argos.ledger.summary import summarize

# 文件系统类动作 = 可通过快照整体还原
_FS_REVERSIBLE_ACTIONS = frozenset({
    "write_file", "create_file", "edit_file", "patch_file",
    "delete_file", "mkdir", "makedirs",
})

# 网络/GUI 类动作 = 不可逆(已发出的请求 / 浏览器操作 / OS 级控制无法整体回滚)
_IRREVERSIBLE_ACTIONS = frozenset({
    "web_fetch", "http_get", "http_post", "fetch", "post",
    "web_search",
    "browser_navigate", "navigate",
    "browser_click", "click",
    "browser_fill", "fill", "type",
    "browser_screenshot", "screenshot",
    # OS 级计算机控制(P6a §10):屏幕/鼠标动作不可撤销 —— 诚实协议,不假装可回滚。
    "computer_screenshot",
    "computer_click",
    "computer_double_click",
    "computer_type_text",
    "computer_key",
    "computer_scroll",
    "computer_open_app",
})


def _classify_reversible(action: str, undo_token: str | None) -> Reversible:
    """从 action 名 + undo_token 可用性推断可逆性三态。"""
    a = action.lower()
    if a in _FS_REVERSIBLE_ACTIONS:
        # 文件系统操作:有快照 = yes;无快照 = unknown(诚实:快照丢失时不能承诺可撤)
        return "yes" if undo_token else "unknown"
    if a in _IRREVERSIBLE_ACTIONS:
        return "no"
    # Shell / 未知:保守 unknown
    return "unknown"


def _classify_undo_state(reversible: Reversible) -> UndoState:
    """从可逆性推断初始 undo_state。"""
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
    """从 Receipt + 上下文构建 LedgerEntry。

    Args:
        receipt:    已签名的 Receipt dataclass(broker 返回)
        run_id:     所属 run id(12 hex)
        seq:        本 run 内顺序号(从 1 起)
        args:       动作原始参数 dict(用于人话生成);None 时用空 dict
        undo_token: run 级快照 tar 路径(str);无快照则 None

    Returns:
        LedgerEntry(frozen)
    """
    if args is None:
        args = {}

    action = receipt.action
    summary = summarize(action, args)
    reversible = _classify_reversible(action, undo_token)
    undo_state = _classify_undo_state(reversible)

    # 从 risk 推断:Receipt 本身不携带 risk(是回执而非审批请求);
    # v1 按动作分类简单推断:网络/浏览器=high,shell=medium,文件读写=low
    a = action.lower()
    if a in _IRREVERSIBLE_ACTIONS:
        risk = "high"
    elif a in ("run_shell", "run_command", "bash", "shell", "exec"):
        risk = "medium"
    else:
        risk = "low"

    # receipt_sig 截断前 16 字符(供审计;不存全文)
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
