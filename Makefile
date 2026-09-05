.DEFAULT_GOAL := help

.PHONY: up down migrate seed poll state-machine replay test test-integration lint fmt smoke verify-seed verify-perf02 help topics

up: ## Start all infrastructure containers (Kafka, Redis, Postgres+TimescaleDB, Kafka UI)
	docker compose -f ops/docker-compose.yml up -d

down: ## Stop and remove infrastructure containers
	docker compose -f ops/docker-compose.yml down

topics: ## Create Kafka topics idempotently
	uv run python scripts/create_topics.py

migrate: ## Run Alembic migrations
	uv run alembic upgrade head

seed: ## Seed 50 NYC restaurants from scripts/seed/restaurants.yml
	uv run python scripts/seed_restaurants.py

poll: ## Run OpenTable poller on host
	uv run python -m services.poller

state-machine: ## Run the state machine consumer on host
	uv run python -m services.state_machine

replay: ## Replay availability.raw through the state machine (ARGS="--input tests/fixtures/raw_streams/happy.jsonl")
	uv run python scripts/replay_raw.py $(ARGS)

test: ## Run unit tests
	uv run pytest tests/unit -x -q

test-integration: ## Run integration tests (requires running infra)
	uv run pytest tests/unit tests/integration -v

lint: ## Run ruff check + mypy (scripts/ included: replay_raw.py carries the byte-identity claim)
	uv run ruff check .
	uv run mypy shared/ services/ scripts/

fmt: ## Format code with ruff
	uv run ruff format .

smoke: ## Quick smoke test: docker compose up, wait 30s, consume one availability.raw message
	docker compose -f ops/docker-compose.yml up -d
	sleep 30
	docker compose -f ops/docker-compose.yml exec kafka kafka-console-consumer.sh --bootstrap-server localhost:9092 --topic availability.raw --max-messages 1 --timeout-ms 30000

verify-seed: ## Assert >=50 restaurants in DB with all required fields; >=50 entries in sched:polls ZSET
	uv run python scripts/verify_seed.py

verify-perf02: ## Assert all 24-hour buckets in poll_log have >=99% success rate
	uv run python scripts/check_poll_success.py

help: ## Show available targets
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
