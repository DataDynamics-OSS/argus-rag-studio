.PHONY: dev run run-uvicorn test lint format clean docker docker-run

dev:
	pip install -r requirements.txt

# 패키지로 임포트되도록 부모 디렉터리에서 실행
run:
	cd .. && ARGUS_DETECTION_SERVER_CONFIG_DIR=$(CURDIR)/packaging/config \
		python -m detection_server

run-uvicorn:
	cd .. && ARGUS_DETECTION_SERVER_CONFIG_DIR=$(CURDIR)/packaging/config \
		uvicorn detection_server.main:app --host 0.0.0.0 --port 8082 --reload --reload-dir detection_server

test:
	pytest tests/ -v

lint:
	ruff check . && ruff format --check .

format:
	ruff format . && ruff check --fix .

docker:
	docker build -t argus-detection-server:latest .

docker-run:
	docker compose up -d --build

clean:
	rm -rf build/ dist/ *.egg-info logs/
	find . -type d -name __pycache__ -exec rm -rf {} +
