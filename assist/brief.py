"""Pre-meeting briefs. Every line is built from a signal and cites the record it came from."""
import json
import time
from datetime import date

from . import pack
from .db import rec_dict
from .memory import forget_sets, ignored_topics, is_forgotten, person_prefs, text_forgotten
from .text import terms

BRIEF_CAP = 12     # when the person has set no limit


def _usage(t0):
    return {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "ms": int((time.perf_counter() - t0) * 1000)}


def meetings_on(conn, person: str, day: str) -> list[dict]:
    out = []
    for r in conn.execute("SELECT * FROM records WHERE type='event' ORDER BY json_extract(raw,'$.start')"):
        rec = rec_dict(r)
        raw = rec["raw"]
        if person not in (raw.get("attendees") or []) and rec["author"] != person:
            continue
        if not pack.can_see(person, rec):
            continue
        if str(pack.local_date(raw["start"], person)) == day:
            out.append(rec)
    return out


def window_start(conn, person: str, meeting: dict) -> str:
    """Local midnight of the person's previous meeting with this client, else the beginning of time."""
    start = meeting["raw"]["start"]
    best = None
    for r in conn.execute("SELECT * FROM records WHERE type='event' AND client IS ?", (meeting["client"],)):
        raw = json.loads(r["raw"])
        if raw["event_id"] == meeting["raw"]["event_id"] or person not in (raw.get("attendees") or []):
            continue
        same_day = pack.local_date(raw["start"], person) >= pack.local_date(start, person)
        if raw["start"] < start and not same_day and (best is None or raw["start"] > best):
            best = raw["start"]
    return pack.local_midnight_utc(pack.local_date(best, person), person) if best else "0000"


def _coalesce(sigs: list[dict]) -> list[dict]:
    """One line per subject+kind. Same new value twice: keep the first report. New value: chain old->latest."""
    groups: dict[tuple, dict] = {}
    for s in sorted(sigs, key=lambda x: (x["at"], x["id"])):
        key = (s["subject"], s["kind"])
        g = groups.get(key)
        if g is None:
            groups[key] = dict(s)
        elif s["new"] == g["new"]:
            continue
        else:
            first_old = g["old"]
            g.update(s)
            g["old"] = first_old
            if s["kind"] == "due" and first_old:
                title = s["what"]
                g["text"] = f"{title} due date moved from {pack.fmt_day(first_old)} to {pack.fmt_day(s['new'])}"
            elif s["kind"] == "owner" and s["subject"].startswith("task:") and first_old:
                g["text"] = f"{s['what']} now owned by {pack.name_of(s['new'])} (was {pack.name_of(first_old)})"
            elif s["kind"] == "date" and first_old:
                g["text"] = f"{s['what'].capitalize()} moved from {first_old} to {s['new']}"
    # a task cannot be both blocked and done: keep the latest status-like line
    latest_status: dict[str, dict] = {}
    for g in groups.values():
        if g["kind"] in ("done", "blocked", "cancelled", "unblocked"):
            cur = latest_status.get(g["subject"])
            if cur is None or (g["at"], g["id"]) > (cur["at"], cur["id"]):
                latest_status[g["subject"]] = g
    return [g for g in groups.values()
            if g["kind"] not in ("done", "blocked", "cancelled", "unblocked") or latest_status.get(g["subject"]) is g]


def _question(top: dict | None) -> dict | None:
    if not top:
        return None
    what, k = top.get("what") or "this", top["kind"]
    q = {
        "blocked": f"What do you need from us to unblock {what}?",
        "date": f"Can {what} still be ready on the new date?",
        "due": f"Can {what} still be delivered by the new date?",
        "owner": f"Does the new owner have everything needed to take over {what}?",
        "done": f"Is {what} signed off, and what comes next?",
        "decision": f"Does the team agree this is final: {top['text'][:80]}?",
        "cancelled": f"Is anything else affected now that {what} is cancelled?",
    }.get(k, f"Anything to confirm about: {top['text'][:80]}?")
    return {"text": q, "sources": [top["record_id"]]}


def brief_for(conn, person: str, meeting: dict) -> dict:
    t0 = time.perf_counter()
    mid = meeting["raw"]["event_id"]
    client = meeting["client"]
    empty = {"meeting_id": mid, "status": "nothing_new", "changed": [], "promises": [], "open_these": [],
             "question_to_ask": None, "usage": _usage(t0)}
    if not client:
        return empty
    prefs = person_prefs(conn, person)
    fsets = forget_sets(conn)
    ign = ignored_topics(conn, person)
    start = window_start(conn, person, meeting)

    def ok(rec_id: str) -> bool:
        r = conn.execute("SELECT * FROM records WHERE id=?", (rec_id,)).fetchone()
        rec = rec_dict(r)
        return pack.can_see(person, rec) and not rec["suspect"] and not is_forgotten(rec, fsets)

    sigs = []
    for r in conn.execute("SELECT * FROM signals WHERE client=? AND at>? ORDER BY at", (client, start)):
        s = dict(r)
        tt = terms(s["text"])
        if not ok(s["record_id"]):
            continue
        if prefs["skip"] and prefs["skip"] & tt and s["kind"] != "blocked":
            continue
        if any(t and len(t & tt) >= min(2, len(t)) for t in ign):
            continue
        if text_forgotten(person, s["text"], fsets):
            continue
        sigs.append(s)
    lines = _coalesce(sigs)
    order = lambda g: (0 if (prefs["blockers_first"] and g["kind"] == "blocked") else 1, g["prio"], _neg(g["at"]), g["id"])
    lines.sort(key=order)
    limit = prefs["max_changed"] or BRIEF_CAP
    lines = lines[:limit]

    promises = []
    for r in conn.execute("SELECT * FROM promises WHERE client=? AND delivered_by IS NULL ORDER BY due", (client,)):
        if ok(r["record_id"]):
            promises.append({"owner": r["owner"], "what": r["what"], "due": r["due"], "sources": [r["record_id"]]})

    if not lines:
        return {**empty, "promises": []} if not promises else {**empty, "promises": []}

    opens, seen = [], set()
    for g in lines:
        if g["record_id"] not in seen and len(opens) < 3:
            seen.add(g["record_id"])
            opens.append({"record": g["record_id"], "why": g["text"][:100]})
    return {"meeting_id": mid, "status": "brief",
            "changed": [{"text": g["text"], "sources": [g["record_id"]]} for g in lines],
            "promises": promises, "open_these": opens, "question_to_ask": _question(lines[0]),
            "usage": _usage(t0)}


def _neg(ts: str) -> str:
    """Sort key that puts newer timestamps first inside an ascending sort."""
    return "".join(chr(0x7E - (ord(c) - 0x20)) if 0x20 <= ord(c) <= 0x7E else c for c in ts)


def briefs(conn, person: str, day: str) -> list[dict]:
    return [brief_for(conn, person, m) for m in meetings_on(conn, person, day)]
