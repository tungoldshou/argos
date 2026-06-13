"""#5 SSE 续传游标:store.append 集中领号(唯一单调 _seq),replay 按 _seq 字段过滤。

bug:worker 路径给事件领 _seq,但 manager 的 state_change/checkpoint 经 store.append 不带 _seq
却占物理行;replay 过去按物理行号过滤,客户端按 _seq 字段游标 → 重连恒重发已见 / 静默丢真事件。
修法:store.append 成为唯一领号点(两条写入路径一致),replay 按 _seq 字段过滤。
"""
from __future__ import annotations

from pathlib import Path

from argos.daemon.store import RunStore


def test_append_assigns_monotonic_seq_to_all_nonmeta_events(tmp_path: Path):
    """两条写入路径(worker / manager state_change·checkpoint)都经 store.append;集中领号
    确保每个非 meta 事件有唯一单调 _seq(run_meta 不领号,replay 第 0 行总在)。"""
    store = RunStore(tmp_path / "runs")
    assert store.append("r1", {"kind": "run_meta", "run_id": "r1"}) == 0   # meta 不领号
    s1 = store.append("r1", {"kind": "token_delta", "text": "a"})
    s2 = store.append("r1", {"kind": "state_change", "to": "running"})     # manager 路径
    s3 = store.append("r1", {"kind": "code_action", "code": "x"})
    assert (s1, s2, s3) == (1, 2, 3)
    seqs = [e["_seq"] for e in store.replay("r1") if e["kind"] != "run_meta"]
    assert seqs == [1, 2, 3]


def test_replay_since_filters_by_seq_field_not_physical_row(tmp_path: Path):
    """客户端按事件 _seq 字段续传 → replay 必须按 _seq 字段过滤而非物理行号,否则混入的
    state_change 行会让 since 错位(重发已见 / 丢真事件)。"""
    store = RunStore(tmp_path / "runs")
    store.append("r1", {"kind": "run_meta", "run_id": "r1"})
    store.append("r1", {"kind": "token_delta"})        # _seq=1
    store.append("r1", {"kind": "state_change"})        # _seq=2
    store.append("r1", {"kind": "code_action"})         # _seq=3
    got = list(store.replay("r1", since_seq=2))          # 客户端已见 _seq=2,重连
    kinds = [e["kind"] for e in got]
    assert "run_meta" in kinds          # meta 总在(重建上下文)
    assert "token_delta" not in kinds   # _seq=1 已见,不重发
    assert "state_change" not in kinds  # _seq=2 已见,不重发
    assert "code_action" in kinds       # _seq=3 新,续传


def test_seq_monotonic_across_store_reinit(tmp_path: Path):
    """跨 daemon 重启(新 RunStore 实例,内存计数器丢失)→ 从文件恢复 max _seq 续传单调,
    不与已有 _seq 冲突(否则 resume 后 _seq 回退,客户端游标错乱)。"""
    store1 = RunStore(tmp_path / "runs")
    store1.append("r1", {"kind": "run_meta", "run_id": "r1"})
    store1.append("r1", {"kind": "token_delta"})   # _seq=1
    store1.append("r1", {"kind": "code_action"})   # _seq=2
    store2 = RunStore(tmp_path / "runs")           # 模拟 daemon 重启
    assert store2.append("r1", {"kind": "token_delta"}) == 3   # 接续,不回退


def test_full_replay_yields_legacy_events_without_seq(tmp_path: Path):
    """向后兼容:改动前写的文件(事件无 _seq)在全量重放(since=0)时不漏。"""
    store = RunStore(tmp_path / "runs")
    path = tmp_path / "runs" / "r1.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    # 手写无 _seq 的历史文件
    path.write_text(
        '{"kind":"run_meta","run_id":"r1"}\n'
        '{"kind":"token_delta","text":"legacy"}\n'
        '{"kind":"state_change","to":"running"}\n',
        encoding="utf-8",
    )
    kinds = [e["kind"] for e in store.replay("r1")]
    assert kinds == ["run_meta", "token_delta", "state_change"]   # 全量不漏
