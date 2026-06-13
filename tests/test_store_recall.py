"""Phase 2:可解释召回 recall() → (MemoryRecord, reason)(契约 §2 / spec §5.6)。"""
import pytest

from argos.memory.store import ArgosStore, MemoryRecord


class _FakeEmbedder:
    """子串匹配的假 embedder(record 索引文本含 goal,不能用等值表)。"""
    dim = 3

    def embed(self, texts):
        table = [("跑 pytest", [1.0, 0.0, 0.0]), ("今天天气", [0.0, 1.0, 0.0]),
                 ("写单测", [0.9, 0.0, 0.1])]
        out = []
        for t in texts:
            hit = next((v for k, v in table if k in t), None)
            out.append(hit if hit is not None else [0.0, 0.0, 0.0])
        return out


def _seed(store):
    store._con.execute("INSERT INTO memory(id,goal,verdict,model,fact,ts) VALUES "
                       "('a','跑 pytest','passed','MiniMax-M2',NULL,1.0)")
    store._con.execute("INSERT INTO memory(id,goal,verdict,model,fact,ts) VALUES "
                       "('b','今天天气','passed','MiniMax-M2',NULL,2.0)")
    store._con.execute("INSERT INTO memory(id,goal,verdict,model,fact,ts) VALUES "
                       "('c','写单测','passed','MiniMax-M2',NULL,3.0)")
    store._con.commit()


def test_recall_returns_record_reason_tuples(tmp_path):
    s = ArgosStore(db_path=str(tmp_path / "argos.db"), embedder=_FakeEmbedder())
    _seed(s)
    out = s.recall("跑 pytest", k=2, sim_min=0.4)
    assert len(out) == 2
    rec, reason = out[0]
    assert isinstance(rec, MemoryRecord)
    assert isinstance(reason, str) and reason  # 非空 reason
    assert "跑 pytest" in rec.goal  # top-1 最相似
    assert "相似" in reason and "passed" in reason  # 可解释:含相似度 + verdict
    s.close()


def test_recall_filters_below_simmin(tmp_path):
    s = ArgosStore(db_path=str(tmp_path / "argos.db"), embedder=_FakeEmbedder())
    s._con.execute("INSERT INTO memory(id,goal,verdict,model,fact,ts) VALUES "
                   "('x','今天天气','passed','m',NULL,1.0)")
    s._con.commit()
    out = s.recall("跑 pytest", k=3, sim_min=0.4)  # 天气与 pytest 正交,sim=0
    assert out == []
    s.close()


def test_recall_empty_when_no_memory(tmp_path):
    s = ArgosStore(db_path=str(tmp_path / "argos.db"), embedder=_FakeEmbedder())
    assert s.recall("anything", k=3) == []
    s.close()


def test_recall_degrades_to_fts_when_no_embedder(tmp_path):
    # embedder=None → 降级 FTS5 字面;reason 须诚实标注降级
    s = ArgosStore(db_path=str(tmp_path / "argos.db"), embedder=None)
    s._con.execute("INSERT INTO memory(id,goal,verdict,model,fact,ts) VALUES "
                   "('a','修复登录失败','passed','m',NULL,1.0)")
    s._con.commit()
    out = s.recall("登录失败", k=3)
    assert len(out) == 1
    rec, reason = out[0]
    assert "登录失败" in rec.goal
    assert "降级" in reason or "字面" in reason  # 诚实:标降级,不假装语义召回
    s.close()


def test_recall_degrades_when_embed_raises(tmp_path):
    class _Boom:
        dim = 3
        def embed(self, texts):
            raise RuntimeError("embed down")
    s = ArgosStore(db_path=str(tmp_path / "argos.db"), embedder=_Boom())
    s._con.execute("INSERT INTO memory(id,goal,verdict,model,fact,ts) VALUES "
                   "('a','登录失败重试','passed','m',NULL,1.0)")
    s._con.commit()
    out = s.recall("登录失败", k=3)  # embed 抛 → 降级 FTS
    assert len(out) == 1 and ("字面" in out[0][1] or "降级" in out[0][1])
    s.close()


def test_recall_empty_goal_returns_empty(tmp_path):
    s = ArgosStore(db_path=str(tmp_path / "argos.db"), embedder=_FakeEmbedder())
    assert s.recall("   ", k=3) == []
    s.close()
