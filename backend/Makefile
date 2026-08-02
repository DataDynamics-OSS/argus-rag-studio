.PHONY: dev run run-api run-worker test lint format clean

dev:
	pip install -e ".[dev]"

run:
	ARGUS_RAG_STUDIO_SERVER_CONFIG_DIR=$(CURDIR)/packaging/config \
		uvicorn app.main:app --host 0.0.0.0 --port 4700 --reload --reload-dir app

# 워커 분리 배포 — API 는 워커 없이(ARGUS_INGESTION_WORKER_ENABLED=false), 워커는 별도 프로세스.
# 대량 인제스천(docai 파싱 등)의 CPU 부하를 API 와 격리한다. 워커는 여러 개 띄워도 됨(SKIP LOCKED).
run-api:
	ARGUS_RAG_STUDIO_SERVER_CONFIG_DIR=$(CURDIR)/packaging/config \
	ARGUS_INGESTION_WORKER_ENABLED=false \
		uvicorn app.main:app --host 0.0.0.0 --port 4700

run-worker:
	ARGUS_RAG_STUDIO_SERVER_CONFIG_DIR=$(CURDIR)/packaging/config \
		python -m app.worker_main

test:
	pytest tests/ -v

lint:
	ruff check app/ && ruff format --check app/

format:
	ruff format app/ && ruff check --fix app/

clean:
	rm -rf build/ dist/ *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
