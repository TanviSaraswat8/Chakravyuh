# Chakravyuh developer commands. Run `make help`.
PY ?= python3
BACKEND = backend

.PHONY: help setup data train api user web test lint build up down sft data-real validate-real audit-leakage splits-real sft-real

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

user: ## Create an account: make user EMAIL=you@example.com ROLE=ADMIN (prompts for the password)
	cd $(BACKEND) && $(PY) -m app.manage create-user --email $(EMAIL) --role $(or $(ROLE),ANALYST)

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

dataset: ## Export the public tactic-level dataset to dataset/
	cd $(BACKEND) && $(PY) -m chakravyuh.sim.export_public --sessions data/sessions.jsonl --out ../dataset

data-real: ## Fetch the licensed real datasets at their pinned commits (SHA-256 checked)
	$(PY) scripts/fetch_real_datasets.py fetch imc25_smishing sp24_gateway_phishing india_spam_sms_junioralive

validate-real: ## Validate every real dataset on disk (schema, duplicates, labels, PII, licence, SHA-256)
	$(PY) scripts/validate_real_dataset.py --all

audit-leakage: ## Measure duplicate / template / cross-dataset leakage (writes data/reports/)
	$(PY) scripts/leakage_audit.py

splits-real: ## Preprocess real data and build leakage-safe splits
	$(PY) scripts/prepare_real_splits.py

sft-real: ## Build Sentinel SFT files from real data (no training)
	$(PY) sentinel/build_sft_real.py --config sentinel/configs/sentinel_real_v1.json
