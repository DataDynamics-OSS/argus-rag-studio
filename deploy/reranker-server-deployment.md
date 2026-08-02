# 리랭커 서버 배포 가이드

- **역할**: 검색 결과 재순위(cross-encoder, TEI 호환 `POST /rerank`)
- **소스**: `extensions/reranker_server/` · **기본 포트**: 8081 · **인증**: `Authorization: Bearer <RERANK_API_KEY>`
- **설정 연결**: 전역 `rerank.server_url` (per-collection URL 없음 — cross_encoder 사용 컬렉션 전체에 적용됨에 유의)
- **설정 소스**: `ARGUS_RERANKER_SERVER_CONFIG_DIR`(기본 `/etc/argus-reranker-server`), **`RERANK_*` 환경변수 우선**

## 방법 1 — 플랫폼 배포 (권장)

**에이전트 > 서비스/배포**(kind=reranker) 또는 `POST /api/v1/deploy`. 이름 규약·설정
주입·모델 사전 설치(레지스트리 선택 시)·서비스 관리 탭 탐색 자동.

## 방법 2 — 수동 Docker

```bash
docker run -d --name argus-rag-reranker-1 --label argus.kind=reranker \
  --restart unless-stopped --gpus all \
  -p 8081:8081 \
  -v argus-rag-rerank-models:/models \
  -e RERANK_PORT=8081 -e RERANK_CACHE_DIR=/models \
  -e RERANK_API_KEY=changeme \
  -e RERANK_BACKEND=sentence_transformers -e RERANK_DEVICE=cuda -e RERANK_PRELOAD=true \
  -e RERANK_DEFAULT_MODEL=BAAI/bge-reranker-v2-m3 \
  -e RERANK_MODELS=BAAI/bge-reranker-v2-m3,dragonkue/bge-reranker-v2-m3-ko \
  -e ARGUS_HEARTBEAT_URL=http://<backend>:4700/api/v1/ext-servers/heartbeat \
  -e ARGUS_INSTANCE_URL=http://<this-host>:8081 \
  argus-rag-studio-reranker-server:latest-gpu-torch
```

## 방법 3 — systemd 직접 실행 (비컨테이너)

> 에이전트의 systemd 탐색은 worker 전용 — 이 unit 은 서비스 관리 탭에 안 보인다.
> heartbeat env 로 외부 서버 채널 관측 권장.

```bash
cd /opt/argus-ext/extensions
python3 -m venv reranker-venv && . reranker-venv/bin/activate
pip install -r reranker_server/requirements.txt
# GPU(torch·cu128): pip install torch --index-url https://download.pytorch.org/whl/cu128
#                   pip install -r reranker_server/requirements-gpu-torch.txt
```

```ini
# /etc/systemd/system/argus-reranker-server.service
[Unit]
Description=Argus Reranker Server
After=network-online.target

[Service]
WorkingDirectory=/opt/argus-ext/extensions
ExecStart=/opt/argus-ext/extensions/reranker-venv/bin/python -m reranker_server
Environment=RERANK_PORT=8081
Environment=RERANK_API_KEY=changeme
Environment=RERANK_BACKEND=sentence_transformers
Environment=RERANK_DEVICE=cuda
Environment=RERANK_PRELOAD=true
Environment=RERANK_DEFAULT_MODEL=BAAI/bge-reranker-v2-m3
Environment=RERANK_CACHE_DIR=/var/lib/argus-reranker-server/models
Environment=ARGUS_HEARTBEAT_URL=http://<backend>:4700/api/v1/ext-servers/heartbeat
Environment=ARGUS_INSTANCE_URL=http://<this-host>:8081
Restart=on-failure
RestartSec=5
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload && systemctl enable --now argus-reranker-server
```

## 방법 4 — shell 직접 실행

```bash
cd /opt/argus-ext/extensions && . reranker-venv/bin/activate
export RERANK_PORT=8081 RERANK_API_KEY=changeme RERANK_DEVICE=cuda RERANK_PRELOAD=true
export RERANK_DEFAULT_MODEL=BAAI/bge-reranker-v2-m3

python -m reranker_server                                            # 포그라운드
nohup python -m reranker_server > /var/log/argus-reranker.log 2>&1 & # 백그라운드
```

## 모델 준비 (수동 배포 서버)

