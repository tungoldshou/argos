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
