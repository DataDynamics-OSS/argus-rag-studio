# 임베딩 서버 배포 가이드

- **역할**: 문서 청크/질의 임베딩(OpenAI 호환 `POST /v1/embeddings`) — sentence-transformers/fastembed 백엔드
- **소스**: `extensions/embedding_server/` · **기본 포트**: 8080 · **인증**: `Authorization: Bearer <EMBED_API_KEY>`
- **설정 연결**: 컬렉션별 `embedding_server_url` 또는 전역 `embedding.server_url` (수동 배포는 직접 설정 — 자동 주입 없음)
- **설정 소스**: `ARGUS_EMBEDDING_SERVER_CONFIG_DIR`(기본 `/etc/argus-embedding-server`)의 config.yml/properties, **`EMBED_*` 환경변수가 항상 우선**

## 방법 1 — 플랫폼 배포 (권장)

에이전트가 설치된 호스트라면 **에이전트 > 서비스/배포** 다이얼로그(kind=embedding) 또는
`POST /api/v1/deploy` 로 배포한다. 이름 규약·설정 주입·모델 사전 설치·서비스 관리 탭
탐색이 전부 자동이다. 기본 포트가 점유된 호스트는 다이얼로그의 **호스트 포트** 필드 사용.

## 방법 2 — 수동 Docker

이름·라벨 규약을 지키면 에이전트가 있는 호스트에서는 서비스 관리 탭에 자동 탐색된다.

```bash
# 이미지: 로컬 빌드(cd extensions/embedding_server && docker compose -f docker-compose.gpu-torch.yml build)
#        또는 zot 미러(에어갭). CPU 는 Dockerfile, GPU(amd64)는 .gpu, GPU(arm64/torch)는 .gpu-torch.
docker run -d --name argus-rag-embedding-1 --label argus.kind=embedding \
  --restart unless-stopped --gpus all \
  -p 8090:8080 \
  -v argus-rag-embed-models:/models \
  -e EMBED_PORT=8080 -e EMBED_CACHE_DIR=/models \
  -e EMBED_API_KEY=changeme \
  -e EMBED_BACKEND=sentence_transformers -e EMBED_DEVICE=cuda -e EMBED_PRELOAD=true \
  -e EMBED_DEFAULT_MODEL=mixedbread-ai/mxbai-embed-large-v1 \
  -e EMBED_MODELS=mixedbread-ai/mxbai-embed-large-v1,intfloat/multilingual-e5-large \
  -e ARGUS_HEARTBEAT_URL=http://<backend>:4700/api/v1/ext-servers/heartbeat \
  -e ARGUS_INSTANCE_URL=http://<this-host>:8090 \
  argus-rag-studio-embedding-server:latest-gpu-torch
```

- 호스트 포트 충돌 시 매핑(`-p <대체>:8080`)과 `ARGUS_INSTANCE_URL`·설정 URL 만 바꾼다(내부 8080 유지).

## 방법 3 — systemd 직접 실행 (비컨테이너)

> 주의: 에이전트의 systemd 탐색은 worker 전용이라 **이 unit 은 서비스 관리 탭에 안 보인다**
> — heartbeat env 를 넣어 외부 서버 채널로 관측하는 것을 권장.

```bash
# 1) venv 준비 (소스 배포 위치 예: /opt/argus-ext)
cd /opt/argus-ext/extensions
python3 -m venv embedding-venv && . embedding-venv/bin/activate
pip install -r embedding_server/requirements.txt
# GPU(torch·cu128) 사용 시:
pip install torch --index-url https://download.pytorch.org/whl/cu128
```

