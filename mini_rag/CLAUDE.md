# mini_rag

A step-by-step teaching project: a small production-style RAG app (hybrid retrieval, reranking, LLM answer with citations, guardrails, evals) built from scratch for a learner.

**Before doing anything, read `memory.md` (state and decisions) and `imp.md` (jargon notes).**

## Rules for this folder
- Teach one small step at a time. Explain before running or writing code. Never run installs or commands the learner has not approved.
- After each step ask three short checkpoint questions (code flow, design reason, what could go wrong) and wait for answers.
- Define jargon in plain English first, then add it to `imp.md` tied to the file where it lives.
- Use `uv` only, never `pip`. Python 3.12. Streamlit frontend.
- Never read or print `.env` values. The user adds `.env` themselves (DeepSeek and Groq keys).
- Keep `memory.md` updated at the end of each step: status table, pending questions, next action.
- Do not modify the existing lab code outside this folder.
