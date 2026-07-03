from __future__ import annotations

import dataclasses

import pytest

from argos.tools.receipts import Receipt, ReceiptSigner


def test_receipt_is_frozen():
    signer = ReceiptSigner(key=b"secret-host-key")
    r = signer.sign(action="run_command", args={"command": "pytest"},
                    result="[exit_code=0]", exit_code=0)
    assert dataclasses.is_dataclass(r)
    assert Receipt.__dataclass_params__.frozen is True
    assert r.action == "run_command"
    assert r.exit_code == 0
    assert r.sig and len(r.sig) >= 32


def test_signer_verifies_own_receipt():
    signer = ReceiptSigner(key=b"k")
    r = signer.sign(action="web_search", args={"query": "x"}, result="hits", exit_code=None)
    assert signer.verify(r) is True


def test_tampered_args_or_result_fails_verify():
    signer = ReceiptSigner(key=b"k")
    r = signer.sign(action="run_command", args={"command": "ls"}, result="ok", exit_code=0)
    forged = dataclasses.replace(r, args_hash="deadbeef")
    assert signer.verify(forged) is False
    forged2 = dataclasses.replace(r, result_hash="deadbeef")
    assert signer.verify(forged2) is False


def test_different_key_cannot_verify():
    a = ReceiptSigner(key=b"host-only")
    r = a.sign(action="x", args={}, result="y", exit_code=None)
    b = ReceiptSigner(key=b"attacker-guess")
    assert b.verify(r) is False


def test_sandbox_child_cannot_forge_receipt():
    host_signer = ReceiptSigner(key=b"host-secret-never-leaves-host-process")
    real_receipt = host_signer.sign(
        action="run_command", args={"command": "echo hi"}, result="hi\n", exit_code=0
    )
    for guessed_key in [b"", b"host-secret", b"host-secret-never-leaves-host-process-x",
                        b"attacker", b"0" * 32]:
        attacker_signer = ReceiptSigner(key=guessed_key)
        if guessed_key != b"host-secret-never-leaves-host-process":
            assert attacker_signer.verify(real_receipt) is False, (
                f"SECURITY VIOLATION: attacker with key={guessed_key!r} "
                f"verified a receipt signed by host!"
            )
        fake = dataclasses.replace(real_receipt, sig="deadbeef" * 8)
        assert host_signer.verify(fake) is False
    assert host_signer.verify(real_receipt) is True
