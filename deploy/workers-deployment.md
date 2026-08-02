# 워커 분리 배포 (Worker separation)

대량 인제스천 시 **파싱(docai/layout 등)은 CPU 바운드**라, 워커가 API 와 같은 프로세스에서
돌면 GIL 경합으로 API 응답이 느려진다. 워커를 **별도 프로세스/컨테이너**로 빼고, 필요하면
**여러 개로 수평 확장**한다. 인제스천 큐(`rag_ingestion_jobs`)는 DB 기반이고 `SKIP LOCKED`
로 잡을 claim 하므로 워커를 여러 개 띄워도 중복 처리되지 않는다.

> 참고: **임베딩은 이미 외부 GPU 서버(.48)로 오프로드**되어 있어 워커의 주 부하는 parse+chunk
> (백엔드 CPU)다. 즉 늘려야 하는 건 GPU 가 아니라 **워커(CPU) 풀**이다.

## 권장 배포 방식

- **백엔드 체크아웃이 있는 호스트(dev)**: **관리형 systemd** (에이전트 > 서비스/배포,
  method=systemd, working_directory=체크아웃) — 체크아웃 venv 를 그대로 실행하므로
  파이프라인 코드 변경이 restart 만으로 반영된다(도커 이미지의 "코드 박제" 함정 없음).
- **원격/에어갭 표준**: **Docker** — 이미지 반입 체계(zot)와 결이 맞고 호스트에
  파이썬 환경이 불필요. 단 코드 변경 = 이미지 교체임을 전제.
- systemd/shell 수동 실행은 아래 A-1·A-2 참조(에이전트 없는 호스트 등 예외 상황용).

## 동작 방식

- **API 인스턴스**: `ARGUS_INGESTION_WORKER_ENABLED=false` 로 띄우면 in-process 워커
  (ingestion·evaluation·sweep)를 기동하지 않는다 — 순수하게 요청만 처리.
- **워커 프로세스**: `python -m app.worker_main` 이 동일한 3개 루프를 돌린다. API 가 하던
  준비(DB 초기화·ORM 등록·`load_into_runtime` 설정 override·버킷 보장)를 그대로 수행한 뒤
  큐를 폴링한다. `SIGTERM`/`SIGINT` 에 깔끔히 종료.

## A. 소스 실행 (현재 dev 방식)

```bash
cd backend

# API — 워커 없이
make run-api        # = ARGUS_INGESTION_WORKER_ENABLED=false uvicorn app.main:app --port 4700

# 워커 — 별도 터미널/프로세스(여러 개 띄워도 됨)
make run-worker     # = python -m app.worker_main
make run-worker     # 또 하나(수평 확장)
```

### A-1. shell 직접 실행 (백그라운드)

백엔드 config 가 없는 원격 호스트라면 연결 env 를 직접 지정한다(체크아웃 호스트는 생략 가능):

```bash
cd <backend 체크아웃> && . .venv/bin/activate
export ARGUS_DB_URL=postgresql+asyncpg://argus:****@<db-host>:5432/argus_rag_studio
export ARGUS_OS_ENDPOINT=http://<minio-host>:9000 ARGUS_OS_ACCESS_KEY=... ARGUS_OS_SECRET_KEY=...
export ARGUS_OS_BUCKET=argus-rag-studio ARGUS_OS_USE_SSL=false
export ARGUS_EMBEDDING_SERVER_URL=<임베딩 서버> ARGUS_EMBEDDING_MODEL=<모델>

nohup python -m app.worker_main > /var/log/argus-rag-worker-1.log 2>&1 &
```

- nohup 워커도 **잡 모니터링 > 워커에는 보인다**(워커 레지스트리 자기 등록) —
  서비스 관리 탭(라이프사이클)에는 안 보임.

### A-2. systemd 직접 실행

unit 이름을 **`argus-rag-worker-<N>` 규약**으로 지으면 에이전트(servicemgr)가 그대로
탐색해 서비스 관리 탭에 OS Native 로 노출·제어된다(다른 이름은 탐색 대상 아님).

```ini
# /etc/systemd/system/argus-rag-worker-1.service
[Unit]
Description=Argus RAG Studio ingestion worker (argus-rag-worker-1)
After=network-online.target

[Service]
WorkingDirectory=<backend 체크아웃>
ExecStart=<backend 체크아웃>/.venv/bin/python -m app.worker_main
Environment=ARGUS_LOG_FILENAME=argus-rag-worker-1.log
# 원격 호스트면 A-1 의 ARGUS_DB_URL/ARGUS_OS_*/ARGUS_EMBEDDING_* 를 Environment= 로 추가
Restart=on-failure
RestartSec=5
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload && systemctl enable --now argus-rag-worker-1
# N개 확장: unit 파일 복제(argus-rag-worker-2 …) — ARGUS_LOG_FILENAME 도 슬롯명으로
```

