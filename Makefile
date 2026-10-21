# AI Engineering Lab: local commands. Requires Python 3.10+, Node 18+, and uv (or pip).
PY := backend/.venv/bin/python

setup:            ## create venv, install core + ML deps, install frontend deps
	cd backend && uv venv .venv --python 3.10 && uv pip install --python .venv/bin/python -r requirements.txt -r requirements-ml.txt
	cd frontend && npm install

setup-core:       ## core deps only (no torch): RAG uses the hash embedder, no LoRA training
	cd backend && uv venv .venv --python 3.10 && uv pip install --python .venv/bin/python -r requirements.txt
	cd frontend && npm install

models:           ## pre-download the two small local models (~360 MB)
	cd backend && .venv/bin/python -c "from sentence_transformers import SentenceTransformer as S; S('sentence-transformers/all-MiniLM-L6-v2'); from huggingface_hub import snapshot_download as d; d('HuggingFaceTB/SmolLM2-135M-Instruct')"

backend:          ## API on http://127.0.0.1:8000
	cd backend && .venv/bin/uvicorn lab.api:app --host 127.0.0.1 --port 8000

dev:              ## backend + frontend together (Ctrl-C stops both)
	$(MAKE) -j2 backend frontend

frontend:         ## UI on http://localhost:5173 (proxies /api to the backend)
	cd frontend && npm run dev

test:             ## full offline test suite (no network, no paid calls)
	cd backend && .venv/bin/python -m pytest

typecheck:
	cd frontend && npx tsc -b --noEmit

experiments:      ## offline benchmark/experiment commands for every module
	cd backend && .venv/bin/python -m lab.p01_rag.evaluate
	cd backend && .venv/bin/python -m lab.p02_finetune.data && .venv/bin/python -m lab.p02_finetune.evaluate --system rules
	cd backend && .venv/bin/python -m lab.p03_cache.workload
	cd backend && .venv/bin/python -m lab.p04_guardrails.adversarial
	cd backend && .venv/bin/python -m lab.p06_agent_evals.evaluate

.PHONY: setup setup-core models backend frontend dev test typecheck experiments
