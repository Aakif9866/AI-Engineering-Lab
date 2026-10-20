# 05 · SignalLoop: user feedback

**In one sentence:** users rate and correct the assistant's answers, a human reviews that feedback, approved corrections become test cases, and a new version of the assistant can only go live if it passes those tests without getting worse anywhere else.

## The scenario

A research assistant answering questions about the Evidence Atlas investigation documents. It reuses the RAG pipeline from Project 01; patterns combine. The live version starts as `baseline-v1` (keyword search, top 3 passages). The goal is to improve it safely using feedback.

## Try it in the web app

Open **http://localhost:5173/signalloop**.

1. **Assistant & feedback:** ask a question, then give feedback:
   - 👍/👎, categories (incorrect, unsupported, outdated…), a comment
   - **Edit the answer into what it should have said.** That correction is the most valuable signal.
   - Tick consent if it may be used for training.
   - *regenerate* and *copy* are recorded as implicit signals.

   No users yet? Press **Seed simulated feedback**. It adds 8 clearly simulated items: a duplicate, a correction containing a phone number, a poisoning attempt, and one "power user" who sends most of the feedback.
2. **Review queue:** feedback grouped into issue clusters, ranked by severity.
   - Approve an item by entering the facts a correct answer must contain (`01:35|1:35 ; 8 degrees`).
   - Try approving the poisoning attempt: refused.
   - Try approving for *training* without consent: refused.
   - **Delete** simulates a user's deletion request.
3. **Analytics:** participation, rating skew, failure categories, implicit signals, the power user's share (bias risk), and time from feedback to an approved example.
4. **Datasets & release gate:**
   1. **Freeze** an eval set (24 seed questions plus your approved examples, locked with a fingerprint).
   2. Create a candidate (for example `hybrid`, k 5).
   3. **Run gate**, then **promote**.
   4. Now create a candidate with abstention gate `0` and try to promote it: **blocked** (the server returns 403).

## How it works

```
answer ─► feedback (pseudonymised user, PII hidden, poisoning flagged)
       ─► review queue (duplicates, clusters, severity) ─► HUMAN approves with required facts
       ─► approved examples (with provenance) ─► FROZEN eval set (hash-locked)
candidate release ─► run candidate AND production on the frozen set ─► gate checks ─► promote (only if passed)
```

| File | What it does |
|---|---|
| `service.py` | Everything: collection, curation, analytics, frozen sets, gate, promotion, deletion, retention, demo seeding |
| `api.py` | HTTP routes for the web page |

## The release gate

| Check | Rule |
|---|---|
| Accuracy | Must not drop more than 2 points versus production |
| Abstention | Must refuse unanswerable questions at least as often as production (safety) |
| Citations | 100% must point at real passages |
| Reported failures | Candidate must not do worse on examples that came from user feedback |
| Privacy | No personal data in any answer |

## Commands

```bash
cd backend
.venv/bin/python -m pytest tests/test_p05_feedback.py
```

Everything else is driven from the web page or the API (`/api/feedback/...`).

## Measured results (tests, 2026-10-20)

- A `hybrid + rerank` candidate **passes** the gate against the keyword baseline.
- A candidate with the abstention gate turned off is **blocked**: it stops refusing unanswerable questions, and promotion returns 403.
- Deleting feedback removes its derived example and **invalidates** any frozen set that contained it.
- Editing a frozen set's contents is detected by its fingerprint, and gating on it is refused.

## Limits and next steps

- A single local user, so "users" are simulated ids.
- Clustering is simple (same category plus similar question).
- **V2:** suggest which fix would help most, pick which interactions to ask users about (active learning), and export approved corrections to IntentForge for training.
