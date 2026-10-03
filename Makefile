# Chakravyuh developer commands. Run `make help`.
PY ?= python3
BACKEND = backend

.PHONY: help setup data train api web test lint build up down sft

help:
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

setup: ## Install backend and frontend dependencies
	cd $(BACKEND) && $(PY) -m pip install -r requirements.txt
	cd frontend && npm install

data: ## Run the Chakravyuh simulator (add LLM_RATE=0.3 to paraphrase with an LLM)
	cd $(BACKEND) && $(PY) -m chakravyuh.sim.simulator --n 4000 --generations 6 --population 40 --llm-rate $${LLM_RATE:-0} --out data

train: ## Train every model and write the benchmark to backend/artifacts/metrics.json
	cd $(BACKEND) && $(PY) -m chakravyuh.ml.train --data data --out artifacts

api: ## Start the API with auto-reload on :8000
	cd $(BACKEND) && $(PY) -m uvicorn app.main:app --reload --port 8000

web: ## Start the web app on :5173 (proxies the API)
	cd frontend && npm run dev

test: ## Run backend tests and a frontend type-check
	cd $(BACKEND) && $(PY) -m pytest -q
	cd frontend && npm run typecheck

lint: ## Lint the backend
	cd $(BACKEND) && ruff check .

build: ## Production build of the frontend
	cd frontend && npm run build

up: ## Run everything in Docker (Postgres + API + web)
	docker compose up --build

down: ## Stop Docker services
	docker compose down

sft: ## Build the Sentinel SLM fine-tuning set
	$(PY) sentinel/build_sft.py --sessions $(BACKEND)/data/sessions.jsonl --out sentinel/sft

coevolve: ## Run attacker-defender co-evolution (add PERSIST=1 to save the hardened model)
	cd $(BACKEND) && $(PY) -m chakravyuh.ml.coevolve --rounds 3 --generations 4 $(if $(PERSIST),--persist,)
