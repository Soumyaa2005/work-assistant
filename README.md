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

## Demo page

```
python3 ui.py --pack /path/to/BuildSprint-R3-candidate
```

Opens http://127.0.0.1:8765 (standard library only). Pick a person, ingest through a day, then get a brief, ask, forget, or compare the same question for two people. Every button runs the real CLI, cited record ids are clickable (a record the person may not see shows as hidden), and a panel shows what is remembered for that person and the session's token total. It is a demo aid only; the scored program is `my_solution.py`.

## Model and tokens

The rules do all the work by default. There is an optional model fallback for wording the rules do not know, off unless you set a key:

```
export GROQ_API_KEY=your-key
```

- Model: `openai/gpt-oss-20b` on Groq (OpenAI-compatible API, standard library `urllib`, nothing to install). Change with `ASSIST_LLM_MODEL`, `ASSIST_LLM_URL`. `ASSIST_LLM=0` switches it off even with a key set.
- It is only called when the rules found nothing: a chat or mail that looks like a handover, date move, delivery or promise; a preference or correction the rules could not read; a question the rules could not answer. Records flagged as prompt injection never reach it.
- It never answers and never writes facts or citations. It rewrites the text into short canonical sentences, each line is checked so that every name, date and content word comes from the original text, and then the same rules read it. Citations always point at the real record. A question rewrite only widens what the rules look up; the asker's visibility checks still apply.
- Tokens: counted from the API's `usage` (prompt and completion tokens), summed per process. If the API gives none, characters / 4. Cost uses Groq's list price, $0.075 per million input and $0.30 per million output tokens (`ASSIST_PRICE_IN`, `ASSIST_PRICE_OUT` to change; check the current price). `ask` reports its own tokens in `usage`. `ingest` reports any tokens it used in an extra `usage` field. Replies read from the local cache (`.assist_llm_cache.json`) cost nothing and report 0.
- At most 80 model calls per process, 8 second timeout. After two failures in a process it stops trying and answers with rules only.
- No key: every call reports 0 tokens, because no model ran.
- No key is stored in the repo.

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

- Messages are understood with regular expressions ("kal tak", "takes over ... from", "move the launch to", and many variants). A phrasing that neither the rules nor the optional model fallback can ground in the text is ignored, not guessed. The fallback has only been tested against a fake model, not the live API.
- Nicknames: initials and name prefixes are worked out from client ids. City hints ("London account", "Mumbai client") use a small city-to-country table matched against client contact email domains.
- Internal meetings (no client) always return `nothing_new`.
- Asks outside tasks, billing, launch date and people fall back to keyword search and answer with one sentence from the best record.

## AI assistants used

Claude (Anthropic) helped write the code and tests. The optional runtime fallback uses gpt-oss-20b via Groq.

## Optional embeddings (semantic matching)

Off unless `EMBED_API_KEY` is set. It does one job: when no task title shares enough words with a "who / when / status" question, the titles of the tasks the asker may already see are ranked by embedding similarity (`assist/embed.py`).

```
export EMBED_API_KEY=your-key      # any OpenAI-compatible /embeddings endpoint
```

- Defaults: `EMBED_URL` (OpenAI), `EMBED_MODEL=text-embedding-3-small`. `ASSIST_EMBED=0` switches it off.
- Vectors are cached in the SQLite store (table `embeddings`), so a text is embedded once. Cosine similarity is computed in plain Python; the candidate set is tiny, so no separate vector database is needed.
- Candidates are built after the visibility check, so a task the asker cannot see is never embedded or matched. A weak match (below `EMBED_MIN_SCORE`) or a near tie (within `EMBED_MIN_GAP`) returns nothing or asks which one, never a guess.
- Embedding tokens are added to the `usage` of the `ask` that used them (price `EMBED_PRICE_IN`, per million tokens; check the current price). At most 20 calls per process; after two failures it stops and the rules answer alone.
- Not used for briefs, ingest or forget, and not needed for the scored days. Tests use a fake embedder (`tests/test_embed.py`), so no network is needed.
