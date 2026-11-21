"""Optional semantic matcher. Off unless EMBED_API_KEY is set.

It is only a fallback for one job: when plain word matching finds no task for a question, rank the titles of
tasks the asker may already see by embedding similarity. Vectors are cached in SQLite (table `embeddings`),
so the same text is never embedded twice. It never answers, never writes facts and never sees a record the
asker cannot read: the candidate list is built after the visibility check. A weak or ambiguous match returns
nothing, and the rules then say "I have nothing on that" or ask which one.
"""
import hashlib
import json
import math
import os
import time
import urllib.request

URL = os.environ.get("EMBED_URL", "https://api.openai.com/v1/embeddings")
MODEL = os.environ.get("EMBED_MODEL", "text-embedding-3-small")
PRICE_IN = float(os.environ.get("EMBED_PRICE_IN", "0.02")) / 1e6     # USD per token
MIN_SCORE = float(os.environ.get("EMBED_MIN_SCORE", "0.45"))
MIN_GAP = float(os.environ.get("EMBED_MIN_GAP", "0.04"))
TIMEOUT = float(os.environ.get("EMBED_TIMEOUT", "8"))
MAX_CALLS = int(os.environ.get("EMBED_MAX_CALLS", "20"))

USAGE = {"input_tokens": 0, "cost_usd": 0.0, "ms": 0, "calls": 0}
_state = {"fails": 0}


def enabled() -> bool:
    return (bool(os.environ.get("EMBED_API_KEY")) and os.environ.get("ASSIST_EMBED", "1") != "0"
            and _state["fails"] < 2 and USAGE["calls"] < MAX_CALLS)


def usage() -> dict:
    return {"input_tokens": USAGE["input_tokens"], "cost_usd": round(USAGE["cost_usd"], 6), "ms": USAGE["ms"]}


def _post_embed(texts: list[str]) -> tuple[list[list[float]], int]:
    body = {"model": MODEL, "input": texts}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), method="POST", headers={
        "Authorization": f"Bearer {os.environ['EMBED_API_KEY']}", "Content-Type": "application/json", "User-Agent": "assist/0.3"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        data = json.loads(r.read())
    vecs = [d["embedding"] for d in sorted(data["data"], key=lambda d: d["index"])]
    n = int((data.get("usage") or {}).get("total_tokens") or sum(len(t) for t in texts) // 4)
    return vecs, n


def _h(text: str) -> str:
    return hashlib.sha1(text.strip().lower().encode()).hexdigest()


def vectors(conn, texts: list[str]) -> list[list[float]] | None:
    """Vectors for texts, from the SQLite cache where possible. None on any failure."""
    conn.execute("CREATE TABLE IF NOT EXISTS embeddings(h TEXT, model TEXT, vec TEXT, PRIMARY KEY(h, model))")
    have, missing = {}, []
    for t in texts:
        row = conn.execute("SELECT vec FROM embeddings WHERE h=? AND model=?", (_h(t), MODEL)).fetchone()
        if row:
            have[_h(t)] = json.loads(row["vec"])
        elif t not in missing:
            missing.append(t)
    if missing:
        if not enabled():
            return None
        t0 = time.perf_counter()
        try:
            vecs, n = _post_embed(missing)
            if len(vecs) != len(missing):
                raise ValueError("size")
        except Exception:
            _state["fails"] += 1
            return None
        USAGE["calls"] += 1
        USAGE["input_tokens"] += n
        USAGE["cost_usd"] += n * PRICE_IN
        USAGE["ms"] += int((time.perf_counter() - t0) * 1000)
        for t, v in zip(missing, vecs):
            have[_h(t)] = v
            conn.execute("INSERT OR REPLACE INTO embeddings(h, model, vec) VALUES(?,?,?)", (_h(t), MODEL, json.dumps(v)))
        conn.commit()
    return [have[_h(t)] for t in texts]


def cosine(a: list[float], b: list[float]) -> float:
    da, db_ = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b)) / (da * db_) if da and db_ else 0.0


def best_matches(conn, question: str, items: list[tuple[str, str]]) -> list[str]:
    """Ids of the items that match the question. [] if weak, one id if clear, several if too close to call."""
    if not items or not enabled():
        return []
    vecs = vectors(conn, [question] + [text for _, text in items])
    if not vecs:
        return []
    q, rest = vecs[0], vecs[1:]
    ranked = sorted(((cosine(q, v), i) for (i, _), v in zip(items, rest)), reverse=True)
    if ranked[0][0] < MIN_SCORE:
        return []
    return [i for s, i in ranked if ranked[0][0] - s < MIN_GAP]
