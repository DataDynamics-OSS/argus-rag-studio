.PHONY: dev validate train test lint format docker clean

# 학습 의존성 설치(GPU 환경 권장)
dev:
	pip install -r requirements.txt

# 샘플 데이터셋 검증(torch 불필요)
validate:
	python -m finetune validate --dataset ./samples/dataset

# 샘플 데이터셋으로 임베딩 학습 스모크 (CPU 가능하나 느림)
train:
	python -m finetune train --dataset ./samples/dataset --output ./out/sample \
		--epochs 1 --batch-size 8

# 같은 데이터셋으로 리랭커(cross-encoder) 학습 스모크
train-reranker:
	python -m finetune train --dataset ./samples/dataset --output ./out/sample-reranker \
		--task reranker --base-model cross-encoder/ms-marco-MiniLM-L-6-v2 \
		--epochs 1 --batch-size 8 --max-negatives 4

# 데이터 로더/검증 테스트(torch 불필요)
test:
	python -m pytest -q

lint:
	ruff check . && ruff format --check .

format:
	ruff format . && ruff check --fix .

docker:
	docker build -t argus-retrieval-finetune:latest .

clean:
	rm -rf out/ build/ dist/ *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