> 참고: 에이전트가 있는 호스트라면 이 unit 생성 자체를 플랫폼(에이전트 > 서비스/배포,
> method=systemd)이 대신해 준다 — 수동 unit 은 에이전트가 없거나 직접 관리가 필요할 때.

### 워커 env 옵션 레퍼런스

체크아웃 호스트(백엔드 config 존재)는 전부 생략 가능 — config 값이 쓰인다.
원격/컨테이너 워커는 연결정보를 env 로 직접 지정한다(플랫폼 배포는 자동 주입).

| env | 설명 |
|---|---|
| `ARGUS_DB_URL` | 잡 큐/메타 DB 접속 URL(`postgresql+asyncpg://…`) — **라우팅 가능한 주소**여야 함(localhost 금지, bridge/원격) |
| `ARGUS_OS_ENDPOINT` | MinIO/S3 엔드포인트 — 원본 문서를 읽는 필수 경로. 역시 라우팅 가능한 주소 |
| `ARGUS_OS_ACCESS_KEY` / `ARGUS_OS_SECRET_KEY` | 오브젝트 스토리지 자격증명 |
| `ARGUS_OS_BUCKET` | 문서 버킷 이름 |
| `ARGUS_OS_USE_SSL` | `true`/`false` — 엔드포인트 스킴과 일치시킬 것 |
| `ARGUS_EMBEDDING_SERVER_URL` / `ARGUS_EMBEDDING_MODEL` | 기동 시 기본 임베딩 연결(실제 값은 DB 설정 override 가 우선 — `load_into_runtime`) |
| `ARGUS_INGESTION_LOCAL_WORKER_ENABLED` | `true` — 워커 프로세스가 인제스천 루프를 돌게 함(워커 배포 시 필수) |
| `ARGUS_LOG_FILENAME` | 슬롯별 로그 파일명(예 `argus-rag-worker-1.log`) — 다중 워커 로그 충돌 방지 |
| `ARGUS_INGESTION_WORKER_ENABLED` | (API 프로세스용) `false` 면 in-process 워커 비활성 — 워커 분리 시 API 쪽에 지정 |

## B. Docker — 플랫폼 배포 (원격/에어갭 표준)

에이전트가 있는 호스트라면 **에이전트 > 서비스/배포**(kind=worker, method=docker,
replicas=N) 또는 `POST /api/v1/deploy` — 연결 env(DB/MinIO/임베딩) 자동 주입,
`argus-rag-worker-N` 슬롯으로 수평 확장, 서비스 관리 탭에서 라이프사이클 제어.

```bash
# 이미지 준비(백엔드와 동일 이미지 — docling 때문에 수 GB, 첫 빌드 오래 걸림)
docker build -t argus-rag-studio-backend:latest backend/
# 배포는 화면 또는 API 로 — 예:
curl -X POST http://<backend>:4700/api/v1/deploy -H "Authorization: Bearer <token>" \
  -H 'Content-Type: application/json' -d '{"spec":{"kind":"worker","replicas":4},
  "target":{"type":"agent_host","hostname":"<host>","method":"docker"}}'
```

- 주의: 이미지에 코드가 박제된다 — 파이프라인 코드 변경 시 이미지 재빌드+재배포.
  (체크아웃 호스트는 이 이유로 관리형 systemd 권장 — 위 "권장 배포 방식" 참조)
- 수동 docker run 이 필요하면 이름 `argus-rag-worker-N` + 라벨 `argus.kind=worker`
  규약을 지켜야 서비스 관리에 탐색된다(연결 env 는 옵션 레퍼런스 참조).

> 백엔드 API 자체의 컨테이너 실행(부트스트랩)은 `deploy/docker-compose.backend.yml`.

## 스케일링 가이드

- **워커 수** ≈ 동시 처리하고 싶은 문서 수. parse 가 무거운 docai/vlm 을 쓰면 워커당 CPU
  코어를 넉넉히. 무거운 파싱 워커는 가능하면 API 호스트와 **다른 호스트**로 분리.
- 임베딩 병목이면 워커가 아니라 **임베딩 GPU 서버(.48)** 쪽 배치/레플리카를 키운다.
- 파서는 컬렉션당 하나이므로, 무거운 docai 는 표·그림이 중요한 컬렉션에만 쓰고 나머지는
  text/layout 으로 두어 CPU 낭비를 줄인다.
