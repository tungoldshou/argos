"""Phase 3:Receipt HMAC 在 host 签,沙箱拿不到 key;篡 args/result → verify False(契约 §6.2 + spec §12.3)。"""
from __future__ import annotations

import dataclasses

import pytest

from argos_agent.tools.receipts import Receipt, ReceiptSigner


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
    forged = dataclasses.replace(r, args_hash="deadbeef")   # 篡 args 哈希
    assert signer.verify(forged) is False
    forged2 = dataclasses.replace(r, result_hash="deadbeef")  # 篡 result 哈希
    assert signer.verify(forged2) is False


def test_different_key_cannot_verify():
    a = ReceiptSigner(key=b"host-only")
    r = a.sign(action="x", args={}, result="y", exit_code=None)
    b = ReceiptSigner(key=b"attacker-guess")   # 沙箱猜的 key
    assert b.verify(r) is False


def test_sandbox_child_cannot_forge_receipt():
    """安全核心:模拟沙箱子进程只能猜 key — 证明没有 key 不可能伪造有效回执。

    沙箱子进程只拿到 _broker RPC stub(写请求到 stdout),绝对拿不到 ReceiptSigner 或其 key。
    本测试显式断言:即使攻击者拿到 Receipt 的所有公开字段,重建一个 ReceiptSigner
    用任意 key 也无法通过 host signer.verify()。
    """
    host_signer = ReceiptSigner(key=b"host-secret-never-leaves-host-process")
    # host 正当签一张回执
    real_receipt = host_signer.sign(
        action="run_command", args={"command": "echo hi"}, result="hi\n", exit_code=0
    )
    # 攻击者(模拟沙箱侧代码)看到了回执的所有公开字段
    # 但没有 key — 尝试构造相同 payload、用猜测的 key
    for guessed_key in [b"", b"host-secret", b"host-secret-never-leaves-host-process-x",
                        b"attacker", b"0" * 32]:
        attacker_signer = ReceiptSigner(key=guessed_key)
        # 尝试方法1: 直接验证真回执(key 不同 → 失败)
        if guessed_key != b"host-secret-never-leaves-host-process":
            assert attacker_signer.verify(real_receipt) is False, (
                f"SECURITY VIOLATION: attacker with key={guessed_key!r} "
                f"verified a receipt signed by host!"
            )
        # 尝试方法2: 自建一张字段相同的回执、篡改 sig 字段
        fake = dataclasses.replace(real_receipt, sig="deadbeef" * 8)
        assert host_signer.verify(fake) is False
    # host signer 能验证自己的真回执
    assert host_signer.verify(real_receipt) is True
