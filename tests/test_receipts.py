"""Tool Receipts(契约 §6.2;spec §6.5/§12.3):HMAC 签名 host 侧,agent 伪造不了。

Task 8(Phase 4):receipts.py 在 Phase 3 已建并经 tests/test_broker_receipt_unforgeable.py
锁定。本文件按契约 §6.2 逐字补齐 Task 8 要求的核验/防重放/冻结测试,VERIFY 既有实现
完全符合 §6.2 的 HMAC 形式,**不重定义** Receipt/ReceiptSigner(单一定义见 tools/receipts.py)。
"""
import dataclasses

import pytest

from argos_agent.tools.receipts import Receipt, ReceiptSigner


def test_sign_then_verify_roundtrip():
    signer = ReceiptSigner(key=b"host-secret-key")
    r = signer.sign(action="run_command", args={"command": "pytest -q"},
                    result="12 passed", exit_code=0)
    assert isinstance(r, Receipt)
    assert r.action == "run_command"
    assert r.exit_code == 0
    assert signer.verify(r) is True


def test_tampered_sig_fails_verify():
    signer = ReceiptSigner(key=b"host-secret-key")
    r = signer.sign(action="web_search", args={"q": "x"}, result="hits", exit_code=None)
    forged = dataclasses.replace(r, sig="deadbeef")
    assert signer.verify(forged) is False


def test_tampered_result_hash_fails_verify():
    signer = ReceiptSigner(key=b"host-secret-key")
    r = signer.sign(action="run_command", args={"command": "ls"}, result="a\nb", exit_code=0)
    forged = dataclasses.replace(r, result_hash="0" * 64)
    assert signer.verify(forged) is False


def test_tampered_args_hash_fails_verify():
    signer = ReceiptSigner(key=b"host-secret-key")
    r = signer.sign(action="run_command", args={"command": "ls"}, result="ok", exit_code=0)
    forged = dataclasses.replace(r, args_hash="f" * 64)
    assert signer.verify(forged) is False


def test_different_key_cannot_verify():
    # agent 在沙箱里即便仿造了一个 signer,没有 host key 也签不出能被 host 接受的回执。
    host = ReceiptSigner(key=b"host-secret-key")
    attacker = ReceiptSigner(key=b"attacker-guess")
    fake = attacker.sign(action="run_command", args={"command": "rm -rf /"},
                         result="done", exit_code=0)
    assert host.verify(fake) is False


def test_nonce_makes_each_receipt_unique():
    signer = ReceiptSigner(key=b"k")
    r1 = signer.sign(action="a", args={}, result="x", exit_code=None)
    r2 = signer.sign(action="a", args={}, result="x", exit_code=None)
    assert r1.nonce != r2.nonce
    assert r1.sig != r2.sig  # 同输入不同 nonce → 不同签名(防重放)


def test_receipt_is_frozen():
    signer = ReceiptSigner(key=b"k")
    r = signer.sign(action="a", args={}, result="x", exit_code=None)
    with pytest.raises(Exception):
        r.sig = "x"  # type: ignore[misc]
