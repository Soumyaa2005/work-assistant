"""Short questions. Order: clarify/refuse checks, task lookups, client facts, then plain retrieval.

Every path reads only records the asker may see, as of the time of the question.
"""
from __future__ import annotations
import json
import re
import time

from . import embed, llm, pack
from .db import rec_dict
from .memory import forget_sets, is_forgotten, text_forgotten
from .text import first_sentence, sentences, stem, terms, tokens

STATUS_TEXT = {"done": "done (complete)", "in_progress": "in progress (being worked on)",
               "todo": "to do (not started)", "blocked": "blocked", "cancelled": "cancelled"}
_GEO = {"london": ".uk", "uk": ".uk", "britain": ".uk", "mumbai": ".in", "delhi": ".in", "india": ".in", "pune": ".in",
        "bangalore": ".in", "bengaluru": ".in", "hyderabad": ".in", "chennai": ".in"}
_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _usage(t0):
    u = llm.usage()
    e = embed.usage()
    u["input_tokens"] += e["input_tokens"]
    u["cost_usd"] = round(u["cost_usd"] + e["cost_usd"], 6)
    u["ms"] = int((time.perf_counter() - t0) * 1000)
    return u


class Ctx:
    def __init__(self, conn, person, at, question):
        self.conn, self.person, self.at, self.q = conn, person, at, question
        self.fsets = forget_sets(conn)
        self.qterms = terms(question)
        self.qtokens = tokens(question)
        self._recs = None

    def visible(self) -> list[dict]:
        if self._recs is None:
            out = []
            for r in self.conn.execute("SELECT * FROM records WHERE at<=? AND suspect=0 ORDER BY at", (self.at,)):
                rec = rec_dict(r)
                if pack.can_see(self.person, rec) and not is_forgotten(rec, self.fsets):
                    out.append(rec)
            self._recs = out
        return self._recs

    def can(self, record_id: str) -> bool:
        """May the asker see this record, as of the question time? Every cited id must pass."""
        r = self.conn.execute("SELECT * FROM records WHERE id=? AND at<=? AND suspect=0", (record_id, self.at)).fetchone()
        if not r:
            return False
        rec = rec_dict(r)
        return pack.can_see(self.person, rec) and not is_forgotten(rec, self.fsets)

    def hidden_matching(self, author: str | None, needle_terms: set[str]) -> list[dict]:
        out = []
        for r in self.conn.execute("SELECT * FROM records WHERE at<=? AND suspect=0", (self.at,)):
            rec = rec_dict(r)
            if pack.can_see(self.person, rec) or rec["org"] != pack.org_of(self.person):
                continue
            if author and rec["author"] != author:
                continue
            if needle_terms <= terms(rec["raw"].get("body", "")):
                out.append(rec)
        return out


# ---------------------------------------------------------------- entity resolution
def client_of_question(ctx: Ctx) -> tuple[str | None, str | None]:
    """(client id, phrase). Uses ids, names, initials, name prefixes, then a tiny geography hint."""
    cl = pack.clients()
    toks = ctx.qtokens
    raw_up = re.findall(r"\b[A-Z]{2,3}\b", ctx.q)
    for c in cl:
        name_words = [w.lower() for w in c["name"].split()]
        for t in toks:
            if t == c["id"] or t == name_words[0] or (len(t) >= 4 and c["id"].startswith(t)):
                return c["id"], t
    for up in raw_up:
        hits = [c for c in cl if _subseq(up.lower(), c["id"]) and up.lower()[0] == c["id"][0]]
        if len(hits) == 1:
            return hits[0]["id"], up
    for t in toks:
        tld = _GEO.get(t)
        if tld:
            hits = [c["id"] for c in cl if _client_has_tld(ctx.conn, c["id"], tld)]
            if len(hits) == 1:
                return hits[0], t
    return None, None


def _subseq(small: str, big: str) -> bool:
    it = iter(big)
    return all(ch in it for ch in small)


def _client_has_tld(conn, client: str, tld: str) -> bool:
    for r in conn.execute("SELECT raw FROM records WHERE type='event' AND client=?", (client,)):
        for a in json.loads(r["raw"]).get("attendees") or []:
            if a.startswith("ext:") and a.rstrip(".").endswith(tld):
                return True
    return False


def person_candidates(first: str) -> list[str]:
    return [p["id"] for p in pack.people().values() if p["org"] == "org_kp" and p["name"].split()[0].lower() == first.lower()]


def asker_clients(conn, person: str) -> set[str]:
    cs = set()
    for r in conn.execute("SELECT client, raw FROM records WHERE type='event' AND client IS NOT NULL"):
        if person in (json.loads(r["raw"]).get("attendees") or []):
            cs.add(r["client"])
    for r in conn.execute("SELECT DISTINCT client FROM records WHERE author=? AND client IS NOT NULL", (person,)):
        cs.add(r["client"])
    return cs


