# Argus 임베딩 모델 파인튜닝 트레이너

> Argus RAG Studio 가 내보낸 학습 데이터셋으로 **임베딩 모델을 파인튜닝**하는 외부 참조 구현.
> 학습 연산은 이 프로그램이 담당하고, **데이터 관리·평가는 Argus** 가 담당한다.

이것은 **느슨하게 결합된 외부 프로세스**다. Argus 와는 *파일(데이터셋/모델) + 얇은 잡 상태*만
주고받으며, 제품은 이 트레이너 내부를 몰라도 된다. sentence-transformers 기반이며, 고객은
자기 GPU·인프라에서 실행한다.

---

## 책임 경계

| 단계 | 담당 |
|------|------|
| 학습 데이터 수집·라벨링·하드네거티브 마이닝·내보내기 | **Argus** |
| 임베딩 모델 파인튜닝(이 프로그램) | 외부(GPU) |
| 모델 등록·서빙·홀드아웃 평가·리더보드 비교 | **Argus** |

> **평가 주도권은 Argus 가 쥔다.** 이 트레이너는 valid 자체 지표만 보고하며, 모델의 최종
> 합격 판정은 Argus 가 보유한 홀드아웃 골든셋(test)으로 내린다.

---

## 입력 계약 (Argus → 트레이너)

데이터셋 디렉터리 구조:

```
<dataset_dir>/
  manifest.json     # 데이터셋 메타데이터
  train.jsonl       # 학습 레코드
  valid.jsonl       # 검증 레코드(선택) — 학습 중 IR 모니터링
  # test 는 Argus 가 보유하며 내보내지 않는다.
```

레코드(JSONL 한 줄):

```json
{"query": "...", "positive": "...", "negatives": ["...", "..."], "meta": {"source_doc": "소득세법", "as_of": "2026"}}
```

- `query` / `positive` : 필수, 비어 있지 않은 문자열
- `negatives` : 문자열 배열(하드네거티브). 비어 있어도 되지만, 있으면 학습 품질이 오른다.
- `meta` : 자유 메타데이터(출처·시점·라벨러 등)

`manifest.json` 주요 필드:

| 필드 | 설명 |
|------|------|
| `dataset_id` | 데이터셋 식별자(필수) |
| `base_model` | 베이스 모델(필수, 예: `intfloat/multilingual-e5-large`) |
| `embedding_dim` | 임베딩 차원(필수, 컬렉션 호환 확인용) |
| `task` | `embedding` \| `reranker` |
| `prompt_format` | `e5`(query:/passage: 접두) \| `none` |
| `split_strategy` | 예: `by_document`(누수 방지) |
| `mining_model` | 하드네거티브 마이닝에 쓴 임베딩 모델 |
| `glossary_version` | 사용한 도메인 용어집 버전 |

---

## 출력 계약 (트레이너 → Argus)

```
<output_dir>/
  model/            # sentence-transformers SavedModel
  metadata.json     # Argus 모델 레지스트리가 읽는 메타데이터
```

`metadata.json` 예:

```json
{
  "base_model": "intfloat/multilingual-e5-large",
  "embedding_dim": 1024,
  "format": "sentence-transformers",
  "task": "embedding",
  "prompt_format": "e5",
  "dataset_id": "...",
  "trained_at": "2026-06-14T...Z",
  "train": {"epochs": 3, "loss": "MultipleNegativesRankingLoss", "steps": 1000},
  "valid_metrics": {"hit_rate@5": 0.91, "mrr@5": 0.83, "n": 200}
}
```

---

## 사용법

```bash
# 1) 설치 (학습은 GPU 권장)
make dev            # = pip install -r requirements.txt

# 2) 데이터셋 검증 (torch 불필요)
make validate
# 또는
python -m finetune validate --dataset ./samples/dataset

# 3) 임베딩 모델 학습 + 내보내기
python -m finetune train \
  --dataset ./samples/dataset \
  --output ./out/tax-law-v1 \
  --base-model intfloat/multilingual-e5-large \
  --epochs 3 --batch-size 32 --lr 2e-5

# 3-b) 리랭커(cross-encoder) 학습 — 같은 데이터셋 재사용, --task reranker
python -m finetune train \
  --dataset ./samples/dataset \
  --output ./out/tax-law-reranker-v1 \
  --task reranker \
  --base-model cross-encoder/ms-marco-MiniLM-L-6-v2 \
  --epochs 3 --batch-size 16 --max-negatives 4

# 4) 데이터 로더/평가 테스트 (torch 불필요)
make test
```

### 임베딩 vs 리랭커

| 구분 | 임베딩(`task=embedding`) | 리랭커(`task=reranker`) |
|------|--------------------------|--------------------------|
| 모델 | bi-encoder(SentenceTransformer) | cross-encoder(CrossEncoder) |
| 손실 | MultipleNegativesRankingLoss | BCEWithLogitsLoss |
| 입력 접두 | e5 `query:`/`passage:` | 사용 안 함(질의·패시지 동시 입력) |
| 출력 | 1024차원 벡터 | 관련도 점수 1개 |
| 데이터 | **동일** (query, positive, negatives[]) | **동일** (positive→1, negative→0) |
| 재인덱싱 | 교체 시 필요 | **불필요**(질의 시점 재정렬) |

