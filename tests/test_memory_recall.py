"""memory.recall + record_task 异步 emb 缓存测试。"""
import pytest

from argos import memory


def test_recall_returns_top_k_by_cosine(monkeypatch, tmp_path):
    monkeypatch.setattr(memory, "MEMORY_PATH", tmp_path / "mem.jsonl")
    # 写入 3 条记录
    memory.record_task(goal="跑 pytest", verdict="passed", model="MiniMax-M2")
    memory.record_task(goal="今天天气", verdict="passed", model="MiniMax-M2")
    memory.record_task(goal="写单测", verdict="passed", model="MiniMax-M2")

    # stub embedding:子串匹配(record 索引文本是 "goal | verdict | model",不能用等值查表)
    def fake_emb(texts):
        table = [
            ("跑 pytest", [1.0, 0.0, 0.0]),
            ("今天天气", [0.0, 1.0, 0.0]),
            ("写单测",   [0.9, 0.0, 0.1]),  # 与 "跑 pytest" 相似
        ]
        out = []
        for t in texts:
            hit = next((v for k, v in table if k in t), None)
            out.append(hit if hit is not None else [0.0, 0.0, 0.0])
        return out
    monkeypatch.setattr(memory, "embed_text", fake_emb)
    # 重新清掉 cache(records_cache 是模块级)
    monkeypatch.setattr(memory, "_EMB_CACHE_PATH", tmp_path / "emb.json")
    monkeypatch.setattr(memory, "_emb_cache", {})

    recs = memory.recall("跑 pytest", k=2, sim_min=0.4)
    assert len(recs) == 2
    assert "跑 pytest" in recs[0]["goal"]  # top-1 应是最相似的


def test_recall_empty_when_no_records(monkeypatch, tmp_path):
    monkeypatch.setattr(memory, "MEMORY_PATH", tmp_path / "mem.jsonl")
    monkeypatch.setattr(memory, "_EMB_CACHE_PATH", tmp_path / "emb.json")
    monkeypatch.setattr(memory, "_emb_cache", {})
    assert memory.recall("anything", k=3, sim_min=0.4) == []


def test_recall_filters_below_simmin(monkeypatch, tmp_path):
    monkeypatch.setattr(memory, "MEMORY_PATH", tmp_path / "mem.jsonl")
    memory.record_task(goal="不相关", verdict="passed", model="M2")
    monkeypatch.setattr(memory, "_EMB_CACHE_PATH", tmp_path / "emb.json")
    monkeypatch.setattr(memory, "_emb_cache", {})
    def fake_emb(texts):
        return [[1.0, 0.0, 0.0] if "不相关" not in t else [0.0, 1.0, 0.0] for t in texts]
    monkeypatch.setattr(memory, "embed_text", fake_emb)
    recs = memory.recall("跑 pytest", k=3, sim_min=0.4)
    assert recs == []  # "不相关" 相似度太低被滤掉