# ---------------------------------------------------------------- task lookup
def task_state(ctx: Ctx, task_id: str) -> dict | None:
    """Fold the task's real changes in time order. Comment records carry stale status values, so they are ignored."""
    rows = ctx.conn.execute("SELECT * FROM records WHERE type='task' AND at<=? AND json_extract(raw,'$.task_id')=? "
                            "ORDER BY at, id", (ctx.at, task_id)).fetchall()
    state, last = None, None
    for r in rows:
        rec = rec_dict(r)
        if not (pack.can_see(ctx.person, rec) and not is_forgotten(rec, ctx.fsets)):
            continue                      # a record the asker may not read never shapes the answer
        raw, ch = rec["raw"], rec["raw"].get("change") or {}
        field = ch.get("field")
        if field == "comment":
            continue
        if state is None:
            state = {k: raw.get(k) for k in ("task_id", "title", "client", "owner", "due", "status")}
        if field == "created":
            state.update({k: raw.get(k) for k in ("owner", "due", "status")})
        elif field in ("owner", "due", "status"):
            state[field] = ch.get("to")
        last = rec
    if state is None:
        return None
    return {**last, "raw": {**last["raw"], **state}}


def find_task(ctx: Ctx, client: str | None) -> tuple[dict | None, list[dict]]:
    """Best task by title words. Returns (task record, ties)."""
    titles: dict[str, dict] = {}
    for r in ctx.visible():
        if r["type"] == "task":
            titles[r["raw"]["task_id"]] = r["raw"]
    scored = []
    for tid, raw in titles.items():
        tt = terms(raw.get("title", ""))
        if not tt:
            continue
        hit = len(tt & ctx.qterms) / len(tt)
        if hit >= 0.99 or (len(tt) >= 3 and hit >= 0.66):
            bonus = 0.2 if client and raw.get("client") == client else 0
            scored.append((hit + bonus, tid))
    if not scored:
        return _semantic_task(ctx, titles, client)
    scored.sort(reverse=True)
    best = [t for s, t in scored if s == scored[0][0]]
    if len(best) > 1 and client:
        narrowed = [t for t in best if titles[t].get("client") == client]
        best = narrowed or best
    return (task_state(ctx, best[0]), [task_state(ctx, t) for t in best]) if best else (None, [])


_TASK_INTENT = re.compile(r"\b(who|owner|owns|handles|when|due|deadline|status|done|finished|progress|ready)\b", re.I)


def _semantic_task(ctx: Ctx, titles: dict, client: str | None) -> tuple[dict | None, list[dict]]:
    """Fallback when no title shares enough words with the question. Only visible tasks are candidates."""
    if not embed.enabled() or not _TASK_INTENT.search(ctx.q):
        return None, []
    pool = {tid: raw for tid, raw in titles.items() if not client or raw.get("client") == client} or titles
    ids = embed.best_matches(ctx.conn, ctx.q, [(tid, raw.get("title", "")) for tid, raw in pool.items()])
    states = [t for t in (task_state(ctx, i) for i in ids) if t]
    return (states[0], states) if states else (None, [])


def task_answer(ctx: Ctx, task: dict, client_phrase) -> dict:
    raw = task["raw"]
    title, kind = raw["title"], ctx.qtokens
    ql = ctx.q.lower()
    if re.search(r"\b(who|owner|owns|own|handles|handling|responsible)\b", ql):
        text = f"{pack.name_of(raw['owner'])} ({raw['owner']}) owns {title}."
    elif re.search(r"\b(when|due|deadline|date)\b", ql):
        text = f"{title} is due {pack.fmt_day(raw['due'])} ({raw['due']})."
    else:
        text = f"{title} is {STATUS_TEXT.get(raw['status'], raw['status'])}."
    if re.search(r"\b(status|done|finished|complete|progress)\b", ql) and not re.search(r"\b(who|owns|when|due)\b", ql):
        text = f"{title} is {STATUS_TEXT.get(raw['status'], raw['status'])}."
    matched = [{"phrase": title, "id": raw["task_id"], "sources": [task["id"]]}]
    if client_phrase[0]:
        matched.append({"phrase": client_phrase[1], "id": client_phrase[0], "sources": []})
    return {"answer": {"text": text, "sources": [task["id"]]}, "matched": matched}