```ini
# /etc/systemd/system/argus-embedding-server.service
[Unit]
Description=Argus Embedding Server
After=network-online.target

[Service]
# 패키지 임포트를 위해 extensions/ 디렉터리에서 실행
WorkingDirectory=/opt/argus-ext/extensions
ExecStart=/opt/argus-ext/extensions/embedding-venv/bin/python -m embedding_server
Environment=EMBED_PORT=8090
Environment=EMBED_API_KEY=changeme
Environment=EMBED_BACKEND=sentence_transformers
Environment=EMBED_DEVICE=cuda
Environment=EMBED_PRELOAD=true
Environment=EMBED_DEFAULT_MODEL=mixedbread-ai/mxbai-embed-large-v1
Environment=EMBED_CACHE_DIR=/var/lib/argus-embedding-server/models
Environment=ARGUS_HEARTBEAT_URL=http://<backend>:4700/api/v1/ext-servers/heartbeat
Environment=ARGUS_INSTANCE_URL=http://<this-host>:8090
Restart=on-failure
RestartSec=5
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload && systemctl enable --now argus-embedding-server
```

## 방법 4 — shell 직접 실행

```bash
cd /opt/argus-ext/extensions && . embedding-venv/bin/activate
export EMBED_PORT=8090 EMBED_API_KEY=changeme EMBED_DEVICE=cuda EMBED_PRELOAD=true
export EMBED_DEFAULT_MODEL=mixedbread-ai/mxbai-embed-large-v1

# 포그라운드
python -m embedding_server
# 또는 백그라운드
nohup python -m embedding_server > /var/log/argus-embedding-server.log 2>&1 &
```

개발 편의는 `extensions/embedding_server/Makefile` 의 `make run`(패키징 config 사용) /
`make run-uvicorn`(--reload) 참조.

## 모델 준비 (수동 배포 서버)

플랫폼 배포는 에이전트가 Model Repository 에서 자동 설치하지만, 수동 배포는 직접 준비한다.

**온라인 서버** — 준비 불필요: 첫 사용(또는 `EMBED_PRELOAD=true` 기동) 시 HF 에서
`EMBED_CACHE_DIR` 로 자동 다운로드된다.

**에어갭 서버** — Model Repository(argus-models 버킷)의 팩을 받아 **hf-cache 구조로** 전개한다
(sentence-transformers 가 "모델 이름"으로 오프라인 캐시를 조회하는 구조 — 필수):

```bash
# 0) 사전: 모델 관리 화면에서 해당 모델 "보유" 확인(외부망 pack_model → mc cp 반입 완료 상태)
mc alias set argus http://<minio-host>:9000 <access-key> <secret-key>

# 1) 팩 다운로드 + 무결성 검증 — 키 규약 {kind}/{name}/{revision}/
mc cp argus/argus-models/embedding/multilingual-e5-large/main/model.tar.zst .
mc cp argus/argus-models/embedding/multilingual-e5-large/main/manifest.json .
echo "$(jq -r .sha256 manifest.json)  model.tar.zst" | sha256sum -c

# 2) hf-cache 레이아웃으로 전개 — models--{org}--{name}/snapshots/{rev} + refs/main
CACHE=/var/lib/argus-embedding-server/models          # = EMBED_CACHE_DIR 값
D=$CACHE/models--intfloat--multilingual-e5-large      # repo 의 '/' 를 '--' 로
mkdir -p "$D/snapshots/main" "$D/refs"
tar --use-compress-program=unzstd -xf model.tar.zst -C "$D/snapshots/main"   # .tar.gz 팩이면 tar xzf
echo main > "$D/refs/main"

# 3) 서버 env 로 오프라인 강제 — 미보유 모델이 무음으로 외부에 나가려다 행 걸리지 않게
export EMBED_CACHE_DIR=$CACHE HF_HUB_OFFLINE=1
```

- 대안(온라인 머신 경유): `huggingface-cli download <repo>` 후
  `~/.cache/huggingface/hub/models--*` 디렉터리를 통째로 `EMBED_CACHE_DIR` 에 복사해도
  동일 구조라 그대로 동작한다.
- 수동 **Docker**(방법 2)로 표준 볼륨(`argus-rag-embed-models`)을 쓰고 호스트에 에이전트가
  있다면, 전개를 에이전트에 맡길 수도 있다:
  `POST http://<host>:4501/api/v1/model/install` (백엔드 모델 관리 화면의 설치 플로우와 동일).

