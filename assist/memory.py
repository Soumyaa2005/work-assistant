"""Feedback, corrections, preferences and forgets. Everything is stored per person."""
import json
import re

from . import pack
from .text import DATE, NUMBER_WORDS, norm_date, stem, terms

_FORGET_NOISE = {"forget", "said", "mention", "mentioned", "everything", "anything", "wrote", "told", "regard", "regarding"}


def forget_terms(words: str) -> set[str]:
    return terms(words) - {stem(w) for w in _FORGET_NOISE}


def add_forget(conn, person: str, words: str) -> bool:
    t = sorted(forget_terms(words))
    if not t:
        return False
    if conn.execute("SELECT 1 FROM forgets WHERE person=? AND words=?", (person, words)).fetchone():
        return False
    conn.execute("INSERT INTO forgets(person,words,terms) VALUES(?,?,?)", (person, words, json.dumps(t)))
    # a forget also removes the person's own stored feedback that carries the topic
    ts = set(t)
    for table in ("prefs", "corrections", "verdicts"):
        for r in conn.execute(f"SELECT id, words FROM {table} WHERE person=?", (person,)).fetchall():
            if ts <= terms(r["words"] or ""):
                conn.execute(f"DELETE FROM {table} WHERE id=?", (r["id"],))
    return True


def forget_sets(conn) -> list[tuple[str, set[str]]]:
    return [(r["person"], set(json.loads(r["terms"]))) for r in conn.execute("SELECT person, terms FROM forgets")]


def _hit(ts: set[str], text_terms: set[str]) -> bool:
    need = len(ts) if len(ts) <= 2 else max(2, len(ts) - 1)
    return len(ts & text_terms) >= need


def is_forgotten(rec: dict, fsets) -> bool:
    """A record is forgotten, for everyone, when its author asked to forget its topic."""
    tt = terms(rec.get("body") or rec.get("raw", {}).get("body", ""))
    return any(rec.get("author") == p and _hit(ts, tt) for p, ts in fsets)


def text_forgotten(person: str, text: str, fsets) -> bool:
    """Output guard: this person asked to forget a topic and the text still carries it."""
    tt = terms(text)
    return any(p == person and ts <= tt for p, ts in fsets)


# ---------------------------------------------------------------- feedback intake
_N = r"(?-i:[A-Z][a-z]+)"
_CORRS = [
    re.compile(r"(?i:(?:\b(?:no|nope|actually|correction)\b[,.:]?\s*)?)(?P<new>" + _N + r")\s+(?i:(?:now\s+)?(?:owns|handles|has|manages|runs|looks\s+after|"
               r"is\s+(?:now\s+)?(?:handling|owning|managing|running|on|the\s+owner\s+of)))\s+(?P<subj>[a-z ]+?)(?i:\s+now)?"
               r"(?=[,.;]|\s+not\b|\s*$)(?:[,.]?\s*(?i:and\s+)?(?i:not)\s+(?P<old>" + _N + r"))?"),
    re.compile(r"(?i)\b(?P<subj>billing)\s+(?:is\s+|goes\s+to\s+|now\s+(?:is\s+)?|is\s+with\s+|now\s+with\s+)(?P<new>" + _N + r")(?:'s)?(?:\s+now)?"
               r"(?:[,.]?\s*not\s+(?P<old>" + _N + r"))?"),
    re.compile(r"(?i)\b(?:it'?s|it\s+is)\s+(?P<new>" + _N + r")[,]?\s+not\s+(?P<old>" + _N + r")[,]?\s+(?:for|on)\s+(?P<subj>[a-z ]+?)\s*[.!]?$"),
]
_NUM_PREF = [
    re.compile(r"\b(?:max(?:imum)?|at most|no more than|only|top|limit(?: to)?|keep (?:it |them )?(?:to|under|within)|just|up to)\s+(\d+|" + "|".join(NUMBER_WORDS) + r")\b", re.I),
    re.compile(r"\b(\d+|" + "|".join(NUMBER_WORDS) + r")\s+(?:items?|bullets?|points?|lines?|things?|changes?)\s+(?:max|at most|tops|only)\b", re.I),
]


