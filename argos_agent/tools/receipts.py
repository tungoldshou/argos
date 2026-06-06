"""Tool Receipts (HMAC, 契约 §6.2 + spec §6.5/§12.3).

每次 broker 动作产 HMAC 签名回执:干了什么 · args 哈希 · 结果哈希 · 退出码 · 时间 · nonce。
签名 key 只在 host 进程构造 —— 沙箱内代码碰不到,故 agent 伪造不了"我做了 X"。
本阶段为可用占位(可签可验);Phase 4 可扩字段/接 harness 核验,签名算法不变。

签名格式(§6.2 逐字匹配):
  HMAC-SHA256(key, "{action}|{args_hash}|{result_hash}|{exit_code}|{ts}|{nonce}")
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any


def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Receipt:
    action: str
    args_hash: str
    result_hash: str
    exit_code: int | None
    ts: float
    nonce: str
    sig: str


class ReceiptSigner:
    """HMAC 签名器。key 仅在 host(spec §12.3),绝不进沙箱子进程。"""

    def __init__(self, key: bytes) -> None:
        self._key = key

    @staticmethod
    def _payload(action: str, args_hash: str, result_hash: str,
                 exit_code: int | None, ts: float, nonce: str) -> bytes:
        return f"{action}|{args_hash}|{result_hash}|{exit_code}|{ts}|{nonce}".encode("utf-8")

    def sign(self, *, action: str, args: dict, result: Any, exit_code: int | None) -> Receipt:
        args_hash = _sha256(_canon(args))
        result_hash = _sha256(_canon(result))
        ts = time.time()
        nonce = uuid.uuid4().hex
        sig = hmac.new(
            self._key,
            self._payload(action, args_hash, result_hash, exit_code, ts, nonce),
            hashlib.sha256,
        ).hexdigest()
        return Receipt(action=action, args_hash=args_hash, result_hash=result_hash,
                       exit_code=exit_code, ts=ts, nonce=nonce, sig=sig)

    def verify(self, receipt: Receipt) -> bool:
        expect = hmac.new(
            self._key,
            self._payload(receipt.action, receipt.args_hash, receipt.result_hash,
                          receipt.exit_code, receipt.ts, receipt.nonce),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expect, receipt.sig)
