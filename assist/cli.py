from __future__ import annotations
import argparse
import json
import sys

from . import brief, db, extract, llm, memory, pack
from .ask import ask


def ingest(day: int) -> dict:
    conn = db.connect(fresh=(day == 1))
    if db.meta_get(conn, f"day{day}"):
        return {"ok": True, "skipped": "already ingested"}
    recs = sorted(pack.day_records(day), key=lambda r: (r["at"], r["id"]))
    for r in recs:
        conn.execute(
            "INSERT OR REPLACE INTO records(id,org,type,at,author,client,visibility,readers,day,raw) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (r["id"], r.get("org", "org_kp"), r["type"], r["at"], r.get("author"), r.get("client"),
             r.get("visibility", "team"), json.dumps(r.get("readers") or []), day, json.dumps(r, ensure_ascii=False)))
    for r in recs:
        extract.derive(conn, r)
    if day > 1:
        memory.apply_feedback(conn, pack.day_feedback(day - 1))   # feedback written on day N-1 arrives now
    db.meta_set(conn, f"day{day}", 1)
    conn.commit()
    out = {"ok": True, "records": len(recs)}
    if llm.USAGE["calls"]:
        out["usage"] = llm.usage()
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="assist")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("ingest"); s.add_argument("--day", type=int, required=True)
    s = sub.add_parser("brief"); s.add_argument("--person", required=True); s.add_argument("--date", required=True)
    s = sub.add_parser("ask"); s.add_argument("--person", required=True); s.add_argument("--at", required=True); s.add_argument("--ask", required=True)
    s = sub.add_parser("forget"); s.add_argument("--person", required=True); s.add_argument("--what", required=True)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "ingest":
            out = ingest(a.day)
        elif a.cmd == "brief":
            conn = db.connect()
            out = brief.briefs(conn, a.person, a.date)
        elif a.cmd == "ask":
            out = ask(db.connect(), a.person, a.at, a.ask)
        else:
            conn = db.connect()
            memory.add_forget(conn, a.person, a.what)
            conn.commit()
            out = {"ok": True}
    except Exception as e:                       # never break the harness: print valid JSON, log to stderr
        print(f"assist error: {e!r}", file=sys.stderr)
        out = [] if a.cmd == "brief" else {"ok": False, "error": str(e)}
        if a.cmd == "ask":
            out = {"answer": None, "matched": [], "clarify": None, "refused": None,
                   "usage": {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "ms": 0}}
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