def _corr_match(words: str):
    for rx in _CORRS:
        m = rx.search(words)
        if m:
            return m
    return None


def apply_feedback(conn, entries: list[dict]) -> None:
    for e in entries:
        person, day, words = e.get("person"), e.get("day"), e.get("words", "")
        kind = e.get("type")
        if kind == "preference":
            if not conn.execute("SELECT 1 FROM prefs WHERE person=? AND words=?", (person, words)).fetchone():
                conn.execute("INSERT INTO prefs(person,day,words) VALUES(?,?,?)", (person, day, words))
        elif kind == "correction":
            _correction(conn, e)
        elif kind == "verdict":
            conn.execute("INSERT INTO verdicts(person,day,meeting,topic,verdict,words) VALUES(?,?,?,?,?,?)",
                         (person, day, e.get("meeting"), e.get("topic"), e.get("verdict"), words))
        # "forget" lines arrive through the forget command


def _correction(conn, e):
    from .extract import _person   # local import: extract needs pack, not memory
    words, person = e.get("words", ""), e.get("person")
    m = _corr_match(words)
    client = subject = value = vid = None
    d = re.search(r"(?i)\blaunch\b.{0,40}?(" + DATE + r")", words)
    if not m and d and norm_date(d.group(1)):
        subject, value = "launch", norm_date(d.group(1))
        mt = e.get("meeting")
        ev = conn.execute("SELECT client FROM records WHERE type='event' AND json_extract(raw,'$.event_id')=?", (mt,)).fetchone() if mt else None
        client = ev["client"] if ev else None
    if m:
        subject = "billing" if "billing" in m.group("subj").lower() else re.sub(r"\W+", "_", m.group("subj").strip().lower())
        value, vid = _person(m.group("new"), "accounts" if subject == "billing" else None)
        row = conn.execute("SELECT client FROM records WHERE id IN (SELECT record_id FROM facts WHERE subject=?) LIMIT 1",
                           (subject,)).fetchone()
        mt = e.get("meeting")
        if mt:
            ev = conn.execute("SELECT client FROM records WHERE type='event' AND json_extract(raw,'$.event_id')=?", (mt,)).fetchone()
            client = ev["client"] if ev else None
        client = client or (row["client"] if row else None)
    conn.execute("INSERT INTO corrections(person,day,meeting,words,client,subject,value,value_id) VALUES(?,?,?,?,?,?,?,?)",
                 (person, e.get("day"), e.get("meeting"), words, client, subject, value, vid))


# ---------------------------------------------------------------- preference parsing
def person_prefs(conn, person: str) -> dict:
    out = {"max_changed": None, "blockers_first": False, "skip": set()}
    for r in conn.execute("SELECT words FROM prefs WHERE person=? ORDER BY id", (person,)):
        w = r["words"]
        n = None
        for rx in _NUM_PREF:
            mm = rx.search(w)
            if mm:
                v = mm.group(1).lower()
                n = int(v) if v.isdigit() else NUMBER_WORDS[v]
                break
        if n:
            out["max_changed"] = n
        if re.search(r"blocker|blocked", w, re.I) and re.search(r"first|top|start|lead|upfront|up front|front|before", w, re.I):
            out["blockers_first"] = True
        m = re.match(r"\s*(?:skip|ignore|exclude|hide|leave out|stop (?:showing|mentioning|including)|"
                     r"(?:don'?t|do not) (?:show|include|mention|tell me about|bring up)|i (?:don'?t|do not) care about|no)\s+(.+?)"
                     r"(?:\s+in my|\s+from my|\s+please|[.!]|$)", w, re.I)
        if m and not (n and re.match(r"\s*no\b", w, re.I)):
            out["skip"] |= terms(m.group(1))
    return out


def ignored_topics(conn, person: str) -> list[set[str]]:
    return [terms(r["topic"] or "") for r in conn.execute(
        "SELECT topic FROM verdicts WHERE person=? AND verdict='ignored'", (person,)) if r["topic"]]