## 옵션 레퍼런스 (`EMBED_*` env — config.yml 값보다 항상 우선, 빈값도 유효)

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `EMBED_HOST` | 0.0.0.0 | 바인드 주소 |
| `EMBED_PORT` | 8080 | 리슨 포트. Docker 는 내부 8080 고정 + 호스트 매핑으로 조정 권장 |
| `EMBED_API_KEY` | changeme | Bearer 인증 키. **빈값이면 무인증** — 반드시 변경 |
| `EMBED_BACKEND` | fastembed | 추론 백엔드: `fastembed`(ONNX) \| `sentence_transformers`(torch). aarch64+Blackwell 처럼 onnxruntime-gpu 휠이 없는 환경의 GPU 는 torch 백엔드 사용 |
| `EMBED_DEVICE` | cpu | `cpu` \| `cuda`. cuda 는 fastembed 백엔드면 fastembed-gpu, torch 백엔드면 torch cu128 설치 필요. GPU 로딩 실패 시 CPU 자동 폴백 |
| `EMBED_CUDA_DEVICE_IDS` | (빈값=기본 GPU) | 사용할 GPU 인덱스(콤마, 예 `0,1`) |
| `EMBED_DEFAULT_MODEL` | mixedbread-ai/mxbai-embed-large-v1 | 요청에 model 이 없을 때 쓰는 기본 모델(HF repo id) |
| `EMBED_MODELS` | (빈값=제한 없음) | 서빙 허용 모델 목록(HF repo CSV). 지정 시 목록 외 모델 요청은 거부 |
| `EMBED_DIM` | 1024 | 차원 검증 필터 — 이 차원이 아닌 모델 사용 차단(0=해제). 컬렉션 벡터 차원 불일치 사고 방지 |
| `EMBED_CACHE_DIR` | (빈값=HF 기본 캐시) | 모델 캐시 디렉터리. 플랫폼 배포는 `/models`(볼륨) 주입 — 에어갭 사전 설치(hf-cache)와 공용 |
| `EMBED_PRELOAD` | false | 기동 시 기본 모델 즉시 로드(true 권장 — 첫 요청 지연 제거, 준비 상태가 /stats 에 드러남) |
| `EMBED_MAX_BATCH` | 256 | 요청당 최대 입력 개수(초과 시 분할 처리 기준) |
| `EMBED_LOG_LEVEL` / `EMBED_LOG_DIR` | INFO / logs | 로그 레벨·디렉터리 |
| `ARGUS_EMBEDDING_SERVER_CONFIG_DIR` | /etc/argus-embedding-server | config.yml/properties 디렉터리(env 미지정 값의 폴백 소스) |

**자기 등록(heartbeat, 선택)** — 지정 시 백엔드 외부 서버 레지스트리에 주기 보고:

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `ARGUS_HEARTBEAT_URL` | (빈값=비활성) | 백엔드 수신 URL — `http://<backend>:4700/api/v1/ext-servers/heartbeat` |
| `ARGUS_INSTANCE_URL` | - | 이 레플리카의 직접 주소(표시·LB 뒤 개별 관측용) |
| `ARGUS_HEARTBEAT_TOKEN` | (빈값) | 공유 토큰 — 백엔드 `monitoring.heartbeat_token` 과 일치해야 수신됨(설정 시) |
| `ARGUS_HEARTBEAT_INTERVAL` | 10 | 보고 주기(초) |

## 탐색·모니터링

| 방식 | 서비스 관리 탭 | 외부 서버 탭/heartbeat |
|---|---|---|
| 방법 1·2(규약 Docker) | ✅ 자동 | ✅(heartbeat env 시) |
| 방법 3·4(systemd/shell) | ❌ | ✅ heartbeat env + 전역 `embedding.server_url` 폴링 |

## 검증

```bash
curl -s http://<host>:8090/health
curl -s -H "Authorization: Bearer changeme" http://<host>:8090/stats | jq .model
curl -s -X POST http://<host>:8090/v1/embeddings -H "Authorization: Bearer changeme" \
  -H 'Content-Type: application/json' \
  -d '{"model":"mixedbread-ai/mxbai-embed-large-v1","input":["hello"]}' | jq '.data[0].embedding | length'
```