# ---------------------------------------------------------------- weekday clarify ("the Friday thing")
def weekday_tasks(ctx: Ctx) -> list[dict] | None:
    wd = next((w for w in _WEEKDAYS if w in ctx.qtokens), None)
    if not wd or "thing" not in ctx.qtokens:
        return None
    asked = pack.local_date(ctx.at, ctx.person)
    target = pack.next_weekday(asked, wd, strictly_after=False)
    latest: dict[str, dict] = {}
    for r in ctx.visible():
        if r["type"] == "task":
            latest[r["raw"]["task_id"]] = r["raw"]
    due = [t for t in latest.values() if t.get("due") == str(target) and t.get("status") not in ("cancelled",)]
    mine = [t for t in due if t.get("owner") == ctx.person]
    return mine or due


# ---------------------------------------------------------------- facts (billing and friends)
def fact_answer(ctx: Ctx, client: str | None) -> dict | None:
    ql = ctx.q.lower()
    if "billing" in ctx.qtokens and re.search(r"\b(who|owns|handles|owner|contact)\b", ql):
        subject = "billing"
    elif "launch" in ctx.qtokens and re.search(r"\b(when|date|day|scheduled|on)\b", ql):
        subject = "launch"
    else:
        return None
    clients = [client] if client else sorted({r["client"] for r in ctx.visible() if r.get("client")})
    for c in clients:
        facts = [f for f in ctx.conn.execute("SELECT * FROM facts WHERE client=? AND subject=? AND at<=? ORDER BY at DESC, id DESC",
                                             (c, subject, ctx.at)) if ctx.can(f["record_id"])]
        f = facts[0] if facts else None
        corr = ctx.conn.execute("SELECT * FROM corrections WHERE person=? AND subject=? AND (client IS ? OR client IS NULL) "
                                "ORDER BY id DESC LIMIT 1", (ctx.person, subject, c)).fetchone()
        cname = next((x["name"] for x in pack.clients() if x["id"] == c), c)
        if corr and corr["value"] and not text_forgotten(ctx.person, corr["words"], ctx.fsets):
            name, vid, src = corr["value"], corr["value_id"], [f["record_id"]] if f else []
        elif f:
            name, vid, src = f["value"], f["value_id"], [f["record_id"]]
        else:
            continue
        if subject == "launch":
            text = f"The {cname} launch is on {name}."
        else:
            text = f"{f'{name} ({vid})' if vid else name} owns billing for {cname}."
        return {"answer": {"text": text, "sources": src}, "matched": [{"phrase": cname, "id": c, "sources": src}]}
    return None


# ---------------------------------------------------------------- "which Arjun"
def person_in_question(ctx: Ctx) -> dict | None:
    names = {p["name"].split()[0].lower() for p in pack.people().values() if p["org"] == "org_kp"}
    for w in re.findall(r"\b[A-Z][a-z]+\b", ctx.q):
        if w.lower() in names and w.lower() not in ("meera",) or (w.lower() in names and w.lower() != pack.first_name(ctx.person).lower()):
            cands = person_candidates(w)
            if len(cands) > 1 and re.search(r"\bwhich\b", ctx.q.lower()):
                return {"phrase": w, "cands": cands}
    return None


def resolve_ambiguous(ctx: Ctx, cands: list[str]) -> tuple[str | None, list[str]]:
    mine = asker_clients(ctx.conn, ctx.person)
    scores = {}
    ev: dict[str, list[str]] = {c: [] for c in cands}
    for c in cands:
        s = 0
        for r in ctx.conn.execute("SELECT * FROM facts WHERE value_id=?", (c,)):
            if r["client"] in mine and ctx.can(r["record_id"]):
                s += 3
                ev[c].append(r["record_id"])
        for r in ctx.conn.execute("SELECT id, client FROM records WHERE author=? AND client IS NOT NULL", (c,)):
            if r["client"] in mine and ctx.can(r["id"]):
                s += 1
                ev[c].append(r["id"])
        for r in ctx.conn.execute("SELECT id, client FROM records WHERE type='task' AND json_extract(raw,'$.owner')=?", (c,)):
            if r["client"] in mine and ctx.can(r["id"]):
                s += 2
        scores[c] = s
    top = sorted(scores.items(), key=lambda x: -x[1])
    if top[0][1] > 0 and (len(top) == 1 or top[0][1] > top[1][1]):
        return top[0][0], ev[top[0][0]][:2]
    return None, []


