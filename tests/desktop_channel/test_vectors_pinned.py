"""向量防漂移测试 — 把 desktop/sdk/test/vectors.json 双向钉在 Python ABI 上。

TS 侧测试（vectors.test.ts）钉 parse 侧：json → TypedEvent。
本测试钉 serialize 侧：deserialize_event(serialized) → serialize_event → 与 vectors.json 入库向量逐字段一致。

这意味着以后协议改动，任何一侧漂移当场红：
  - TS 侧改字段/类型 → vectors.test.ts 红
  - Python 侧改字段/类型 → 本测试红
  - 新增 kind 未同步更新 vectors.json → 覆盖缺口但不强制（coverage 在 test_event_golden.py）

跑法：
  uv run --no-sync pytest tests/desktop_channel -q --no-cov
"""
from __future__ import annotations

import json
import pathlib
from dataclasses import asdict
from typing import Any

import pytest

from argos.protocol.events import deserialize_event, serialize_event

# vectors.json 路径（相对于仓库根）
VECTORS_PATH = (
    pathlib.Path(__file__).parent.parent.parent
    / "desktop" / "sdk" / "test" / "vectors.json"
)


def _load_vectors() -> list[dict[str, Any]]:
    with open(VECTORS_PATH, encoding="utf-8") as f:
        return json.load(f)  # type: ignore[return-value]


VECTORS: list[dict[str, Any]] = _load_vectors()


def _deep_subset(expected: Any, actual: Any, path: str = "") -> None:
    """Assert that `expected` is a deep subset of `actual`.

    For dict: every key in `expected` exists in `actual` with an equal value.
    For list/tuple: lengths match and each element recursively matches.
    For scalars: strict equality.
    """
    if isinstance(expected, dict):
        assert isinstance(actual, dict), f"{path}: expected dict, got {type(actual)}"
        for k, v in expected.items():
            assert k in actual, f"{path}.{k}: key missing from actual"
            _deep_subset(v, actual[k], f"{path}.{k}")
    elif isinstance(expected, (list, tuple)):
        # Normalize both to list for comparison
        exp_list = list(expected)
        act_list = list(actual) if isinstance(actual, (list, tuple)) else actual
        assert isinstance(act_list, list), f"{path}: expected list, got {type(actual)}"
        assert len(exp_list) == len(act_list), (
            f"{path}: length mismatch: expected {len(exp_list)}, got {len(act_list)}"
        )
        for i, (e, a) in enumerate(zip(exp_list, act_list)):
            _deep_subset(e, a, f"{path}[{i}]")
    else:
        assert expected == actual, (
            f"{path}: expected {expected!r}, got {actual!r}"
        )


def _ids_for_vectors() -> list[str]:
    """Generate pytest IDs, appending a counter to handle duplicate kinds."""
    counts: dict[str, int] = {}
    ids = []
    for v in VECTORS:
        kind = v["kind"]
        counts[kind] = counts.get(kind, 0) + 1
        ids.append(f"{kind}#{counts[kind]}")
    return ids


@pytest.mark.parametrize("vector", VECTORS, ids=_ids_for_vectors())
def test_round_trip_serialize(vector: dict[str, Any]) -> None:
    """deserialize_event(serialized) → serialize_event → 逐字段与 expected_data 一致。

    1. vectors.json の serialized フィールドは Python serialize_event() が吐いた JSON。
    2. deserialize_event でイベントを復元。
    3. serialize_event で再シリアライズし、data フィールドを取り出す。
    4. expected_data の全フィールドが data に存在し、値が一致することを確認。

    NOTE: expected_data は部分一致（subset）のみ要求する（TS 側が意図的に
    いくつかのフィールドを省いているため）。Python 側は全フィールドを保持する。
    """
    serialized: str = vector["serialized"]
    expected_data: dict[str, Any] = vector["expected_data"]

    # Step 1: deserialize (Python ABI round-trip in)
    try:
        ev = deserialize_event(serialized)
    except Exception as exc:
        pytest.fail(
            f"deserialize_event failed for kind={vector['kind']!r}: {exc}\n"
            f"serialized={serialized!r}"
        )

    # Step 2: re-serialize (Python ABI round-trip out)
    re_serialized = serialize_event(ev)
    re_obj: dict[str, Any] = json.loads(re_serialized)

    # Step 3: kind must be preserved
    assert re_obj["kind"] == vector["kind"], (
        f"kind mismatch: expected {vector['kind']!r}, got {re_obj['kind']!r}"
    )

    # Step 4: expected_data fields must all be present and match
    actual_data: dict[str, Any] = re_obj["data"]
    _deep_subset(expected_data, actual_data)


def test_all_vector_kinds_known_to_python() -> None:
    """所有 vectors.json 中的 kind 必须能被 deserialize_event 解析（无 ValueError）。"""
    seen_kinds: set[str] = set()
    failures: list[str] = []
    for v in VECTORS:
        kind = v["kind"]
        if kind in seen_kinds:
            continue
        seen_kinds.add(kind)
        try:
            deserialize_event(v["serialized"])
        except ValueError as exc:
            failures.append(f"  kind={kind!r}: {exc}")
        except Exception as exc:
            failures.append(f"  kind={kind!r}: unexpected error: {exc}")
    if failures:
        pytest.fail("deserialize_event failed for:\n" + "\n".join(failures))


def test_verify_verdict_unverifiable_never_becomes_passed() -> None:
    """Python 侧不变量：unverifiable verdict status 永远不会被映射为 passed。"""
    verdict_vectors = [v for v in VECTORS if v["kind"] == "verify_verdict"]
    assert len(verdict_vectors) >= 3, (
        f"expected at least 3 verify_verdict vectors, got {len(verdict_vectors)}"
    )
    for v in verdict_vectors:
        ev = deserialize_event(v["serialized"])
        re_serialized = serialize_event(ev)
        data = json.loads(re_serialized)["data"]
        status = data["verdict"]["status"]
        expected_status = v["expected_data"]["verdict"]["status"]
        assert status == expected_status, (
            f"verdict status changed after round-trip: expected {expected_status!r}, got {status!r}"
        )
        if expected_status == "unverifiable":
            assert status != "passed", (
                "unverifiable verdict status must never be coerced to passed"
            )


def test_proactive_suggestion_requires_confirmation_invariant() -> None:
    """Python 侧不变量：proactive_suggestion.requires_confirmation 恒为 True。"""
    found = [v for v in VECTORS if v["kind"] == "proactive_suggestion"]
    assert len(found) >= 1, "expected at least one proactive_suggestion vector"
    for v in found:
        ev = deserialize_event(v["serialized"])
        re_serialized = serialize_event(ev)
        data = json.loads(re_serialized)["data"]
        assert data["requires_confirmation"] is True, (
            "requires_confirmation must always be True (protocol invariant)"
        )
