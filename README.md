# assist: meeting brief helper (BuildSprint R3)

Reads Kitepoint's work day by day, remembers feedback, writes a brief before each meeting and answers short questions. Every line it prints cites the record ids it came from.

## Run

Python 3.10+ and the standard library only. No install step, no API key.

```
python3 my_solution.py ingest --day 1
python3 my_solution.py brief --person p02 --date 2026-11-03
python3 my_solution.py ask --person p02 --at 2026-11-02T18:00:00Z --ask "Who handles billing for NB?"
python3 my_solution.py forget --person p02 --what "Forget what I said about the Dubai trip"
```

With the organisers' harness and scorer (from the pack folder):

```
export R3_PACK=$PWD
python3 tools/run_days.py --cmd "python3 /path/to/my_solution.py" --days 1-5 --out runs/mine
python3 tools/score.py --run runs/mine --days 1-5
```

The pack folder comes from `$R3_PACK`, else the current folder. Memory is one SQLite file, `.assist_store.sqlite`, in the current folder (override with `ASSIST_STORE`). `ingest --day 1` starts a fresh store.

Tests (build a tiny pack and drive the real CLI):

```
python3 -m pytest tests -q
```

## Model and tokens

No language model is used. Every output reports `input_tokens: 0`, `output_tokens: 0`, `cost_usd: 0` and the real time in ms. Nothing is estimated.

## Results on days 1 to 5

With the organisers' scorer: 85 out of 85 (briefs 20/20, answers 15/15, honesty 15/15, memory 15/15, privacy 10/10, cost 10/10; "getting better" needs 6 or more days). I treat this with suspicion: the rules were written while looking at these five days, and the hidden days may contain message shapes I have not seen. `tests/test_generalisation.py` covers cases the five days do not show (see DESIGN_NOTE.md).

## Layout

| File | Job |
|---|---|
| `my_solution.py` | the one command |
| `assist/pack.py` | the only place that knows file layout, people, zones, and `can_see()` |
| `assist/extract.py` | at ingest: records become signals (what changed), promises and facts |
| `assist/memory.py` | corrections, preferences, verdicts, forgets |
| `assist/brief.py` | picks and orders the lines for one meeting |
| `assist/ask.py` | task lookups, client facts, which-person, clarify, refuse, plain retrieval |
| `assist/db.py`, `assist/text.py` | SQLite schema, small text helpers |

## Known gaps

- Messages are understood with regular expressions over the shapes in the pack ("kal tak", "takes over ... from", "move the launch to"). A new phrasing is ignored, not guessed. A model would help most here.
- Nicknames: initials and name prefixes are worked out from client ids. City hints ("London account", "Mumbai client") use a small city-to-country table matched against client contact email domains.
- Internal meetings (no client) always return `nothing_new`.
- Asks outside tasks, billing, launch date and people fall back to keyword search and answer with one sentence from the best record.

## AI assistants used

Claude (Anthropic) helped write the code and tests.
