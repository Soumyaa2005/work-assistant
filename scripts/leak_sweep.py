"""Leak sweep on a real pack: for every private or restricted record, check that its sentences never appear in
any brief or answer given to a person who may not read it.

    R3_PACK=/path/to/pack python3 scripts/leak_sweep.py [--days 5]
"""
import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("ASSIST_STORE", os.path.join(tempfile.mkdtemp(), "sweep.sqlite"))
for k in ("GROQ_API_KEY", "OPENAI_API_KEY", "ASSIST_LLM_KEY", "EMBED_API_KEY"):
    os.environ.pop(k, None)

from assist import ask as askmod, brief, cli, db, pack      # noqa: E402


def sentences(body):
    return [s.strip() for s in re.split(r"[.\n!?]+", body or "") if len(s.split()) >= 4]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=5)
    n = ap.parse_args().days
    for d in range(1, n + 1):
        cli.ingest(d)
    conn = db.connect()
    secrets = []
    for r in conn.execute("SELECT * FROM records WHERE visibility!='team' OR org!='org_kp'"):
        rec = db.rec_dict(r)
        for s in sentences(rec["raw"].get("body")):
            secrets.append((rec, s.lower()))
    people = sorted(pack.people())
    dates = sorted({str(pack.local_date(json.loads(r["raw"])["start"], p)) for r in conn.execute("SELECT raw FROM records WHERE type='event'")
                    for p in people[:1]}) or []
    dates = sorted({d for d in dates} | {f"2026-11-{x:02d}" for x in range(2, 12)})
    titles = sorted({json.loads(r["raw"])["title"] for r in conn.execute("SELECT raw FROM records WHERE type='task'")})
    questions = [f"{w} {t}?" for t in titles for w in ("Who owns the", "When is the", "What's the status of the")]
    questions += ["Who owns billing for Northbeam?", "Who owns billing for Cobaltline?", "When is the Northbeam launch?",
                  "What did Meera say about me?", "When is my Dubai trip?", "What is the latest on churn?"]
    leaks, checked = [], 0
    for p in people:
        outputs = []
        for d in dates:
            outputs.append(json.dumps(brief.briefs(conn, p, d)).lower())
        for q in questions:
            outputs.append(json.dumps(askmod.ask(conn, p, "2026-11-12T00:00:00Z", q)).lower())
        blob = "\n".join(outputs)
        for rec, s in secrets:
            if pack.can_see(p, rec):
                continue
            checked += 1
            if s in blob:
                leaks.append((p, rec["id"], s))
    print(f"{len(secrets)} private/restricted/other-company sentences, {len(people)} people, {checked} pair checks")
    for p, rid, s in leaks[:20]:
        print("LEAK", p, rid, s)
    print("RESULT:", "LEAKS FOUND" if leaks else "no leaks found")
    return 1 if leaks else 0


if __name__ == "__main__":
    sys.exit(main())