# ---------------------------------------------------------------- "what did X say about me"
def said_about_me(ctx: Ctx) -> dict | None:
    m = re.search(r"what did (\w+) (?:say|write|mention|tell\b.*?)\s*(?:about|regarding)\s+me", ctx.q, re.I)
    if not m:
        return None
    speaker = person_candidates(m.group(1))
    me = pack.first_name(ctx.person).lower()
    seen = [r for r in ctx.visible() if r["author"] in speaker and me in tokens(r["raw"].get("body", ""))]
    if seen:
        r = seen[-1]
        return {"answer": {"text": first_sentence(r["raw"]["body"]), "sources": [r["id"]]}, "matched": []}
    hidden = [r for r in ctx.hidden_matching(None, set()) if r["author"] in speaker and me in tokens(r["raw"].get("body", ""))]
    if hidden:
        return {"refused": {"reason": "private"}}
    return {"answer": {"text": "I have nothing on that.", "sources": []}, "matched": []}


# ---------------------------------------------------------------- plain retrieval
def retrieve(ctx: Ctx) -> dict:
    qt = ctx.qterms - {pack.first_name(ctx.person).lower()}
    best, best_s = None, 0.0
    for r in ctx.visible():
        if r["type"] in ("notification", "event") or r["author"] == "system":
            continue
        s = len(qt & terms(r["raw"].get("body", "") + " " + r["raw"].get("title", "")))
        if s >= max(2, min(3, len(qt))) and (s, r["at"]) > (best_s, best["at"] if best else ""):
            best, best_s = r, s
    if not best:
        return {"answer": {"text": "I have nothing on that.", "sources": []}, "matched": []}
    sent = max(sentences(best["raw"]["body"]) or [best["raw"]["body"]], key=lambda x: len(qt & terms(x)))
    return {"answer": {"text": sent[:220], "sources": [best["id"]]}, "matched": []}


# ---------------------------------------------------------------- entry
def _resolve(ctx: Ctx, person: str) -> dict:
    r = said_about_me(ctx)
    if r:
        return (r)
    if pack.org_of(person) != "org_kp":
        return (retrieve(ctx))        # clients, tasks and facts belong to Kitepoint only
    tasks = weekday_tasks(ctx)
    if tasks is not None:
        if len(tasks) > 1:
            return ({"clarify": {"question": "Which one: " + " or ".join(t["title"] for t in tasks) + "?",
                                       "options": [{"id": t["task_id"], "text": t["title"]} for t in tasks]}})
        if len(tasks) == 1:
            t = task_state(ctx, tasks[0]["task_id"])
            return (task_answer(ctx, t, (None, None)))
    amb = person_in_question(ctx)
    client, phrase = client_of_question(ctx)
    if amb:
        pid, src = resolve_ambiguous(ctx, amb["cands"])
        if pid:
            nm = pack.name_of(pid)
            role = pack.people()[pid].get("role", "")
            return ({"answer": {"text": f"That is {nm} ({pid}), {role}.", "sources": src},
                           "matched": [{"phrase": amb["phrase"], "id": pid, "sources": src}] +
                                      ([{"phrase": phrase, "id": client, "sources": []}] if client else [])})
        return ({"clarify": {"question": f"Which {amb['phrase']}?",
                                   "options": [{"id": c, "text": pack.name_of(c)} for c in amb["cands"]]}})
    task, ties = find_task(ctx, client)
    if task:
        if len(ties) > 1:
            return ({"clarify": {"question": "Which one: " + " or ".join(t["raw"]["title"] for t in ties) + "?",
                                       "options": [{"id": t["raw"]["task_id"], "text": t["raw"]["title"]} for t in ties]}})
        return (task_answer(ctx, task, (client, phrase)))
    f = fact_answer(ctx, client)
    if f:
        return (f)
    return (retrieve(ctx))


def _nothing(res: dict) -> bool:
    a = res.get("answer")
    return bool(a) and not a.get("sources") and not res.get("clarify") and not res.get("refused")


def ask(conn, person: str, at: str, question: str) -> dict:
    t0 = time.perf_counter()
    ctx = Ctx(conn, person, at, question)
    out = {"answer": None, "matched": [], "clarify": None, "refused": None}
    res = _resolve(ctx, person)
    if _nothing(res) and pack.org_of(person) == "org_kp" and llm.enabled():
        by_id = {c["id"]: c["name"] for c in pack.clients()}
        rew = llm.canonical_question(question, list(by_id.values())) if by_id else None
        if rew:
            q2, phrase = rew
            res2 = _resolve(Ctx(conn, person, at, q2), person)
            if res2.get("answer") and res2["answer"].get("sources"):
                for m in res2.get("matched") or []:
                    if phrase and by_id.get(m.get("id"), "").lower() == (m.get("phrase") or "").lower():
                        m["phrase"] = phrase
                res = res2
    out.update({k: v for k, v in res.items() if k in out})
    a = out["answer"]
    if a and text_forgotten(person, a["text"], ctx.fsets):
        out.update(answer={"text": "I have nothing on that.", "sources": []}, matched=[])
    out["usage"] = _usage(t0)
    return out