**온라인**: 준비 불필요 — 첫 사용/`RERANK_PRELOAD=true` 기동 시 `RERANK_CACHE_DIR` 로 자동
다운로드. **에어갭**: Model Repository 팩을 **hf-cache 구조로** 전개(임베딩 서버와 동일
절차 — [embedding-server-deployment.md](embedding-server-deployment.md#모델-준비-수동-배포-서버)
참조, `RERANK_*` 이름만 다름):

```bash
mc cp argus/argus-models/reranker/bge-reranker-v2-m3/main/model.tar.zst .
echo "$(mc cat argus/argus-models/reranker/bge-reranker-v2-m3/main/manifest.json | jq -r .sha256)  model.tar.zst" | sha256sum -c

CACHE=/var/lib/argus-reranker-server/models           # = RERANK_CACHE_DIR 값
D=$CACHE/models--BAAI--bge-reranker-v2-m3
mkdir -p "$D/snapshots/main" "$D/refs"
tar --use-compress-program=unzstd -xf model.tar.zst -C "$D/snapshots/main"
echo main > "$D/refs/main"

export RERANK_CACHE_DIR=$CACHE HF_HUB_OFFLINE=1       # 오프라인 강제
```

대안: 온라인 머신에서 `huggingface-cli download <repo>` 후 hub 캐시 디렉터리 복사 /
표준 볼륨 + 에이전트 호스트라면 `POST :4501/api/v1/model/install` 로 전개 위임.

## 옵션 레퍼런스 (`RERANK_*` env — config.yml 값보다 항상 우선, 빈값도 유효)

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `RERANK_HOST` | 0.0.0.0 | 바인드 주소 |
| `RERANK_PORT` | 8081 | 리슨 포트. Docker 는 내부 8081 고정 + 호스트 매핑으로 조정 권장 |
| `RERANK_API_KEY` | changeme | Bearer 인증 키. **빈값이면 무인증** — 반드시 변경 |
| `RERANK_BACKEND` | fastembed | `fastembed`(ONNX) \| `sentence_transformers`(torch·GPU). aarch64 GPU 는 torch 백엔드 |
| `RERANK_DEVICE` | cpu | `cpu` \| `cuda`. GPU 로딩 실패 시 CPU 자동 폴백 |
| `RERANK_CUDA_DEVICE_IDS` | (빈값=기본 GPU) | 사용할 GPU 인덱스(콤마) |
| `RERANK_DEFAULT_MODEL` | Xenova/ms-marco-MiniLM-L-6-v2 | 요청에 model 이 없을 때 기본 cross-encoder — 한국어는 `BAAI/bge-reranker-v2-m3` 권장 |
| `RERANK_MODELS` | (빈값=제한 없음) | 서빙 허용 모델 목록(HF repo CSV) — 목록 외 요청 거부 |
| `RERANK_CACHE_DIR` | (빈값=HF 기본 캐시) | 모델 캐시 디렉터리. 플랫폼 배포는 `/models`(볼륨) 주입 |
| `RERANK_PRELOAD` | false | 기동 시 기본 모델 즉시 로드(true 권장) |
| `RERANK_MAX_BATCH` | 256 | 요청당 최대 (query, text) 쌍 개수 |
| `RERANK_LOG_LEVEL` / `RERANK_LOG_DIR` | INFO / logs | 로그 레벨·디렉터리 |
| `ARGUS_RERANKER_SERVER_CONFIG_DIR` | /etc/argus-reranker-server | config.yml/properties 디렉터리 |

**자기 등록(heartbeat, 선택)**: `ARGUS_HEARTBEAT_URL`(백엔드 수신 URL, 빈값=비활성) ·
`ARGUS_INSTANCE_URL`(이 레플리카 주소) · `ARGUS_HEARTBEAT_TOKEN`(백엔드
`monitoring.heartbeat_token` 일치, 선택) · `ARGUS_HEARTBEAT_INTERVAL`(기본 10초).

## 탐색·모니터링

방법 1·2(규약 Docker)만 서비스 관리 탭에 보인다. 방법 3·4는 heartbeat env(외부 서버
레지스트리) + 전역 `rerank.server_url` 폴링(잡 모니터링 > 외부 서버)으로 관측.

## 검증

```bash
curl -s -H "Authorization: Bearer changeme" http://<host>:8081/stats | jq .model
curl -s -X POST http://<host>:8081/rerank -H "Authorization: Bearer changeme" \
  -H 'Content-Type: application/json' \
  -d '{"query":"계약 해지 조건","texts":["계약의 해지는 30일 전 서면 통지로 한다","점심 메뉴"]}'
# 관련 문서의 score 가 무관 문서보다 크게 높아야 정상
```
