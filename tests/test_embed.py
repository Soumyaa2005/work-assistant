"""Embedding fallback, tested with a fake embedder (no network)."""
import json

import pytest

from assist import ask as askmod, db, embed
from test_generalisation import CLIENTS, PEOPLE, rec, task
from test_hidden_days import ev, run, setup

CONCEPTS = [("redesign", "revamp", "overhaul"), ("homepage", "landing"), ("pricing", "rates"), ("banner", "hero")]


def fake_post(texts):
    vecs = [[float(sum(w in t.lower() for w in group)) for group in CONCEPTS] for t in texts]
    return vecs, sum(len(t.split()) for t in texts)


@pytest.fixture
def store(tmp_path, monkeypatch):
    d1 = [ev(1, "2026-11-02T03:00:00Z", "2026-11-04T05:30:00Z"),
          task("t1", "2026-11-02T05:00:00Z", "t-home", "Homepage redesign", "p03", "2026-11-12", "in_progress", "created"),
          task("t2", "2026-11-02T05:00:00Z", "t-banner", "Banner set", "p03", "2026-11-12", "todo", "created"),
          rec("t3", "task", "2026-11-02T05:00:00Z", "p01", "northbeam", "x", vis="restricted", readers=["p01"],
              task_id="t-price", title="Pricing overhaul", owner="p01", due="2026-11-20", status="todo", change={"field": "created"})]
    setup(tmp_path, {1: d1}, {})
    run(tmp_path, "ingest", "--day", "1")
    monkeypatch.setenv("R3_PACK", str(tmp_path))
    monkeypatch.setenv("ASSIST_STORE", str(tmp_path / "s.sqlite"))
    for k in ("GROQ_API_KEY", "ASSIST_LLM_KEY", "OPENAI_API_KEY", "EMBED_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(embed, "_post_embed", fake_post)
    monkeypatch.setattr(embed, "USAGE", {"input_tokens": 0, "cost_usd": 0.0, "ms": 0, "calls": 0})
    monkeypatch.setattr(embed, "_state", {"fails": 0})
    return db.connect()


def q(conn, text, person="p02"):
    return askmod.ask(conn, person, "2026-11-03T00:00:00Z", text)


def test_off_without_key_means_nothing(store, monkeypatch):
    monkeypatch.delenv("EMBED_API_KEY", raising=False)
    assert q(store, "Who owns the landing page revamp?")["answer"]["sources"] == []


def test_synonym_question_finds_the_task(store, monkeypatch):
    monkeypatch.setenv("EMBED_API_KEY", "k")
    out = q(store, "Who owns the landing page revamp?")
    assert out["answer"]["sources"] == ["t1"] and "Chris Doe" in out["answer"]["text"]
    assert out["usage"]["input_tokens"] > 0


def test_vectors_are_cached(store, monkeypatch):
    monkeypatch.setenv("EMBED_API_KEY", "k")
    q(store, "Who owns the landing page revamp?")
    calls = embed.USAGE["calls"]
    q(store, "Who owns the landing page revamp?")
    assert embed.USAGE["calls"] == calls


def test_task_the_asker_cannot_see_is_never_matched(store, monkeypatch):
    monkeypatch.setenv("EMBED_API_KEY", "k")
    out = q(store, "Who owns the rates work?", "p02")
    assert "Pricing" not in json.dumps(out) and out["answer"]["sources"] == []
    assert "Pricing overhaul" in json.dumps(q(store, "Who owns the pricing overhaul?", "p01"))


def test_weak_match_stays_silent(store, monkeypatch):
    monkeypatch.setenv("EMBED_API_KEY", "k")
    assert q(store, "Who owns the cafeteria menu?")["answer"]["sources"] == []


def test_not_a_task_question_is_ignored(store, monkeypatch):
    monkeypatch.setenv("EMBED_API_KEY", "k")
    assert q(store, "Tell me about the landing page revamp")["answer"]["sources"] == []


def test_api_failure_falls_back_to_rules(store, monkeypatch):
    monkeypatch.setenv("EMBED_API_KEY", "k")
    monkeypatch.setattr(embed, "_post_embed", lambda t: (_ for _ in ()).throw(OSError("down")))
    assert q(store, "Who owns the landing page revamp?")["answer"]["text"] == "I have nothing on that."
