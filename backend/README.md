# Argus RAG Studio — Backend

FastAPI(async) + SQLAlchemy 2.0 + PostgreSQL(pgvector) 기반 RAG 서버.

## 구조

```
app/
├── core/          # config, config_loader, database, auth, security, logging, password_gate
├── auth/          # 로그인/리프레시/내 정보/비밀번호 변경 (로컬 JWT + Keycloak OIDC)
├── usermgr/       # 사용자·역할 CRUD
├── permissions/   # 역할별 메뉴/기능 권한 매트릭스
├── apikeys/       # API 키 발급/관리
├── collections/   # 지식베이스(컬렉션) CRUD + 임베딩 차원 검증
├── documents/     # 문서 CRUD (컬렉션 종속, 삭제 시 스토리지 스냅샷 정리)
├── chunks/        # 청크 조회/비교
├── ingestion/     # 인제스천 파이프라인 — 파싱전략/청킹/post_parse 변환(pii·image_captions)
├── imaging/       # 문서 내 이미지 추출기(포맷별)·변환
├── imagerecog/    # 이미지 추출·분석(VLM) 실행
├── annotations/   # 이미지 OCR 라벨링(bbox) + 탐색기
├── pipelines/     # 파이프라인 버전 자산(활성화/diff/롤백)
├── routing/       # 문서 라우팅 — 라우터 레지스트리(파일명/확장자/메타/경로) + 인테이크/스캔
├── sources/       # 스토리지 소스 레지스트리(S3·NAS 읽기 전용 어댑터 — 참조 인테이크)
├── retrieval/     # 하이브리드 검색(벡터+렉시컬+RRF)
├── rerank/        # 리랭킹(none/llm/cross_encoder)
├── generation/    # 질의·챗(SSE)·페더레이션
├── embedding/     # 임베딩 프로바이더(hash/openai_compatible)
├── vectorstore/   # 벡터 스토어 추상화(pgvector 등)
├── llm/           # LLM 클라이언트
├── evaluation/    # 골든 데이터셋·평가 Run·LLM-as-judge
├── feedback/      # 피드백 수집 → 골든셋 승격
├── observability/ # 질의 트레이스·통계
├── settings/      # 런타임 설정 override(argus_settings, EDITABLE 화이트리스트)
├── storage/       # 내부 오브젝트 스토리지 백엔드(S3/UC Volumes) + 버킷 보장
├── s3browse/      # S3 파일 브라우저 API
├── agent/         # 에이전트 등록/하트비트 수신
├── agentclient/   # 에이전트 원격 호출 클라이언트
├── servermgr/     # 배포 카탈로그(CONTAINER_KINDS)·컨테이너 스펙 빌더·설정 주입
├── deploy/        # 통합 배포 오케스트레이션(Docker/systemd/k8s) + 모델 준비(model_prep)
├── modelreg/      # 모델 레지스트리(사용자 등록) + Model Repository 보유 확인·서버 팩
├── extservers/    # 확장 서버(임베딩/리랭커/검출) 등록·모니터링
├── finetune/      # 파인튜닝(용어사전/라벨링/데이터셋/작업/모델)
├── pii/           # PII 정규식 마스킹 규칙
├── platform/      # 기반 환경 프로파일(standard/databricks)
├── workers/       # 워커 레지스트리(하트비트 · 리소스 메트릭)
├── worker_main.py # 독립 워커 진입점 (API 와 분리 실행)
└── main.py        # FastAPI 앱 (lifespan, 미들웨어, 라우터 등록)
```

도메인 모듈은 `models.py(ORM) → service.py(로직) → router.py(HTTP) → schemas.py(Pydantic)` 패턴을 따른다.
스키마(테이블)는 `packaging/config/argus-rag-studio-postgresql.sql` 이 단일 소스로 관리한다.

## 인증 (로컬 + Keycloak)

`config.properties` 의 `auth.type` 으로 전환한다.

- `auth.type=local` — `argus_users` 테이블 기반 로컬 JWT(HS256). 최초 기동 시 `admin/admin`
  계정이 시드되며 최초 로그인 시 비밀번호 변경이 강제된다(`must_change_password`).
