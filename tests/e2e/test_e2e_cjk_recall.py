import json

import pytest

from argos.memory.store import ArgosStore, MemoryRecord


class _FakeEmbedder:
    dim = 4

    def embed(self, texts):
        out = []
        for t in texts:
            v = [0.0, 0.0, 0.0, 0.0]
            if "登录" in t or "登陆" in t:
                v[0] = 1.0
            elif "支付" in t or "付款" in t:
                v[1] = 1.0
            elif "部署" in t or "发布" in t:
                v[2] = 1.0
            else:
                v[3] = 1.0
            out.append(v)
        return out


_RECS = [
    {"id": "m1", "goal": "修复用户登录失败的 bug", "verdict": "passed", "model": "MiniMax-M2", "fact": "清了过期 session", "ts": 1.0},
    {"id": "m2", "goal": "实现微信支付回调", "verdict": "passed", "model": "MiniMax-M2", "fact": "校验签名", "ts": 2.0},
    {"id": "m3", "goal": "部署到生产环境", "verdict": "failed", "model": "MiniMax-M2", "fact": "证书过期", "ts": 3.0},
]


@pytest.fixture
def cjk_store(tmp_path):
    jl = tmp_path / "mem.jsonl"
    jl.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in _RECS), encoding="utf-8")
    s = ArgosStore(db_path=str(tmp_path / "argos.db"), embedder=_FakeEmbedder())
    n = s.migrate_jsonl(str(jl))
    assert n == 3, f"应迁入 3 条中文记忆,实际 {n}"
    yield s
    s.close()


def test_recall_hits_relevant_chinese_with_reason(cjk_store):
    out = cjk_store.recall("登录又出问题了", k=3, sim_min=0.4)
    assert out, "相关中文查询必须命中"
    rec, reason = out[0]
    assert isinstance(rec, MemoryRecord)
    assert rec.id == "m1", "应召回最相关的登录记忆"
    assert reason and ("相似" in reason or "降级" in reason or "字面" in reason), "reason 须可解释"


def test_recall_misses_unrelated_chinese(cjk_store):
    out = cjk_store.recall("今天天气怎么样", k=3, sim_min=0.4)
    ids = [r.id for r, _ in out]
    assert "m1" not in ids and "m2" not in ids and "m3" not in ids


def test_fts_search_hits_chinese_message(cjk_store):
    cjk_store.ensure_session("s-cjk", title="t", model="m", system_snapshot="")
    cjk_store.append_message("s-cjk", role="user", content="请修复用户登录失败的问题")
    hits = cjk_store.search("登录失败")
    assert any("登录失败" in h.content for h in hits), "中文 4 字短语应经 FTS5 命中"
