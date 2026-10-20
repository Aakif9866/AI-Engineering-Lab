# Troubleshooting

Each entry is a symptom, its cause, and the fix. Most of these were hit while building the lab.

## Setup

**`uv: command not found`**
Install uv (`pip install uv`), or use plain venv: `python3 -m venv backend/.venv && backend/.venv/bin/pip install -r backend/requirements.txt -r backend/requirements-ml.txt`.

**Disk space during `make setup`**
The ML extras take about 900 MB and the two models about 360 MB (in `~/.cache/huggingface`). With little free space, run `make setup-core` instead: the whole lab works, except LoRA training, and RAG and caching use the hash embedder. The status badge in the header shows which embedder is active.

**First request is slow (5 to 10 s)**
MiniLM and torch load lazily on first use. Later requests are fast. The lab loads cached models with `local_files_only=True` first; an early version did not, and Hub network checks made one experiment run take 601 s instead of 7 s.

## Providers

**Header shows "offline mode" although a key is in `.env`**
- The key must sit in the **repo-root** `.env` (not `backend/.env`), named `DEEPSEEK_API_KEY` or `GROQ_API_KEY`.
- Values starting with `your-` (the `.env.example` placeholders) are treated as unset.
- `LAB_OFFLINE=1` forces offline mode even when keys exist.
- Restart the backend after editing `.env`; it is read at startup.

**`provider_unavailable` (HTTP 409) when a workspace offers an LLM toggle**
No usable provider is configured. Turn the LLM option off to use the offline path. Nothing was called and nothing was charged.

**`rate_limit` or `server error` after a delay**
The client retries 429 and 5xx responses `LAB_MAX_RETRIES` times (default 2), honouring `Retry-After`, then fails loudly. Each retry is a `retry` span in TraceLens. Other 4xx errors are not retried.

**Answer cut off mid-sentence**
Reasoning models spend part of `max_tokens` on hidden reasoning. RAG uses 1500 and flags `finish_reason == "length"` as truncation in the UI. If you lower the budgets, expect this.

**Costs show "UNVERIFIED price"**
DeepSeek's official pricing page could not be retrieved when this was built. The prices in `backend/lab/core/pricing.json` come from secondary sources and are labelled. Confirm them on the provider's site and set `"verified": true`.

## Fine-tuning (IntentForge)

**Training stalls after a few steps; the process sits at ~0% CPU**
The system is out of memory and swapping. On the 8 GB M1 this was built on, the MPS allocator's memory growth caused exactly this (process state `U`, swap nearly full). Training defaults to CPU (`LAB_TORCH_DEVICE=cpu`), which was just as fast here (about 1.5 s/step at batch 8). Close memory-heavy apps, and don't run evaluation while training.

**Run shows `interrupted`**
The training process died without writing a final state (killed, or out of memory). Check the log tail on the Train tab, or `backend/var/jobs/p02-train.log`.

**Constrained decoding is slow**
Each enum field scores every allowed value with a forward pass, about 1.5 s per example on CPU with the adapter's short prompt and about 4.5 s with the long baseline prompt. `logits_to_keep` already avoids projecting every prompt position onto the 49k-token vocabulary.

**A trained adapter scores poorly on some fields although validation loss is low**
That is a real finding, not a bug: loss averages over every token, and most tokens are easy. Look at the per-field columns and the OOD slice.

## Data and state

**Reset everything**
Stop the backend and delete `backend/var/`. It holds the SQLite database (traces, cache, feedback, runs), datasets, adapters and experiment results. Fixtures in `backend/data/` are never modified.

**Traces disappeared**
Retention purges spans older than `LAB_TRACE_RETENTION_DAYS` when you click Purge in TraceLens. It never runs automatically.

**Tests touch my real data?**
No. Every test gets its own temporary `LAB_VAR_DIR`, offline mode, the hash embedder, and an HTTP transport that fails the test if anything tries to reach the network.

## Frontend

**API calls return 404 or connection refused**
The Vite dev server proxies `/api` to `127.0.0.1:8000`. Start the backend first (`make backend`).

**Screenshots of the mobile layout look clipped**
Desktop Chrome enforces a minimum window width of about 500 px even in headless mode, so a 390 px screenshot crops a 500 px layout. Test phone widths with device emulation (or an iframe of the target width) instead.