- `auth.type=keycloak` — Keycloak password grant 로 토큰을 발급받고 JWKS 로 검증. `argus-admin`/
  `argus-superuser`/`argus-user` realm role 로 권한을 매핑하며, 로그인 시 `argus_users` 에 JIT 동기화.

JWT 서명키는 환경변수 `ARGUS_JWT_SECRET` 로 주입한다(운영 필수).

## 실행

```bash
# 1) 인프라 (DB + MinIO)
docker compose -f ../deploy/docker-compose.infra.yml up -d

# 2) 의존성 설치 + 개발 서버 (포트 4700, 설정은 packaging/config 사용)
make dev
make run

# 헬스체크
curl http://localhost:4700/health
# OpenAPI 문서: http://localhost:4700/docs
```

## 주요 엔드포인트

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | `/api/v1/auth/login` | 로그인 (local/keycloak 공통) |
| GET  | `/api/v1/auth/me` | 내 정보 |
| POST | `/api/v1/auth/change-password` | 비밀번호 변경 (로컬) |
| GET  | `/api/v1/auth/type` | 인증 모드 조회 |
| GET/POST | `/api/v1/collections` | 컬렉션 목록/생성 |
| GET/PUT/DELETE | `/api/v1/collections/{id}` | 컬렉션 단건 |
| GET/POST | `/api/v1/collections/{id}/documents` | 문서 목록/등록(메타) |
| GET/PUT/DELETE | `/api/v1/documents/{id}` | 문서 단건 |
| **POST** | **`/api/v1/collections/{id}/ingest`** | **파일 업로드 → 적재 → 인제스천 잡(202)** |
| POST | `/api/v1/ingestion/register` | NiFi 등 오브젝트 스토리지 경유 등록(서비스 토큰) |
| GET | `/api/v1/ingestion/jobs/{job_id}` | 인제스천 잡 진행률 |
| POST | `/api/v1/documents/{id}/reindex` | 문서 재처리(청크 교체) |
| POST | `/api/v1/collections/{id}/reindex` | 컬렉션 색인 설정 변경 + 전체 재인덱싱 |
| POST | `/api/v1/collections/{id}/search` · `/query` · `/chat` | 검색 / 인용 답변 / 챗(SSE) |
| **POST** | **`/api/v1/search/federated`** · **`/query/federated`** | **여러 컬렉션 페더레이션 검색·질의(RRF 병합)** |
| GET | `/api/v1/workers` | 워커 목록(생존·현재 잡·CPU/RAM/GPU 메트릭) |
| GET | `/api/v1/embedding/server-stats` | 확장 서버(임베딩·리랭커·검출) /stats 메트릭 |
| GET/POST | `/api/v1/usermgr/users` | 사용자 관리 (관리자) |

## 인제스천 (M2)

업로드/등록 → MinIO 적재 → **비동기 워커**가 `파싱 → 청킹 → 임베딩 → pgvector 인덱싱` 수행.
`rag_documents.status`: `registered → processing → indexed/failed`, `rag_ingestion_jobs` 로 진행률 추적.

**임베딩 프로바이더** (`embedding.provider`):
- `openai_compatible` — `embedding.server_url` 의 `/embeddings` 호출(TEI/Ollama-proxy/vLLM/OpenAI).
  임베딩 서버는 플랫폼 배포(에이전트 > 서비스/배포) 또는 수동 배포 — `deploy/embedding-server-deployment.md` 참조
- `hash` — 외부 서버 없이 결정적 더미 벡터 생성(개발/오프라인/에어갭·CI 검증용)

### 청킹 (chunking)

파싱 본문을 검색 단위(청크)로 나눈다. 컬렉션별 설정 `chunk_strategy`(전략) · `chunk_unit`(단위) ·
`chunk_size` · `chunk_overlap` 으로 제어하며, 변경 시 재인덱싱이 필요하다(생성 후 불변).
기본값은 `ingestion.chunk_strategy=recursive` / `chunk_unit=char` / `chunk_size=1000` / `chunk_overlap=150`.

