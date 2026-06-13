"""Phase 2:FTS5 字面 + CJK 搜(契约 §2 / spec §5.3)。

trigram 对 >=3 字(含中文)命中稳;本测试用 >=3 字 query。2 字 CJK 召回靠 vec
(test_store_recall.py 覆盖)。"""
import pytest

from argos.memory.store import ArgosStore, MessageRow


@pytest.fixture
def store(tmp_path):
    s = ArgosStore(db_path=str(tmp_path / "argos.db"))
    sid = s.create_session(title="t", model="m", system_snapshot="s")
    s.append_message(sid, role="user", content="修复登录失败的并发竞争")
    s.append_message(sid, role="assistant", content="add login retry logic")
    s.append_message(sid, role="user", content="完全不相关的内容")
    yield s
    s.close()


def test_search_english_literal(store):
    rows = store.search("login", limit=10)
    assert any("login retry" in r.content for r in rows)
    assert all(isinstance(r, MessageRow) for r in rows)


def test_search_cjk_three_chars(store):
    rows = store.search("登录失败", limit=10)
    assert any("登录失败" in r.content for r in rows)


def test_search_no_match_returns_empty(store):
    assert store.search("zzz_no_such_token_xyzqwer", limit=10) == []


def test_search_special_chars_dont_crash(store):
    # FTS5 语法字符不应让查询崩(应被转义/引号包裹)
    assert store.search('"', limit=5) == [] or isinstance(store.search('"', limit=5), list)
    assert isinstance(store.search("a OR b", limit=5), list)


def test_search_respects_limit(store):
    sid = store.create_session(title="t2", model="m", system_snapshot="s")
    for i in range(5):
        store.append_message(sid, role="user", content=f"common token number{i}")
    assert len(store.search("common", limit=3)) == 3
