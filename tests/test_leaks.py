"""Data-leak regressions. A private or restricted record must never shape what another person is shown,
including through derived text ("moved from X to Y"), document history, delivered promises and the model."""
import json

from assist import cli, db, extract
from test_generalisation import rec, run
from test_hidden_days import ev, setup


def brief(pack, person, date="2026-11-04"):
    return run(pack, "brief", "--person", person, "--date", date)[0]


def lines(b):
    return " | ".join(c["text"] for c in b["changed"])


def base(extra2, extra1=()):
    d1 = [ev(1, "2026-11-02T03:00:00Z", "2026-11-04T05:30:00Z"),
          rec("doc", "doc", "2026-11-02T03:00:00Z", "p01", "northbeam", "Plan.\nLaunch date: 10 Nov 2026.\nBilling owner: Kavya.\nx",
              doc_id="d", version=1, title="Plan"), *extra1]
    return {1: d1, 2: list(extra2)}


def go(tmp, days):
    setup(tmp, days, {})
    run(tmp, "ingest", "--day", "1")
    run(tmp, "ingest", "--day", "2")


def test_private_date_move_is_not_the_old_value_in_a_public_line(tmp_path):
    go(tmp_path, base([rec("priv", "chat", "2026-11-03T05:00:00Z", "p03", "northbeam", "Launch pushed to 14 Nov. Keep this between us.", vis="private"),
                       rec("pub", "chat", "2026-11-03T06:00:00Z", "p01", "northbeam", "Launch moved to 20 Nov.")]))
    text = lines(brief(tmp_path, "p02"))
    assert "14 Nov" not in text and "Launch moved from 10 Nov to 20 Nov" in text


def test_private_takeover_does_not_leak_as_was(tmp_path):
    go(tmp_path, base([rec("priv", "chat", "2026-11-03T05:00:00Z", "p03", "northbeam", "Chris is taking over billing from Kavya. Keep quiet.", vis="private"),
                       rec("pub", "chat", "2026-11-03T06:00:00Z", "p01", "northbeam", "Arjun is taking over billing.")]))
    text = lines(brief(tmp_path, "p02"))
    assert "Chris" not in text and "Arjun" in text


def test_restricted_document_history_does_not_leak(tmp_path):
    secret = rec("d2", "doc", "2026-11-03T05:00:00Z", "p01", "northbeam", "Plan.\nLaunch date: 31 Dec 2026.\nx",
                 vis="restricted", readers=["p01"], doc_id="d", version=2, title="Plan")
    team = rec("d3", "doc", "2026-11-03T06:00:00Z", "p01", "northbeam", "Plan.\nLaunch date: 20 Nov 2026.\nx",
               doc_id="d", version=3, title="Plan")
    go(tmp_path, base([secret, team]))
    assert "31 Dec" not in json.dumps(brief(tmp_path, "p02"))


def test_private_delivery_does_not_close_a_public_promise(tmp_path):
    go(tmp_path, base([rec("p", "chat", "2026-11-03T05:00:00Z", "p03", "northbeam", "I'll send the pricing sheet by Friday."),
                       rec("d", "mail", "2026-11-03T06:00:00Z", "p03", "northbeam", "Sharing the pricing sheet as promised.", vis="private"),
                       rec("pub", "chat", "2026-11-03T07:00:00Z", "p01", "northbeam", "Launch moved to 20 Nov.")]))
    assert any("pricing sheet" in p["what"] for p in brief(tmp_path, "p02")["promises"])


def test_model_never_sees_private_or_restricted_records(tmp_path, monkeypatch):
    setup(tmp_path, base([rec("a", "chat", "2026-11-03T05:00:00Z", "p03", "northbeam", "Kavya ab billing sambhalegi, bas tumhe bata raha hoon.", vis="private"),
                          rec("b", "chat", "2026-11-03T05:10:00Z", "p01", "northbeam", "Kavya ab billing sambhalegi, restricted.", vis="restricted", readers=["p01"]),
                          rec("c", "chat", "2026-11-03T05:20:00Z", "p01", "northbeam", "Kavya ab billing sambhalegi, sabko pata hai.")]), {})
    monkeypatch.setenv("R3_PACK", str(tmp_path))
    monkeypatch.setenv("ASSIST_STORE", str(tmp_path / "s.sqlite"))
    sent = []
    monkeypatch.setattr(extract.llm, "enabled", lambda: True)
    monkeypatch.setattr(extract.llm, "canonical_message", lambda body, when: sent.append(body) or [])
    cli.ingest(1)
    cli.ingest(2)
    assert sent == ["Kavya ab billing sambhalegi, sabko pata hai."]


def test_nothing_of_ours_reaches_the_other_company(tmp_path):
    go(tmp_path, base([rec("pub", "chat", "2026-11-03T07:00:00Z", "p01", "northbeam", "Launch moved to 20 Nov.")]))
    assert run(tmp_path, "brief", "--person", "q01", "--date", "2026-11-04") == []
    out = run(tmp_path, "ask", "--person", "q01", "--at", "2026-11-05T00:00:00Z", "--ask", "When is the Northbeam launch?")
    assert "Nov" not in json.dumps(out["answer"]) and out["answer"]["sources"] == []