**지원 전략 (`chunk_strategy`)** — 구현: [`app/ingestion/chunking.py`](app/ingestion/chunking.py)

| 전략 | 설명 | 권장 용도 |
| --- | --- | --- |
| `auto` | 내용 자동 선택 — 표·헤딩 있으면 `markdown`, 아니면 `recursive` | 형식이 섞인 지식베이스(기본 권장) |
| `recursive` | 구분자 우선순위(문단→줄→문장→공백)로 구조 보존하며 분할 | 범용 기본값 |
| `sentence` | 문장 경계 보존 + 그리디 묶음(한국어 kss, 약어·소수점 보호) | FAQ·QA, 한국어 |
| `paragraph` | 빈 줄(문단 경계) 보존 + 그리디 묶음(긴 문단은 recursive 폴백) | 산문·보고서·공지 |
| `section` | 섹션 헤더(마크다운 헤딩·setext·번호 `1.2`·`제N장`·`Chapter`) 경계 + 섹션 경로(`section_path`) | 매뉴얼·규정·논문 |
| `fixed` | 구분자 무시, 고정 길이 윈도우로 하드 컷 | 균일 길이 필요 시 |
| `markdown` | 표·코드블록 원자 보존 + 헤딩 경계 + 상위 헤딩 경로(breadcrumb) | `layout`/`docai`/`vlm` 파싱과 짝 |
| `semantic` | 문장 임베딩 인접 유사도가 급락하는 의미 경계에서 분할 | 가장 정교(문장별 임베딩 비용↑) |

**단위 (`chunk_unit`)** — `char`(문자, 기본) | `token`(tiktoken `cl100k_base`, 미설치 시 char 폴백).
`token` 은 임베딩 모델의 토큰 윈도우(보통 512)에 맞춰 자른다. `fixed`+`token` 조합이 곧 **Fixed Token Chunking**.

**공통 처리** — `recursive`/`sentence`/`paragraph`/`fixed` 는 오버랩(`chunk_overlap`)을 경계로 스마트 스냅해
부착하고, 예산 캡(오버랩 포함 `chunk_size` 이내)·작은 청크 병합(10% 미만) 품질 가드를 적용한다.
`markdown`/`section` 은 구조 보존이 우선이라 오버랩 대신 헤딩/섹션 경로로 연속성을 확보한다.
청크마다 위치 메타(`section_path`·`char_start`·`char_end`·`token_count`)를 함께 저장한다.

> 동작·예제·전략 선택 가이드 → [`docs` 청킹 처리 가이드](../docs/modules/ROOT/pages/kb/chunking.adoc)

## 워커 분리 배포 · 모니터링

대량 인제스천의 파싱(`docai` 등)은 CPU 바운드라, 워커가 API 와 같은 프로세스에서 돌면 응답이
느려진다. 워커를 별도 프로세스로 분리하고(임베딩은 이미 GPU 서버로 오프로드) 필요시 수평 확장한다.

- **API**: `ARGUS_INGESTION_WORKER_ENABLED=false` 로 띄우면 in-process 워커를 끈다 → `make run-api`
- **워커**: `python -m app.worker_main` (인제스천·평가·스윕 루프) → `make run-worker`. 큐가 `SKIP LOCKED`
  라 여러 개 띄워도 한 잡을 한 워커만 처리(수평 확장)
- **Docker(부트스트랩)**: 백엔드 API 컨테이너 — `deploy/docker-compose.backend.yml`. 워커는 플랫폼 배포(에이전트 > 서비스/배포)가 표준 — `deploy/workers-deployment.md`
- **모니터링**: 워커는 기동 시 `argus_workers` 에 등록하고 5초마다 하트비트(+psutil/NVML 리소스 메트릭)를
  upsert. `GET /api/v1/workers` 가 생존(alive)·현재 잡·처리량·프로세스/호스트 CPU·RAM·GPU 를 반환
  (Frontend 잡 모니터링 **워커** 탭에서 막대로 표시)

> 배포·스케일링 가이드 → [`deploy/workers-deployment.md`](../deploy/workers-deployment.md)
