"""记忆持久化:agent 跑完任务,把记录沉淀到本地 JSONL。

这是 Argos 的"记忆大脑"数据源 —— 真实的、随任务生长的记忆,不是编造的演示数据。
每条记录是 agent 跑完的一个任务:目标 + verify 裁决 + 模型 + 时间。

刻意极简:一个 append-only JSONL 文件,无数据库依赖。读时按时间倒序、限量返回。
位置 ~/.argos/memory.jsonl(可被 ARGOS_MEMORY_FILE 覆盖,测试用)。

同时挂一个本地 embedding 缓存(~/.argos/memory_embeddings.json),让 recall() 按 goal
余弦 top-k 召回历史相似任务。写盘后异步算缓存(daemon thread,不阻塞主流程)。
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from argos import llm_embed
# 把 embed_text 提到模块级名字,让测试可以 monkeypatch.setattr(memory, "embed_text", ...)
# 这样写盘的副作用还是走 llm_embed,但单测可以无损替换。
embed_text = llm_embed.embed_text


MEMORY_PATH = Path(
    os.environ.get("ARGOS_MEMORY_FILE")
    or str(Path.home() / ".argos" / "memory.jsonl")
)
MAX_MEMORY_SUMMARY_CHARS = 500
_EMB_CACHE_PATH = Path.home() / ".argos" / "memory_embeddings.json"
_emb_cache: dict[str, list[float]] = {}
_rec_lock = threading.Lock()


def _memory_file() -> Path:
    """解析当前记忆文件路径:env var 优先(测试用),否则用模块级 MEMORY_PATH。"""
    override = os.environ.get("ARGOS_MEMORY_FILE")
    if override:
        return Path(override)
    return MEMORY_PATH


# ── 嵌入缓存读写 ──────────────────────────────────────────────────────────────
def _load_emb_cache() -> None:
    """惰性从磁盘加载嵌入缓存到模块字典;已加载则跳过。"""
    global _emb_cache
    if _emb_cache:
        return
    if not _EMB_CACHE_PATH.exists():
        _emb_cache = {}
        return
    try:
        raw = json.loads(_EMB_CACHE_PATH.read_text("utf-8"))
        _emb_cache = {
            k: v
            for k, v in (raw or {}).items()
            if isinstance(v, list) and len(v) == llm_embed.EMBED_DIM
        }
    except Exception:
        _emb_cache = {}  # 坏文件当空,本机 cache 坏掉不能把 recall 拖死


def _save_emb_cache() -> None:
    """原子写缓存;写不进下次重算(本机能写就下次再写)。"""
    try:
        _EMB_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _EMB_CACHE_PATH.write_text(json.dumps(_emb_cache), encoding="utf-8")
    except Exception:
        pass


# ── 单条记忆 → 索引文本 + 嵌入 ───────────────────────────────────────────────
def _index_text(rec: dict[str, Any]) -> str:
    """把一条记忆的 goal + verdict + model 拼成索引文本,<= MAX_MEMORY_SUMMARY_CHARS。"""
    raw = f"{rec.get('goal', '')} | {rec.get('verdict') or 'unknown'} | {rec.get('model') or ''}"
    return raw[:MAX_MEMORY_SUMMARY_CHARS]


def _emb_for(text: str) -> list[float] | None:
    """sha1(text[:16]) 作 key,命中即返,未命中算。算失败返 None(让 recall 走无 recall 路径)。"""
    _load_emb_cache()
    k = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
    if k in _emb_cache:
        return _emb_cache[k]
    try:
        v = embed_text([text])[0]
    except Exception:
        return None
    _emb_cache[k] = v
    _save_emb_cache()
    return v


def _cosine(a: list[float], b: list[float]) -> float:
    """纯 Python 余弦相似度(避免 numpy 依赖),0 向量保护。"""
    s = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        s += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return s / math.sqrt(na * nb)


# ── recall:按 goal embedding 取 top-k 相似记录 ─────────────────────────────
def recall(goal: str, *, k: int = 3, sim_min: float = 0.4) -> list[dict]:
    """按 goal 余弦相似度取 top-k。失败/无 goal/无记录 → 返空(降级,不抛)。"""
    if not goal.strip():
        return []
    recs = load_memories(limit=200)
    if not recs:
        return []
    goal_emb = _emb_for(goal)
    if goal_emb is None:
        return []
    scored: list[tuple[float, dict]] = []
    for r in recs:
        emb = _emb_for(_index_text(r))
        if emb is None:
            continue
        scored.append((_cosine(goal_emb, emb), r))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [r for s, r in scored[:k] if s >= sim_min]


# ── 写盘:append-only,记录含 id/ts ─────────────────────────────────────────
def record_task(goal: str, verdict: str | None = None, model: str | None = None,
                fact: str | None = None) -> dict:
    """追加一条任务记忆。返回写入的记录(含生成的 id/ts)。

    写盘后异步算 emb 缓存(daemon thread),不阻塞主流程;sidecar 退出可能丢这一次
    缓存,接受 —— 下次 reload 时如果落盘了,load_memories 仍能正常读。
    """
    rec = {
        "id": uuid.uuid4().hex[:12],
        "goal": goal,
        "verdict": verdict,
        "model": model,
        "fact": fact,
        "ts": time.time(),
    }
    with _rec_lock:
        path = _memory_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # 异步触发 emb 缓存:把"goal+verdict+model"索引用 sha1 缓存起来,
    # 下次 recall() 同 goal 即可命中。失败静默(daemon + 异常吞掉)。
    def _background() -> None:
        try:
            _emb_for(_index_text(rec))
        except Exception:
            pass

    threading.Thread(target=_background, daemon=True).start()
    return rec


# ── 读盘:按时间倒序限量 ─────────────────────────────────────────────────────
def load_memories(limit: int = 200) -> list[dict]:
    """读取记忆,按时间倒序,最多 limit 条。文件不存在 → 空列表(诚实空态)。"""
    path = _memory_file()
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # 跳过损坏行,不让一行坏数据毁掉整个记忆
    out.sort(key=lambda r: r.get("ts") or 0, reverse=True)
    return out[:limit]
