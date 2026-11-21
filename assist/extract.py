"""Turns raw records into signals (what changed), promises, and facts, once, at ingest.

Rules are tight regexes over the pack's message shapes. Free text that no rule recognises is
simply not a signal (and is never quoted), which keeps injected text out of briefs.
"""
import json
import re

from . import pack
from .text import INJECTION, cap

_PERSON_NAMES = None


def _candidates(first: str, prefer_team: str | None = None) -> list[str]:
    ids = [p["id"] for p in pack.people().values()
           if p["org"] == "org_kp" and p["name"].split()[0].lower() == first.lower()]
    if len(ids) > 1 and prefer_team:
        narrowed = [i for i in ids if pack.people()[i].get("team") == prefer_team]
        ids = narrowed or ids
    return ids


def _person(first: str, prefer_team: str | None = None) -> tuple[str, str | None]:
    """First name -> (display name, id). Ambiguous names stay as typed unless a team hint settles it."""
    ids = _candidates(first, prefer_team)
    if len(ids) == 1:
        return pack.name_of(ids[0]), ids[0]
    return first, None


def add_signal(conn, rec, kind, subject, prio, text, old=None, new=None, what=None):
    conn.execute(
        "INSERT INTO signals(record_id,client,kind,subject,prio,at,old,new,text,what) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (rec["id"], rec.get("client"), kind, subject, prio, rec["at"], old, new, text, what))


def add_fact(conn, rec, subject, value, value_id=None, at=None):
    conn.execute("INSERT INTO facts(client,subject,value,value_id,at,record_id) VALUES(?,?,?,?,?,?)",
                 (rec.get("client"), subject, value, value_id, at or rec["at"], rec["id"]))


def current_fact(conn, client, subject, before=None):
    q = "SELECT * FROM facts WHERE client=? AND subject=?"
    args = [client, subject]
    if before:
        q += " AND at<=?"
        args.append(before)
    r = conn.execute(q + " ORDER BY at DESC, id DESC LIMIT 1", args).fetchone()
    return dict(r) if r else None


# ---------------------------------------------------------------- tasks
def _task(conn, rec):
    raw = rec
    ch = raw.get("change") or {}
    field, title, tid = ch.get("field"), raw.get("title", "a task"), raw.get("task_id")
    subj = f"task:{tid}"
    if field == "owner":
        add_signal(conn, rec, "owner", subj, 2,
                   f"{title} now owned by {pack.name_of(ch.get('to'))} (was {pack.name_of(ch.get('from'))})",
                   ch.get("from"), ch.get("to"), title)
    elif field == "due":
        add_signal(conn, rec, "due", subj, 2,
                   f"{title} due date moved from {pack.fmt_day(ch['from'])} to {pack.fmt_day(ch['to'])}",
                   ch.get("from"), ch.get("to"), title)
    elif field == "status":
        new, old, body = ch.get("to"), ch.get("from"), (raw.get("body") or "").strip()
        if new == "done":
            add_signal(conn, rec, "done", subj, 2, f"{title} is done", old, new, title)
        elif new == "blocked":
            reason = re.sub(r"^blocked:\s*", "", body, flags=re.I).rstrip(".")
            why = f" ({reason[:1].lower() + reason[1:]})" if reason and reason.lower() != "blocked" else ""
            add_signal(conn, rec, "blocked", subj, 1, f"{title} is blocked{why}", old, new, title)
        elif new == "cancelled":
            add_signal(conn, rec, "cancelled", subj, 2, f"{title} was cancelled ({body.rstrip('.').lower()})" if body
                       else f"{title} was cancelled", old, new, title)
        elif old == "blocked":
            add_signal(conn, rec, "unblocked", subj, 2, f"{title} is unblocked", old, new, title)


# ---------------------------------------------------------------- notes
_KEYED = re.compile(r"^(decision|action|risk|blocker|date|update)\s*:\s*(.+)$", re.I)


def _note(conn, rec):
    lines = [l.strip() for l in rec["body"].split("\n") if l.strip()]
    for line in lines[1:-1] if len(lines) > 2 else lines[1:]:
        m = _KEYED.match(line)
        if m:
            text = cap(m.group(2).rstrip("."))
            add_signal(conn, rec, "decision", f"note:{text.lower()[:40]}", 1, text, what=text)
        else:
            add_signal(conn, rec, "note_item", f"note:{line.lower()[:40]}", 3, line.rstrip("."), what=line)


# ---------------------------------------------------------------- docs and sheets
_KV = re.compile(r"^([A-Za-z][A-Za-z ]{2,30}):\s*(.+?)\.?$")


def _subject_key(key: str) -> str:
    k = key.lower()
    if "billing" in k:
        return "billing"
    if "launch" in k:
        return "launch"
    return re.sub(r"\W+", "_", k).strip("_")


def _norm_val(v: str) -> str:
    m = re.match(r"^(\d{1,2}\s+[A-Za-z]{3})[a-z]*(\s+\d{4})?$", v.strip())
    return m.group(1) if m else v.strip()


def _doc_pairs(body: str) -> dict[str, tuple[str, str]]:
    out = {}
    for line in body.split("\n")[1:5]:
        m = _KV.match(line.strip())
        if m:
            out[_subject_key(m.group(1))] = (m.group(1).strip(), _norm_val(m.group(2)))
    return out


def _doc(conn, rec):
    prev = conn.execute("SELECT raw FROM records WHERE type='doc' AND json_extract(raw,'$.doc_id')=? AND id!=? "
                        "AND at<? ORDER BY at DESC LIMIT 1", (rec.get("doc_id"), rec["id"], rec["at"])).fetchone()
    old = _doc_pairs(json.loads(prev["raw"])["body"]) if prev else {}
    for subj, (label, val) in _doc_pairs(rec["body"]).items():
        if old.get(subj, (None, None))[1] == val:
            continue                       # unchanged line is not a new assertion
        vid = None
        if subj == "billing":
            m = re.match(r"([A-Z][a-z]+)\s+[A-Z][a-z]+", val)
            if m:
                _, vid = _person(m.group(1), "accounts")
        add_fact(conn, rec, subj, val, vid)
        if subj in old:
            was = old[subj][1]
            if subj == "launch":
                add_signal(conn, rec, "date", "launch", 1, f"Launch moved from {was} to {val}", was, val, "launch")
            elif subj == "billing":
                add_signal(conn, rec, "owner", "billing", 1, f"Billing contact changed from {was} to {val}", was, val, "billing")
            else:
                add_signal(conn, rec, "doc_fact", subj, 2, f"{label} changed from {was} to {val}", was, val, label)


def _sheet(conn, rec):
    prev = conn.execute("SELECT raw FROM records WHERE type='sheet' AND json_extract(raw,'$.sheet_id')=? AND id!=? "
                        "AND at<? ORDER BY at DESC LIMIT 1", (rec.get("sheet_id"), rec["id"], rec["at"])).fetchone()
    if not prev:
        return
    old = json.loads(prev["raw"]).get("cells") or {}
    for cell, val in (rec.get("cells") or {}).items():
        if cell in old and old[cell] != val:
            add_signal(conn, rec, "sheet", f"sheet:{rec.get('sheet_id')}:{cell}", 3,
                       f"{rec.get('name', 'Sheet')}: {cell} changed from {old[cell]} to {val}", old[cell], val, rec.get("name"))


# ---------------------------------------------------------------- chat and mail
_TAKEOVER = re.compile(r"([A-Z][a-z]+)\s+takes over\s+(.+?)\s+from\s+([A-Z][a-z]+)")
_MOVE = re.compile(r"\b(?:move|moving|moved|push|pushing|pushed|shift|shifting)\s+the\s+([a-z]+(?: [a-z]+)?)\s+to\s+(\d{1,2}\s+[A-Z][a-z]{2})")
_DELIVER = re.compile(r"^Sharing\s+(.+?)\s+as promised", re.I)
_P_KAL = re.compile(r"^(?P<what>.+?)\s+(?P<w>kal|parso|aaj)\s+tak\b", re.I)
_P_NEXT = re.compile(r"^(?P<what>.+?)\s+next\s+(?P<wd>[A-Za-z]+)\s+tak\b", re.I)
_P_EOD = re.compile(r"\bwill\s+(?:share|send|deliver)\s+(?P<what>.+?)\s+by\s+EOD\s+(?P<w>today|tomorrow)", re.I)
_P_BY = re.compile(r"\bI\s+will\s+(?:share|send|deliver)\s+(?P<what>.+?)\s+by\s+(?P<wd>[A-Za-z]+)\b", re.I)


def _promise_due(rec, m) -> str | None:
    d0 = pack.local_date(rec["at"], rec["author"]) if rec["author"] in pack.people() else pack.parse_ts(rec["at"]).date()
    gd = m.groupdict()
    w = (gd.get("w") or "").lower()
    if w in ("kal", "tomorrow"):
        return str(d0.fromordinal(d0.toordinal() + 1))
    if w == "parso":
        return str(d0.fromordinal(d0.toordinal() + 2))
    if w in ("aaj", "today"):
        return str(d0)
    wd = gd.get("wd")
    if wd:
        nd = pack.next_weekday(d0, wd, strictly_after="next" in m.group(0).lower())
        return str(nd) if nd else None
    return None


def _msg(conn, rec):
    body = (rec.get("body") or "").strip()
    client = rec.get("client")
    if not client or body.endswith("?"):
        return
    m = _TAKEOVER.search(body)
    if m:
        new_name, new_id = _person(m.group(1), "accounts")
        old_name, _ = _person(m.group(3), "accounts")
        subj_text = m.group(2).strip()
        subj = "billing" if "billing" in subj_text.lower() else re.sub(r"\W+", "_", subj_text.lower())
        add_fact(conn, rec, subj, new_name, new_id)
        add_signal(conn, rec, "owner", subj, 1, f"{new_name} now owns {subj_text} (was {old_name})", old_name, new_name, subj)
    m = _MOVE.search(body)
    if m:
        what = m.group(1).lower()
        subj = "launch" if "launch" in what else re.sub(r"\W+", "_", what)
        new = m.group(2)
        cur = current_fact(conn, client, subj, rec["at"])
        old = cur["value"] if cur else None
        text = f"{cap(what)} moved from {old} to {new}" if old else f"{cap(what)} moved to {new}"
        add_fact(conn, rec, subj, new)
        add_signal(conn, rec, "date", subj, 1, text, old, new, what)
    m = _DELIVER.match(body)
    if m:
        what = m.group(1).strip()
        row = conn.execute("SELECT id FROM promises WHERE client=? AND delivered_by IS NULL AND lower(what)=? AND owner=? "
                           "ORDER BY at LIMIT 1", (client, what.lower(), rec["author"])).fetchone()
        if row:
            conn.execute("UPDATE promises SET delivered_by=? WHERE id=?", (rec["id"], row["id"]))
        add_signal(conn, rec, "delivered", f"delivered:{what.lower()}", 3,
                   f"{pack.first_name(rec['author'])} delivered {what}", None, None, what)
    for rx in (_P_KAL, _P_NEXT, _P_EOD, _P_BY):
        m = rx.search(body)
        if m:
            due = _promise_due(rec, m)
            what = m.group("what").strip(" ,.")
            if due and what:
                conn.execute("INSERT INTO promises(record_id,owner,what,due,client,at) VALUES(?,?,?,?,?,?)",
                             (rec["id"], rec["author"], what, due, client, rec["at"]))
            break


# ---------------------------------------------------------------- entry point
def derive(conn, rec: dict) -> None:
    if INJECTION.search(rec.get("body") or "") or str(rec.get("author", "")).startswith("ext:unknown"):
        conn.execute("UPDATE records SET suspect=1 WHERE id=?", (rec["id"],))
        return
    if rec["org"] != "org_kp":
        return
    t = rec["type"]
    if t == "task":
        _task(conn, rec)
    elif t == "note":
        _note(conn, rec)
    elif t == "doc":
        _doc(conn, rec)
    elif t == "sheet":
        _sheet(conn, rec)
    elif t in ("chat", "mail"):
        _msg(conn, rec)
