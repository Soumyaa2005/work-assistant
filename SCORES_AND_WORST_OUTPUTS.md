# My scores (days 1 to 5) and my three worst outputs

Run with the organisers' `tools/run_days.py` and `tools/score.py`, rules only (no model key) and again with a model key set. Same result both times.

| Area | Score | Points |
|---|---|---|
| Right briefs | 1.00 | 20 / 20 |
| Right answers | 1.00 | 15 / 15 |
| Honesty | 1.00 | 15 / 15 |
| Memory | 1.00 | 15 / 15 |
| Privacy | 1.00 | 10 / 10 |
| Getting better | n/a (needs 6+ scored days) | - |
| Cost | 1.00 | 10 / 10 |
| Total | | 85.0 / 85, plus the design note |

Per day, briefs / answers / honesty / cost were 1.00 on every day, 1 to 5 (day 5 has no briefs).

The scorer gives every item 1.00, so "worst" below means the outputs I would be least happy to show a real user. I picked them by reading my output next to the answer key, not from the score.

## 1. Day 4, brief ev-nb-ne-05: too long

My brief had 12 changed lines. The key lists 8 changes and 2 optional ones. The extra lines are real changes, so the scorer does not penalise them, but nobody wants to read 12 lines before a meeting. One of them, "Store locator page was cancelled (dropped per client decision)", is not in the key at all.

Cause: with no stated limit I cap a brief at 12 (`BRIEF_CAP` in `assist/brief.py`) and sort by importance, and a cancelled task still ranks fairly high.

What I would change: lower the default cap to about 8, and rank cancelled items below owner and date changes. A person who sets "max N" already gets exactly that.

## 2. Day 3, brief ev-nb-me-04: same problem, same extra line

10 lines against 6 in the key, and the same extra "Store locator page was cancelled" line. This is the same weakness as the first one, so I count it as one finding seen twice. It shows up on two different days.

## 3. The "question to ask" is a template

Every brief ends with one suggested question, built from a fixed sentence per kind of change, for example "Is TMS data pipeline signed off, and what comes next?". On day 2 two different people meeting the same client got the identical question. It is cited and correct, but it is generic, and it is not scored.

What I would change: pick the question from the most important change for that person's role, or leave it out when I have nothing specific to ask.

## Weak spots I know of but could not show in the scores

- Wording my rules have not seen is silently missed. I widened the rules and tested with sentences I made up. The optional model catches some of the rest, but I cannot measure the hidden days.
- Meetings with no client always return `nothing_new`.
- Leave and expiry are not handled; I found no example in the visible data.
- A forget hides what the forgetter wrote, not a teammate's note on the same topic.
- The "Skip newsletters" preference has no visible effect on days 1 to 5, because newsletters never become changes in the first place.