> 데이터셋 포맷이 동일하므로 같은 `samples/dataset` 으로 두 작업을 모두 학습할 수 있다.
> `manifest.task` 또는 `--task` 로 경로를 정하고, 리랭커는 cross-encoder 베이스 모델을 지정한다.

Docker:

```bash
docker build -t argus-rag-studio-finetune:latest .
docker run --rm -v $PWD/samples/dataset:/data -v $PWD/out:/out \
  argus-rag-studio-finetune:latest \
  train --dataset /data --output /out/model --epochs 1 --batch-size 8
```

> 이 이미지(`argus-rag-studio-finetune`)는 상시 서버가 아니라 일회성 GPU 학습 잡이므로, 에이전트 배포 카탈로그에는 포함되지 않는다.

---

## 학습한 모델을 Argus 에 연결하기

### 임베딩 모델
1. **서빙**: 파인튜닝 모델은 로컬 FastEmbed 로는 못 올린다(내장 모델만 지원). `model/` 을
   sentence-transformers 호환 임베딩 서버(예: TEI, 또는 본 저장소의 `extensions/embedding_server`)로 띄운다.
2. **컬렉션 연결**: Argus 에서 컬렉션 생성 시 프로바이더를 **OpenAI 호환**으로 두고 서버 URL을
   가리킨다. 차원이 컬렉션과 일치해야 한다.
3. **평가**: 같은 **홀드아웃 골든셋**으로 base 모델 컬렉션과 fine-tuned 모델 컬렉션을 평가/스윕해
   Hit Rate·MRR 을 나란히 비교한다. (Argus 가 판정)

### 리랭커
1. **서빙**: `model/` 을 cross-encoder 리랭크 서버(예: 본 저장소의 `extensions/reranker_server`)로 띄운다.
2. **컬렉션 연결**: 컬렉션의 리랭커 설정을 **`cross_encoder`** 로 두고 리랭크 서버 URL을 가리킨다.
   임베딩과 달리 **재인덱싱이 필요 없다**(질의 시점 재정렬).
3. **평가**: 평가/스윕에서 `rerank=on` 으로 base 리랭커와 비교해 Hit Rate·MRR 개선을 확인한다.

---

## 디렉터리

```
finetune/
  cli.py        # CLI 진입점 (validate | train), task 로 임베딩/리랭커 분기
  schema.py     # 매니페스트·레코드 스키마/검증 (표준 라이브러리만)
  dataset.py    # JSONL 로더 + InputExample 빌더 (e5 접두 처리)
  trainer.py    # 임베딩 학습 (SentenceTransformer, MultipleNegativesRankingLoss)
  reranker.py   # 리랭커 학습 (CrossEncoder, BCE) + 리랭크 평가
  evaluate.py   # 임베딩 valid IR 평가(hit_rate@k / mrr@k)
  export.py     # 모델 + metadata.json 내보내기 (task 별 메타)
samples/dataset/  # 세금·법률 도메인 예시 데이터셋(임베딩·리랭커 공용)
tests/            # 데이터 로더/검증 + 리랭커 평가 스모크 테스트
```

## 대량 학습 (GPU)

큰 데이터셋·장시간 학습에는 다음 옵션을 쓴다.

```bash
python -m finetune train \
  --dataset ./data/big --output ./out/v1 \
  --base-model intfloat/multilingual-e5-large \
  --device cuda \
  --epochs 3 --batch-size 128 \   # GPU VRAM 한도까지 크게
  --fp16 \                        # 혼합정밀(속도↑·메모리↓). CUDA 면 기본 자동 ON
  --checkpoint-steps 1000         # 장시간 학습 중 주기적 체크포인트(임베딩)
```

- `--device cuda` + `--fp16`(미지정 시 CUDA 환경에서 자동 ON) — GPU 처리량 극대화.
- `--batch-size`는 VRAM 한도까지 키운다(예: e5-large GPU에서 64~128). OOM이면 줄인다.
- `--checkpoint-steps N`(>0) — `<output>/checkpoints` 에 주기 저장(임베딩 학습).
- **멀티 GPU**: `SentenceTransformer.fit` 단일 프로세스 기준이라, 다수 GPU는 데이터셋을 분할해
  여러 잡을 병렬 실행하거나(샤딩) 추후 `accelerate`/`torchrun` 도입으로 확장한다.

## 한계 / TODO (스캐폴드)

- 임베딩은 레코드당 하드네거티브 1개를 사용한다(추가 네거티브는 in-batch 네거티브로 활용). 다중
  하드네거티브 배치는 추후 확장.
- 리랭커 평가는 레코드별 후보군(positive + 자체 negatives) 내 재정렬로 단순화했다. 교차 후보
  풀 평가는 추후 확장.
- fp16·주기 체크포인트는 지원(위 참고). **분산(멀티 GPU) 학습·체크포인트 재개·W&B 로깅**은 미포함.
