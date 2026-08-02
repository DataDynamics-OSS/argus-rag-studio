-- Argus RAG Studio Server - PostgreSQL DDL
-- 스키마는 이 DDL 이 단일 소스로 관리한다(런타임 ORM create_all 사용 안 함).
-- 정합 앱 버전: 0.1.2 — 스키마를 바꾸는 릴리스에서 이 줄을 함께 갱신한다(VERSIONING.md).

CREATE EXTENSION IF NOT EXISTS vector;

-- ---------------------------------------------------------------------------
-- Role Management
--   argus_users 가 role_id FK 로 참조하므로 반드시 먼저 생성해야 한다.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS argus_roles (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) NOT NULL,
    description VARCHAR(255),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    role_id VARCHAR(50) NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_argus_roles_role_id ON argus_roles USING btree (role_id);

-- ---------------------------------------------------------------------------
-- User Management (로컬 인증 계정 + Keycloak JIT 동기화 사본)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS argus_users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) NOT NULL UNIQUE,
    email VARCHAR(255) NOT NULL UNIQUE,
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,
    organization VARCHAR(100),
    department VARCHAR(100),
    phone_number VARCHAR(30),
    password_hash VARCHAR(255) NOT NULL,
    status VARCHAR(20) NOT NULL,
    -- 최초 로그인 시 비밀번호 강제 변경 플래그
    must_change_password BOOLEAN NOT NULL DEFAULT false,
    role_id INT NOT NULL REFERENCES argus_roles(id),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- User Preferences (토큰 sub 를 키로 로컬·Keycloak 인증 공용)
--   로컬 인증: sub = str(argus_users.id) / Keycloak: sub = user UUID
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS argus_user_preferences (
    sub VARCHAR(100) PRIMARY KEY,
    avatar_preset_id VARCHAR(50),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- RAG: Collection (지식베이스)
--   임베딩 모델/차원/거리 메트릭을 생성 시점에 고정하는 벡터 공간 경계.
--   rag_eval_datasets 등이 FK 로 참조하므로 평가 섹션보다 먼저 생성해야 한다.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS rag_collections (
    id SERIAL PRIMARY KEY,
    collection_id VARCHAR(36) NOT NULL UNIQUE,
    name VARCHAR(200) NOT NULL UNIQUE,
    description TEXT,
    -- 임베딩(벡터 공간) 설정 — 컬렉션별 상이 가능, 생성 후 불변. server_url NULL 이면 전역 상속.
    embedding_provider VARCHAR(30) NOT NULL DEFAULT 'openai_compatible',  -- openai_compatible | hash
    embedding_model VARCHAR(200) NOT NULL,
    embedding_dim INT NOT NULL,
    embedding_server_url VARCHAR(500),
    distance_metric VARCHAR(20) NOT NULL DEFAULT 'cosine',
    rerank_provider VARCHAR(20) NOT NULL DEFAULT 'none',  -- none | llm | cross_encoder (쿼리 시점, 재인덱싱 불필요)
    rerank_model VARCHAR(200),                            -- cross_encoder 리랭커 모델(선택, 비면 서버 기본)
    -- 파싱 전략 — 컬렉션별, 변경 시 재인덱싱 필요.
    parse_strategy VARCHAR(20) NOT NULL DEFAULT 'text',  -- auto | text | layout | docai | vlm | rhwp
    -- 청킹 전략 — 컬렉션별, 변경 시 재인덱싱 필요.
    chunk_strategy VARCHAR(20) NOT NULL DEFAULT 'recursive',  -- auto | recursive | sentence | fixed | markdown | semantic
    chunk_unit VARCHAR(10) NOT NULL DEFAULT 'char',          -- char | token (tiktoken)
    chunk_size INT NOT NULL DEFAULT 1000,
    chunk_overlap INT NOT NULL DEFAULT 150,
    ingestion_pipeline JSONB,                                -- 보강 파이프라인 {post_parse,post_chunk}; NULL=기본
    ephemeral_sweep_id INT,                                  -- 스윕이 만든 임시 후보 컬렉션 표식(종료 시 정리)
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    created_by VARCHAR(200),
    updated_by VARCHAR(200),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_rag_collections_status ON rag_collections USING btree (status);

-- ---------------------------------------------------------------------------
-- RAG: Evaluation (M4 — 골든셋 · 평가 Run · 항목별 결과)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS rag_eval_datasets (
    id SERIAL PRIMARY KEY,
    dataset_id VARCHAR(36) NOT NULL UNIQUE,
    name VARCHAR(200) NOT NULL UNIQUE,
    description TEXT,
    collection_id INT REFERENCES rag_collections(id) ON DELETE SET NULL,
    created_by VARCHAR(200),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS rag_eval_items (
    id SERIAL PRIMARY KEY,
    item_id VARCHAR(36) NOT NULL UNIQUE,
    dataset_id INT NOT NULL REFERENCES rag_eval_datasets(id) ON DELETE CASCADE,
    question TEXT NOT NULL,
    expected_answer TEXT,
    expected_sources TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_rag_eval_items_dataset ON rag_eval_items USING btree (dataset_id);

CREATE TABLE IF NOT EXISTS rag_eval_runs (
    id SERIAL PRIMARY KEY,
    run_id VARCHAR(36) NOT NULL UNIQUE,
    dataset_id INT NOT NULL REFERENCES rag_eval_datasets(id) ON DELETE CASCADE,
    collection_id INT NOT NULL,
    pipeline_id INT,                       -- 적용한 파이프라인(활성 버전 설정으로 실행). NULL=직접 설정
    sweep_id INT,                          -- 설정 스윕 소속(rag_eval_sweeps.id). NULL=일반 Run
    config_json TEXT,                      -- 이 Run 의 전체 설정 JSON 스냅샷(스윕 리더보드·재현용)
    status VARCHAR(20) NOT NULL DEFAULT 'queued',
    mode VARCHAR(20) NOT NULL DEFAULT 'hybrid',
    distance_metric VARCHAR(20),           -- 평가 대상 컬렉션의 벡터 거리 메트릭
    rerank BOOLEAN NOT NULL DEFAULT false,
    judge BOOLEAN NOT NULL DEFAULT false,
    top_k INT NOT NULL DEFAULT 5,
    total_items INT NOT NULL DEFAULT 0,
    completed_items INT NOT NULL DEFAULT 0,
    hit_rate DOUBLE PRECISION,
    mrr DOUBLE PRECISION,
    faithfulness DOUBLE PRECISION,
    answer_relevance DOUBLE PRECISION,
    correctness DOUBLE PRECISION,
    error TEXT,
    created_by VARCHAR(200),
    created_at TIMESTAMPTZ DEFAULT now(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_rag_eval_runs_dataset ON rag_eval_runs USING btree (dataset_id);
CREATE INDEX IF NOT EXISTS idx_rag_eval_runs_status ON rag_eval_runs USING btree (status);

CREATE TABLE IF NOT EXISTS rag_eval_results (
    id SERIAL PRIMARY KEY,
    run_id INT NOT NULL REFERENCES rag_eval_runs(id) ON DELETE CASCADE,
    item_id INT NOT NULL,
    question TEXT NOT NULL,
    answer TEXT,
    retrieved_docs TEXT,
    hit BOOLEAN,
    reciprocal_rank DOUBLE PRECISION,
    faithfulness DOUBLE PRECISION,
    answer_relevance DOUBLE PRECISION,
    correctness DOUBLE PRECISION,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_rag_eval_results_run ON rag_eval_results USING btree (run_id);

-- 설정 스윕(AutoML식 옵션 탐색) — 여러 설정 조합을 Run 으로 만들어 베스트를 찾는다.
CREATE TABLE IF NOT EXISTS rag_eval_sweeps (
    id SERIAL PRIMARY KEY,
    sweep_id VARCHAR(36) NOT NULL UNIQUE,
    name VARCHAR(200) NOT NULL,
    dataset_id INT NOT NULL REFERENCES rag_eval_datasets(id) ON DELETE CASCADE,
    base_collection_id INT NOT NULL,
    search_space TEXT NOT NULL,            -- JSON: {index_axis, query_axis}
    primary_metric VARCHAR(30) NOT NULL DEFAULT 'hit_rate',
    judge BOOLEAN NOT NULL DEFAULT false,
    judge_top_n INT,                       -- judge 게이팅: 검색 점수 상위 N개만 judge 재실행(NULL=게이팅 없음)
    holdout_ratio DOUBLE PRECISION NOT NULL DEFAULT 0,  -- 0~0.9. >0 이면 train 으로 선정·holdout 으로 검증
    max_runs INT NOT NULL DEFAULT 64,
    status VARCHAR(20) NOT NULL DEFAULT 'queued',  -- queued|indexing|running|judging|succeeded|failed|canceled
    total_runs INT NOT NULL DEFAULT 0,
    completed_runs INT NOT NULL DEFAULT 0,
    candidate_collections TEXT,            -- JSON: [{collection_id, index_config, ephemeral}]
    best_run_id INT,
    error TEXT,
    created_by VARCHAR(200),
    created_at TIMESTAMPTZ DEFAULT now(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_rag_eval_sweeps_status ON rag_eval_sweeps USING btree (status);
CREATE INDEX IF NOT EXISTS idx_rag_eval_sweeps_dataset ON rag_eval_sweeps USING btree (dataset_id);
CREATE INDEX IF NOT EXISTS idx_rag_eval_runs_sweep ON rag_eval_runs USING btree (sweep_id);

-- ---------------------------------------------------------------------------
-- RAG: Query Trace (운영 — 질의 단계별 지연 · 토큰 · 상태)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS rag_query_traces (
    id SERIAL PRIMARY KEY,
    trace_id VARCHAR(36) NOT NULL UNIQUE,
    kind VARCHAR(10) NOT NULL,        -- search | query | chat
    collection_id INT,
    query TEXT,
    mode VARCHAR(20),
    distance_metric VARCHAR(20),       -- 벡터 검색 거리 메트릭(렉시컬이면 미사용)
    rerank BOOLEAN NOT NULL DEFAULT false,
    status VARCHAR(10) NOT NULL DEFAULT 'ok',
    error TEXT,
    hit_count INT NOT NULL DEFAULT 0,
    embedding_ms DOUBLE PRECISION,         -- 쿼리 임베딩 시간(검색 세부)
    search_ms DOUBLE PRECISION,            -- 벡터(+렉시컬) 검색·융합 시간(검색 세부)
    retrieval_ms DOUBLE PRECISION,         -- 검색 단계 총합(임베딩+검색)
    rerank_ms DOUBLE PRECISION,
    generation_ms DOUBLE PRECISION,
    total_ms DOUBLE PRECISION,
    prompt_tokens INT,
    completion_tokens INT,
    answer TEXT,
    created_by VARCHAR(200),
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_rag_query_traces_created ON rag_query_traces USING btree (created_at);
CREATE INDEX IF NOT EXISTS idx_rag_query_traces_collection ON rag_query_traces USING btree (collection_id);
CREATE INDEX IF NOT EXISTS idx_rag_query_traces_status ON rag_query_traces USING btree (status);

-- ---------------------------------------------------------------------------
-- RAG: Pipeline (버전 가능한 RAG 설정 — 검색/리랭크/생성)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS rag_pipelines (
    id SERIAL PRIMARY KEY,
    pipeline_id VARCHAR(36) NOT NULL UNIQUE,
    name VARCHAR(200) NOT NULL UNIQUE,
    description TEXT,
    stage VARCHAR(20) NOT NULL DEFAULT 'dev',
    active_version INT NOT NULL DEFAULT 1,
    created_by VARCHAR(200),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS rag_pipeline_versions (
    id SERIAL PRIMARY KEY,
    pipeline_id INT NOT NULL REFERENCES rag_pipelines(id) ON DELETE CASCADE,
    version INT NOT NULL,
    config_json TEXT NOT NULL,
    note TEXT,
    created_by VARCHAR(200),
    created_at TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT uq_pipeline_version UNIQUE (pipeline_id, version)
);

CREATE INDEX IF NOT EXISTS idx_rag_pipeline_versions_pipeline ON rag_pipeline_versions USING btree (pipeline_id);

-- ---------------------------------------------------------------------------
-- RAG: 문서 라우팅 정책 (인제스천 전 "어느 컬렉션으로 보낼지" 결정 — Phase 1)
--   정책은 단일 'default' 자산. 라우터 조합(app/routing 레지스트리)을 버전 가능하게 보관하고
--   active_version 이 인테이크가 사용할 버전을 가리킨다(rag_pipelines 와 동형).
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS rag_routing_policies (
    id SERIAL PRIMARY KEY,
    policy_id VARCHAR(36) NOT NULL UNIQUE,
    name VARCHAR(200) NOT NULL UNIQUE,
    description TEXT,
    active_version INT NOT NULL DEFAULT 1,
    created_by VARCHAR(200),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS rag_routing_policy_versions (
    id SERIAL PRIMARY KEY,
    policy_id INT NOT NULL REFERENCES rag_routing_policies(id) ON DELETE CASCADE,
    version INT NOT NULL,
    config_json TEXT NOT NULL,   -- RoutingPolicyConfig JSON {mode, stages, fallback_collection_id, review_below}
    note TEXT,
    created_by VARCHAR(200),
    created_at TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT uq_routing_policy_version UNIQUE (policy_id, version)
);

CREATE INDEX IF NOT EXISTS idx_rag_routing_policy_versions_policy ON rag_routing_policy_versions USING btree (policy_id);

-- 라우팅 결정 감사 로그 — 인테이크 1건당 1행(선택 컬렉션·신뢰도·라우터별 trace).
-- review=true 행을 모아 검토 큐로 쓴다(Phase 3 UI).
CREATE TABLE IF NOT EXISTS rag_routing_decisions (
    id SERIAL PRIMARY KEY,
    decision_id VARCHAR(36) NOT NULL UNIQUE,
    document_id INT NOT NULL REFERENCES rag_documents(id) ON DELETE CASCADE,
    collection_id INT REFERENCES rag_collections(id) ON DELETE SET NULL,
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
    mode VARCHAR(20),
    matched_router VARCHAR(60),
    fallback_used BOOLEAN NOT NULL DEFAULT false,
    review BOOLEAN NOT NULL DEFAULT false,
    policy_version INT,
    trace_json TEXT,
    created_by VARCHAR(200),
    created_at TIMESTAMPTZ DEFAULT now(),
    -- 검토 처리 기록(검토 큐 UI) — 확인/재배정 시 채워짐. corrected 는 재배정 시에만.
    reviewed_at TIMESTAMPTZ,
    reviewed_by VARCHAR(200),
    corrected_collection_id INT REFERENCES rag_collections(id) ON DELETE SET NULL
);

-- (마이그레이션) 기존 환경 컬럼 보강 — 멱등.
ALTER TABLE rag_routing_decisions ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ;
ALTER TABLE rag_routing_decisions ADD COLUMN IF NOT EXISTS reviewed_by VARCHAR(200);
ALTER TABLE rag_routing_decisions ADD COLUMN IF NOT EXISTS corrected_collection_id INT REFERENCES rag_collections(id) ON DELETE SET NULL;

-- 라우팅 디스크립터(Phase 2) — 내용 임베딩 라우터의 컬렉션 centroid(라우팅 공간 = 전역
-- 임베딩 설정). 컬렉션 벡터 공간(불변)과 무관한 사이드 테이블. 공간 불일치 행은 stale.
CREATE TABLE IF NOT EXISTS rag_routing_profiles (
    collection_id INT PRIMARY KEY REFERENCES rag_collections(id) ON DELETE CASCADE,
    centroid_json TEXT NOT NULL,           -- L2 정규화 float 배열(JSON) — pgvector 미사용(공간 가변)
    space_provider VARCHAR(50) NOT NULL,
    space_model VARCHAR(200) NOT NULL,
    space_dim INT NOT NULL,
    source VARCHAR(20) NOT NULL DEFAULT 'chunks',   -- chunks | description
    sample_count INT NOT NULL DEFAULT 0,
    built_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_rag_routing_decisions_document ON rag_routing_decisions USING btree (document_id);
CREATE INDEX IF NOT EXISTS idx_rag_routing_decisions_review ON rag_routing_decisions USING btree (review);

-- 기본 라우팅 정책 시드 — 단일 'default'(빈 stage = 항상 폴백). 이름 기준 멱등.
INSERT INTO rag_routing_policies (policy_id, name, description, active_version, created_by)
SELECT 'seed-routing-default', 'default', '기본 라우팅 정책', 1, 'system'
WHERE NOT EXISTS (SELECT 1 FROM rag_routing_policies p WHERE p.name = 'default');

INSERT INTO rag_routing_policy_versions (policy_id, version, config_json, note, created_by)
SELECT p.id, 1, '{"mode":"first_match","stages":[],"fallback_collection_id":null,"review_below":0.5}', 'initial', 'system'
FROM rag_routing_policies p
WHERE p.name = 'default'
  AND NOT EXISTS (
    SELECT 1 FROM rag_routing_policy_versions v WHERE v.policy_id = p.id AND v.version = 1
  );

-- ---------------------------------------------------------------------------
-- RAG: 스토리지 소스 레지스트리 (참조 인테이크의 원본 소스 — 읽기 전용, app/sources)
--   내부 저장소(object_storage 설정)와 별개로, 문서를 "소스 ID + 경로"로 가져올(pull)
--   S3·NAS 소스를 등록한다. name 은 라우팅 규칙(path_rule 의 storage 필터)이 참조하는
--   논리 식별자. 자격증명은 secret_enc(Fernet 암호화)에만 두고 API 응답에 노출하지 않는다.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS rag_storage_sources (
    id SERIAL PRIMARY KEY,
    source_id VARCHAR(36) NOT NULL UNIQUE,
    name VARCHAR(200) NOT NULL UNIQUE,
    kind VARCHAR(20) NOT NULL,               -- s3 | nas
    description TEXT,
    config_json TEXT NOT NULL DEFAULT '{}',  -- 비밀 아닌 설정(s3: endpoint/bucket/base_prefix/region, nas: mount_path/base_prefix)
    secret_enc TEXT,                         -- 자격증명(Fernet 암호화)
    enabled BOOLEAN NOT NULL DEFAULT true,
    created_by VARCHAR(200),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);


-- ---------------------------------------------------------------------------
-- RAG: 소스 워치 (드롭존 무인화 — app/sourcewatch, design/source-watch.md)
--   워치=소스+폴더+주기. seen 은 증분 스캔 캐시(최적화 — 지워져도 content_hash 가 정확성 보장).
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS rag_source_watches (
    id SERIAL PRIMARY KEY,
    watch_id VARCHAR(36) NOT NULL UNIQUE,
    source_id INTEGER NOT NULL REFERENCES rag_storage_sources(id) ON DELETE CASCADE,
    name VARCHAR(200) NOT NULL,
    prefix VARCHAR(2000) NOT NULL DEFAULT '',
    recursive BOOLEAN NOT NULL DEFAULT true,
    interval_seconds INTEGER NOT NULL DEFAULT 300,
    enabled BOOLEAN NOT NULL DEFAULT true,
    next_run_at TIMESTAMPTZ DEFAULT now(),
    last_run_at TIMESTAMPTZ,
    last_status VARCHAR(20),                -- ok | error | NULL(미실행)
    last_error TEXT,
    last_counts_json TEXT,                  -- 마지막 실행 집계(UI 표시)
    consecutive_failures INTEGER NOT NULL DEFAULT 0,  -- 백오프 계산용
    created_by VARCHAR(200),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_source_watches_due
    ON rag_source_watches USING btree (enabled, next_run_at);

CREATE TABLE IF NOT EXISTS rag_source_watch_runs (
    id SERIAL PRIMARY KEY,
    watch_id INTEGER NOT NULL REFERENCES rag_source_watches(id) ON DELETE CASCADE,
    started_at TIMESTAMPTZ DEFAULT now(),
    finished_at TIMESTAMPTZ,
    scanned INTEGER NOT NULL DEFAULT 0,
    skipped INTEGER NOT NULL DEFAULT 0,     -- seen 지문 동일로 건너뜀
    counts_json TEXT,                       -- {"routed":3,"duplicate":45,...}
    truncated BOOLEAN NOT NULL DEFAULT false,
    error TEXT
);

CREATE INDEX IF NOT EXISTS idx_source_watch_runs_watch
    ON rag_source_watch_runs USING btree (watch_id, started_at DESC);

CREATE TABLE IF NOT EXISTS rag_source_seen_files (
    id SERIAL PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES rag_storage_sources(id) ON DELETE CASCADE,
    path VARCHAR(2000) NOT NULL,
    size BIGINT NOT NULL DEFAULT 0,
    mtime TIMESTAMPTZ,                      -- 지문(list 결과로 비교 — 추가 I/O 없음)
    status VARCHAR(20) NOT NULL,            -- routed | duplicate | no_route | failed
    policy_version INTEGER,                 -- no_route/failed 재평가 판단용
    last_seen_at TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT uq_source_seen_path UNIQUE (source_id, path)
);

CREATE INDEX IF NOT EXISTS idx_source_seen_prune
    ON rag_source_seen_files USING btree (last_seen_at);

-- ---------------------------------------------------------------------------
-- RAG: 모델 레지스트리 (시스템이 사용하는 모델 가중치의 선언 — app/modelreg)
--   design/model-registry.md. (kind, name) 은 Model Repository(argus-models 버킷)의
--   키 규약 {kind}/{name}/{revision}/ 과 결합. repo 가 HF 연결 고리(팩·온라인 폴백·
--   hf-cache 디렉터리명). 시드는 기동 시 앱이 투입(builtin).
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS rag_model_registry (
    id SERIAL PRIMARY KEY,
    model_id VARCHAR(36) NOT NULL UNIQUE,
    kind VARCHAR(20) NOT NULL,                      -- embedding | reranker | vlm | detection
    name VARCHAR(200) NOT NULL,                     -- 논리명(버킷 키·served-model-name)
    repo VARCHAR(300) NOT NULL,                     -- HF repo id (org/name)
    revision VARCHAR(100) NOT NULL DEFAULT 'main',
    source VARCHAR(20) NOT NULL DEFAULT 'hf',       -- hf | paddle(수동 반입)
    target VARCHAR(20) NOT NULL DEFAULT 'hf-cache', -- hf-cache | flat (전개 레이아웃)
    params_json TEXT NOT NULL DEFAULT '{}',         -- kind 별 부가(max_len, approx_gb...)
    note TEXT,
    enabled BOOLEAN NOT NULL DEFAULT true,          -- 비활성화 = 배포 선택에서 제외
    builtin BOOLEAN NOT NULL DEFAULT false,         -- 시드 여부(삭제 대신 비활성화)
    created_by VARCHAR(200),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT uq_model_registry_kind_name UNIQUE (kind, name)
);

-- 모델 카탈로그 시드 — 검증된 추천 모델(기본 비활성 = 배포 선택 목록 미노출, 필요 시
-- 화면에서 활성화). 동작 필수 최소 셋(기본 VLM·운영 임베딩/리랭커·검출)은 앱 시드
-- (backend/app/modelreg/seeds.py — 외부망 pack_model 폴백 겸용)가 투입하고, 그 외
-- 모델은 이 목록(DB)이 단일 출처다. (kind, name) 기준 멱등 — 이미 있으면 건너뜀.
-- note 서식: 1행 = 핵심 요약(목록 표시), 2행~ = 특징·추천 이유·제약(툴팁 표시).
INSERT INTO rag_model_registry (model_id, kind, name, repo, revision, source, target, params_json, note, enabled, builtin, created_by)
SELECT v.model_id, v.kind, v.name, v.repo, 'main', 'hf', v.target, v.params_json, v.note, false, false, 'catalog'
FROM (VALUES
    -- vlm (target=flat — vLLM 로컬 경로 서빙)
    ('cat-qwen2-vl-2b',           'vlm', 'qwen2-vl-2b',    'Qwen/Qwen2-VL-2B-Instruct',    'flat', '{"max_len": 8192, "approx_gb": 5}',
     E'경량(저사양 GPU)\n7B 대비 인식 정밀도는 낮지만 VRAM 8GB급에서 구동 가능. 단순 이미지 분류 등 가벼운 파이프라인용.'),
    ('cat-qwen2.5-vl-3b',         'vlm', 'qwen2.5-vl-3b',  'Qwen/Qwen2.5-VL-3B-Instruct',  'flat', '{"max_len": 8192, "approx_gb": 8}',
     E'차세대 경량\nQwen2.5-VL 세대(2025.1) — 2세대 대비 문서 파싱·구조 인식 개선. 저사양 GPU용.'),
    ('cat-qwen2.5-vl-7b',         'vlm', 'qwen2.5-vl-7b',  'Qwen/Qwen2.5-VL-7B-Instruct',  'flat', '{"max_len": 8192, "approx_gb": 16}',
     E'차세대 표준\n현행 운영 모델(qwen2-vl-7b)의 후속 — 동급 크기에서 OCR·문서 이해 개선. 운영 업그레이드 1순위 후보.'),
    ('cat-qwen2.5-vl-32b',        'vlm', 'qwen2.5-vl-32b', 'Qwen/Qwen2.5-VL-32B-Instruct', 'flat', '{"max_len": 8192, "approx_gb": 66}',
     E'고성능(대형 GPU)\n복잡한 표·도면 해석용 대형 모델. VRAM 70GB+ 또는 텐서 병렬 필요 — DGX급 장비 전용.'),
    ('cat-qwen3-vl-2b',           'vlm', 'qwen3-vl-2b',    'Qwen/Qwen3-VL-2B-Instruct',    'flat', '{"max_len": 8192, "approx_gb": 5}',
     E'3세대 초경량\nQwen3-VL 2B(Apache-2.0, 2025.10). 저사양 GPU용. vLLM 최신 버전 필요 — 에어갭 vLLM 이미지 버전 확인.'),
    ('cat-qwen3-vl-4b',           'vlm', 'qwen3-vl-4b',    'Qwen/Qwen3-VL-4B-Instruct',    'flat', '{"max_len": 8192, "approx_gb": 9}',
     E'3세대 경량\nQwen3-VL 4B(Apache-2.0, 2025.10). VRAM 12GB급. vLLM 최신 버전 필요 — 에어갭 vLLM 이미지 버전 확인.'),
    ('cat-qwen3-vl-8b',           'vlm', 'qwen3-vl-8b',    'Qwen/Qwen3-VL-8B-Instruct',    'flat', '{"max_len": 8192, "approx_gb": 18}',
     E'3세대 표준 — 문서 인식 대폭 개선(추천)\nQwen3-VL 세대(2025.10, Apache-2.0). OCR·표/차트·다국어 문서 이해가 2.5세대 대비 개선 — 차기 운영 후보. vLLM 최신 버전 필요 — 에어갭 vLLM 이미지 버전 확인.'),
    ('cat-internvl3-8b',          'vlm', 'internvl3-8b',   'OpenGVLab/InternVL3-8B',       'flat', '{"max_len": 8192, "approx_gb": 16}',
     E'Qwen 외 대안 계열 — 문서 이해 강점\nOpenGVLab InternVL3(8B). 문서·차트 벤치마크 강세, vLLM 지원. 라이선스 MIT 표기이나 Qwen2.5 파생 — 반출 승인 시 재확인.'),
    ('cat-gemma-3-12b-it',        'vlm', 'gemma-3-12b-it', 'google/gemma-3-12b-it',        'flat', '{"max_len": 8192, "approx_gb": 24}',
     E'멀티모달 대안(Google)\nGemma 3 12B 멀티모달(vLLM 지원). HF gated repo — 팩 시 라이선스 동의·토큰 필요, Gemma 사용 조건 고지 필수.'),
    -- embedding (target=hf-cache — 이름으로 오프라인 캐시 조회)
    ('cat-bge-large-en-v1.5',     'embedding', 'bge-large-en-v1.5',              'BAAI/bge-large-en-v1.5',                   'hf-cache', '{"approx_gb": 1.3, "dim": 1024}',
     E'영문\nBAAI 영문 임베딩(335M, dim 1024, MIT). 영문 전용(다국어 불가) — mxbai 와 동급 대안.'),
    ('cat-bge-m3',                'embedding', 'bge-m3',                         'BAAI/bge-m3',                              'hf-cache', '{"approx_gb": 2.3, "dim": 1024}',
     E'다국어 임베딩 표준 — 한국어 강함(추천)\nBAAI 3세대 임베딩(568M, dim 1024, MIT). 다국어 RAG 의 사실상 표준으로 한국어 벤치마크 상위권, 8192 토큰 장문 지원. 한국어 지식베이스 기본 후보.'),
    ('cat-kure-v1',               'embedding', 'kure-v1',                        'nlpai-lab/KURE-v1',                        'hf-cache', '{"approx_gb": 2.3, "dim": 1024}',
     E'한국어 특화 임베딩 — 한국어 검색 최상위(추천)\n고려대 NLP&AI 연구실의 bge-m3 한국어 파인튜닝(568M, dim 1024, MIT). 한국어 검색 벤치마크에서 원본 bge-m3 상회 — HWP 등 한국어 문서 중심 지식베이스에 최적.'),
    ('cat-qwen3-embedding-0.6b',  'embedding', 'qwen3-embedding-0.6b',           'Qwen/Qwen3-Embedding-0.6B',                'hf-cache', '{"approx_gb": 1.2, "dim": 1024}',
     E'경량 다국어 — MTEB 상위권\nQwen3 기반(0.6B, dim 1024, Apache-2.0, 2025.6). 32k 컨텍스트, 경량 대비 다국어 성능 우수. instruction-aware — 쿼리 프리픽스 설정 확인 필요.'),
    ('cat-qwen3-embedding-4b',    'embedding', 'qwen3-embedding-4b',             'Qwen/Qwen3-Embedding-4B',                  'hf-cache', '{"approx_gb": 8, "dim": 2560}',
     E'고성능 다국어(GPU 필요)\nQwen3 임베딩 4B(dim 2560, Apache-2.0). MTEB 다국어 최상위권. dim 이 2560 이라 기존 1024 컬렉션과 호환 안 됨 — 신규 지식베이스용.'),
    ('cat-arctic-embed-l-v2.0',   'embedding', 'snowflake-arctic-embed-l-v2.0',  'Snowflake/snowflake-arctic-embed-l-v2.0',  'hf-cache', '{"approx_gb": 1.2, "dim": 1024}',
     E'다국어 검색 특화\nSnowflake 임베딩(568M, dim 1024, Apache-2.0). retrieval 최적화·8192 토큰, 상업 사용 제약 없음.'),
    ('cat-me5-large-instruct',    'embedding', 'multilingual-e5-large-instruct', 'intfloat/multilingual-e5-large-instruct',  'hf-cache', '{"approx_gb": 1.1, "dim": 1024}',
     E'현행 e5-large 개선판\ninstruct 튜닝으로 다국어 검색 성능 향상(560M, dim 1024, MIT). 쿼리 instruction 프리픽스 필요 — 임베딩 서버 설정 확인 후 도입.'),
    ('cat-gte-multilingual-base', 'embedding', 'gte-multilingual-base',          'Alibaba-NLP/gte-multilingual-base',        'hf-cache', '{"approx_gb": 0.6, "dim": 768}',
     E'경량 다국어(305M)\nAlibaba GTE 계열(dim 768, Apache-2.0), 8192 토큰. 저사양 다국어 후보. trust_remote_code 필요 — 임베딩 서버 허용 여부 확인.'),
    -- reranker (target=hf-cache)
    ('cat-bge-reranker-v2-m3-ko', 'reranker', 'bge-reranker-v2-m3-ko',           'dragonkue/bge-reranker-v2-m3-ko',          'hf-cache', '{"approx_gb": 2.3}',
     E'한국어 파인튜닝 리랭커(추천)\n운영 중인 bge-reranker-v2-m3 의 한국어 파인튜닝(568M, Apache-2.0) — 드롭인 교체 가능, 한국어 재순위 품질 개선 기대.'),
    ('cat-gte-ml-reranker-base',  'reranker', 'gte-multilingual-reranker-base',  'Alibaba-NLP/gte-multilingual-reranker-base', 'hf-cache', '{"approx_gb": 0.6}',
     E'경량 다국어 리랭커(306M)\nApache-2.0. 저사양·저지연 재순위용. trust_remote_code 필요 — 리랭커 서버 허용 여부 확인.'),
    ('cat-ms-marco-minilm-l6-v2', 'reranker', 'ms-marco-minilm-l6-v2',           'cross-encoder/ms-marco-MiniLM-L6-v2',      'hf-cache', '{"approx_gb": 0.1}',
     E'초경량 영문 cross-encoder(~90MB)\nCPU 서빙 가능 — 스모크 테스트·저사양 환경용. 영문 전용.'),
    ('cat-qwen3-reranker-0.6b',   'reranker', 'qwen3-reranker-0.6b',             'Qwen/Qwen3-Reranker-0.6B',                 'hf-cache', '{"approx_gb": 1.2}',
     E'LLM 방식 리랭커 — 성능 상위권\nQwen3 기반(0.6B, Apache-2.0, 2025.6). cross-encoder API 가 아닌 생성형 채점 방식 — 현행 리랭커 서버 호환 확인 후 활성화.')
) AS v(model_id, kind, name, repo, target, params_json, note)
WHERE NOT EXISTS (SELECT 1 FROM rag_model_registry m WHERE m.kind = v.kind AND m.name = v.name);

-- (일회성 마이그레이션) 앱 시드 축소(2026-07-11)로 카탈로그로 이관된 구 시드 —
-- builtin 해제(삭제 허용)·비고 갱신. created_by='seed' 가드로 재실행 시 no-op.
UPDATE rag_model_registry m
SET builtin = false, created_by = 'catalog', note = v.note, updated_at = now()
FROM (VALUES
    ('vlm', 'qwen2-vl-2b',    E'경량(저사양 GPU)\n7B 대비 인식 정밀도는 낮지만 VRAM 8GB급에서 구동 가능. 단순 이미지 분류 등 가벼운 파이프라인용.'),
    ('vlm', 'qwen2.5-vl-3b',  E'차세대 경량\nQwen2.5-VL 세대(2025.1) — 2세대 대비 문서 파싱·구조 인식 개선. 저사양 GPU용.'),
    ('vlm', 'qwen2.5-vl-7b',  E'차세대 표준\n현행 운영 모델(qwen2-vl-7b)의 후속 — 동급 크기에서 OCR·문서 이해 개선. 운영 업그레이드 1순위 후보.'),
    ('vlm', 'qwen2.5-vl-32b', E'고성능(대형 GPU)\n복잡한 표·도면 해석용 대형 모델. VRAM 70GB+ 또는 텐서 병렬 필요 — DGX급 장비 전용.'),
    ('embedding', 'bge-large-en-v1.5', E'영문\nBAAI 영문 임베딩(335M, dim 1024, MIT). 영문 전용(다국어 불가) — mxbai 와 동급 대안.')
) AS v(kind, name, note)
WHERE m.kind = v.kind AND m.name = v.name AND m.created_by = 'seed';

-- (일회성 마이그레이션) 유지 시드의 비고 서식 갱신(1행 핵심 + 2행~ 특징) —
-- 원본 한 줄 비고와 정확히 일치할 때만 교체(사용자 수정분 보존).
UPDATE rag_model_registry m
SET note = v.new_note, updated_at = now()
FROM (VALUES
    ('vlm', 'qwen2-vl-7b', '기본 — 현행 운영 모델',
     E'기본 — 현행 운영 모델\nQwen 2세대 비전-언어 모델(7B, Apache-2.0). 문서 이미지 OCR·표/차트 해석이 안정적이고 한국어 문서 인식 품질이 검증됨. vLLM 서빙 기준 VRAM 약 20GB(권장 24GB+).'),
    ('embedding', 'multilingual-e5-large', '한국어 포함 다국어 — HWP/PPT 지식베이스 사용',
     E'한국어 포함 다국어 — HWP/PPT 지식베이스 사용\nintfloat 다국어 임베딩(560M, dim 1024, MIT). 약 100개 언어 학습으로 한국어 검색 무난 — 현행 운영 기본 모델.'),
    ('embedding', 'mxbai-embed-large-v1', '영문 — DOC 지식베이스 사용',
     E'영문 — DOC 지식베이스 사용\nmixedbread.ai 영문 임베딩(335M, dim 1024, Apache-2.0). 영문 MTEB 상위권.'),
    ('reranker', 'bge-reranker-v2-m3', '다국어 cross-encoder',
     E'다국어 cross-encoder\nBAAI bge-m3 기반 리랭커(568M, Apache-2.0). 한국어 포함 다국어 재순위의 표준적 선택 — 현행 운영 모델.'),
    ('detection', 'paddleocr-det-rec', 'det/rec 모델 — Paddle 저장소 배포, 수동 반입(볼륨에 직접 전개)',
     E'det/rec 모델 — Paddle 저장소 배포, 수동 반입(볼륨에 직접 전개)\nPaddleOCR 텍스트 검출/인식 모델 — bbox 자동 검출 서버가 사용. pack_model 미지원이므로 볼륨에 직접 전개한다.')
) AS v(kind, name, old_note, new_note)
WHERE m.kind = v.kind AND m.name = v.name AND m.note = v.old_note;

-- ---------------------------------------------------------------------------
-- RAG: PII 규칙 (개인정보 정규식 마스킹 — 인제스천 post_parse 의 pii_regex transform 이 사용)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS rag_pii_rules (
    id SERIAL PRIMARY KEY,
    rule_id VARCHAR(36) NOT NULL UNIQUE,
    name VARCHAR(200) NOT NULL,
    category VARCHAR(40) NOT NULL DEFAULT 'custom',  -- rrn | email | phone | card | custom ...
    pattern TEXT NOT NULL,                           -- 파이썬 re 정규식
    flags VARCHAR(20) NOT NULL DEFAULT '',           -- i/m/s 조합
    mask VARCHAR(200) NOT NULL DEFAULT '[REDACTED]', -- 치환 문자열
    enabled BOOLEAN NOT NULL DEFAULT true,
    description TEXT,
    created_by VARCHAR(200),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_rag_pii_rules_enabled ON rag_pii_rules USING btree (enabled);

-- 사용자 정의 PII 함수(샌드박스 실행) — pii_function transform 이 enabled 함수를 적용
CREATE TABLE IF NOT EXISTS rag_pii_functions (
    id SERIAL PRIMARY KEY,
    function_id VARCHAR(36) NOT NULL UNIQUE,
    name VARCHAR(200) NOT NULL,
    code TEXT NOT NULL,                              -- redact(text)->str 정의 코드
    timeout_ms INT NOT NULL DEFAULT 2000,
    enabled BOOLEAN NOT NULL DEFAULT true,
    description TEXT,
    created_by VARCHAR(200),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_rag_pii_functions_enabled ON rag_pii_functions USING btree (enabled);

-- 기본 PII 규칙 시드(한국) — 이름 기준 멱등(이미 있으면 건너뜀). 정밀 규칙은 enabled,
-- 오탐 큰 규칙(유선전화·계좌·여권·IP)은 기본 off 로 둔다. 정규식은 파이썬 re 기준.
INSERT INTO rag_pii_rules (rule_id, name, category, pattern, flags, mask, enabled, description, created_by)
SELECT v.rule_id, v.name, v.category, v.pattern, v.flags, v.mask, v.enabled, v.description, 'system'
FROM (VALUES
    ('seed-pii-rrn',      '주민등록번호',     'rrn',      '\b\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])-[1-4]\d{6}\b', '',  '[RRN]',      true,  'YYMMDD-Sxxxxxx (성별 1~4)'),
    ('seed-pii-frn',      '외국인등록번호',   'frn',      '\b\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])-[5-8]\d{6}\b', '',  '[FRN]',      true,  '외국인등록번호 (성별 5~8)'),
    ('seed-pii-phone',    '휴대전화번호',     'phone',    '\b01[0-9]-?\d{3,4}-?\d{4}\b',                                  '',  '[PHONE]',    true,  '010-1234-5678 등'),
    ('seed-pii-email',    '이메일',           'email',    '\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b',         'i', '[EMAIL]',    true,  ''),
    ('seed-pii-card',     '신용카드번호',     'card',     '\b(?:\d{4}[\s-]?){3}\d{4}\b',                                  '',  '[CARD]',     true,  '4그룹 16자리'),
    ('seed-pii-bizno',    '사업자등록번호',   'bizno',    '\b\d{3}-\d{2}-\d{5}\b',                                        '',  '[BIZNO]',    true,  '123-45-67890'),
    ('seed-pii-telephone','유선전화번호',     'phone',    '\b0(?:2|[3-6][1-5])-?\d{3,4}-?\d{4}\b',                        '',  '[PHONE]',    false, '지역번호 유선전화(오탐 가능 → 기본 off)'),
    ('seed-pii-account',  '계좌번호(일반)',   'account',  '\b\d{2,6}-\d{2,6}-\d{2,6}\b',                                  '',  '[ACCOUNT]',  false, '형식 다양·오탐 큼 → 기본 off'),
    ('seed-pii-passport', '여권번호',         'passport', '\b[MSRODGP][0-9]{8}\b',                                        '',  '[PASSPORT]', false, '오탐 가능 → 기본 off'),
    ('seed-pii-ip',       'IP 주소',          'ip',       '\b(?:\d{1,3}\.){3}\d{1,3}\b',                                  '',  '[IP]',       false, '기본 off')
) AS v(rule_id, name, category, pattern, flags, mask, enabled, description)
WHERE NOT EXISTS (SELECT 1 FROM rag_pii_rules r WHERE r.name = v.name);

-- 사용자 정의 PII 함수 시드(부분 마스킹 예시) — 이름 기준 멱등. redact(text) 계약, re·luhn_ok·rrn_ok 사용.
INSERT INTO rag_pii_functions (function_id, name, code, timeout_ms, enabled, description, created_by)
SELECT v.function_id, v.name, v.code, v.timeout_ms, v.enabled, v.description, 'system'
FROM (VALUES
    ('seed-fn-email', '이메일 부분 마스킹',
'def redact(text):
    def m(x):
        s = x.group(0)
        i = s.index("@")
        return (s[:i][:1] or "") + "***" + s[i:]
    return re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", m, text)
', 2000, true, '아이디 첫 글자만 남기고 마스킹(예: h***@example.com)'),
    ('seed-fn-card', '신용카드 끝 4자리 유지',
'def redact(text):
    def m(x):
        d = "".join(c for c in x.group(0) if c.isdigit())
        if not luhn_ok(d):
            return x.group(0)
        return "****-****-****-" + d[-4:]
    return re.sub(r"(?<!\d)\d(?:[ -]?\d){12,18}(?!\d)", m, text)
', 2000, true, 'Luhn 검증 후 끝 4자리만 노출(****-****-****-1234)'),
    ('seed-fn-rrn', '주민번호 뒷자리 마스킹',
'def redact(text):
    def m(x):
        d = "".join(c for c in x.group(0) if c.isdigit())
        if not rrn_ok(d):
            return x.group(0)
        return d[:6] + "-" + d[6] + "******"
    return re.sub(r"(?<!\d)\d{6}-?\d{7}(?!\d)", m, text)
', 2000, true, '생년월일·성별만 남기고 뒷자리 마스킹(880101-1******)')
) AS v(function_id, name, code, timeout_ms, enabled, description)
WHERE NOT EXISTS (SELECT 1 FROM rag_pii_functions f WHERE f.name = v.name);

-- ---------------------------------------------------------------------------
-- RAG: Feedback (답변 👍/👎 수집 → 평가 골든셋 보강 루프)
--   사용자 피드백을 모아 평가 데이터셋 항목으로 승격(promote)한다.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS rag_feedback (
    id SERIAL PRIMARY KEY,
    feedback_id VARCHAR(36) NOT NULL UNIQUE,
    trace_id VARCHAR(36),                  -- rag_query_traces.trace_id 연결(선택)
    collection_id INT,
    query TEXT NOT NULL,
    answer TEXT,
    rating VARCHAR(4) NOT NULL,            -- up | down
    comment TEXT,
    corrected_answer TEXT,                 -- 사용자가 제시한 더 나은 답변(선택)
    expected_sources TEXT,                 -- 줄바꿈 구분 기대 출처(선택)
    status VARCHAR(12) NOT NULL DEFAULT 'new',  -- new | promoted | dismissed
    promoted_item_id INT,                  -- 승격된 rag_eval_items.id
    created_by VARCHAR(200),
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_rag_feedback_created ON rag_feedback USING btree (created_at);
CREATE INDEX IF NOT EXISTS idx_rag_feedback_status ON rag_feedback USING btree (status);
CREATE INDEX IF NOT EXISTS idx_rag_feedback_rating ON rag_feedback USING btree (rating);

-- ---------------------------------------------------------------------------
-- Permission Matrix (역할별 메뉴/기능 접근 제어 — open-by-default)
--   행이 없는 perm_key 는 전 역할 허용. 제한 항목만 저장한다.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS argus_permissions (
    id SERIAL PRIMARY KEY,
    kind VARCHAR(10) NOT NULL,        -- MENU | FEATURE
    perm_key VARCHAR(100) NOT NULL,
    role_id VARCHAR(50) NOT NULL,     -- argus-superuser | argus-user | __none__
    created_at TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT uq_permission UNIQUE (kind, perm_key, role_id)
);

-- ---------------------------------------------------------------------------
-- App Settings (config 기본값에 대한 운영자 override — key-value)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS argus_settings (
    key VARCHAR(100) PRIMARY KEY,
    value TEXT,
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- API Keys (외부 시스템 연동용 서비스 계정 — search/query/chat 프로그래밍 호출)
--   평문 키는 발급 시 1회만 노출하고, DB 에는 SHA-256 해시만 저장한다.
--   role_id 로 권한을 부여(사용자와 동일한 역할 식별자 — argus-user 등).
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS argus_api_keys (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description VARCHAR(255),
    key_prefix VARCHAR(20) NOT NULL,        -- 표시용 앞부분 (예: argus_sk_AbCd…)
    key_hash VARCHAR(64) NOT NULL UNIQUE,   -- sha256(평문 키)
    role_id VARCHAR(50) NOT NULL,           -- argus-admin | argus-superuser | argus-user
    enabled BOOLEAN NOT NULL DEFAULT true,
    expires_at TIMESTAMPTZ,                 -- NULL 이면 무기한
    last_used_at TIMESTAMPTZ,
    created_by VARCHAR(100),                -- 발급한 관리자 username
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_argus_api_keys_key_hash ON argus_api_keys USING btree (key_hash);

-- ---------------------------------------------------------------------------
-- 워커 레지스트리 (인제스천 워커 모니터링)
--   워커 프로세스(또는 API in-process 워커)가 기동 시 등록하고 주기적으로 last_heartbeat_at
--   을 갱신한다. API 가 이 표로 살아있는 워커·현재 잡·처리량을 보여준다(잡 모니터링 '워커' 탭).
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS argus_workers (
    id VARCHAR(64) PRIMARY KEY,             -- 프로세스당 uuid
    hostname VARCHAR(255),
    pid INTEGER,
    mode VARCHAR(20),                       -- in_process(API 동거) | standalone(분리)
    runtime VARCHAR(20),                    -- 배포 방식: docker | systemd | k8s | NULL(직접 실행)
    version VARCHAR(40),
    status VARCHAR(20) NOT NULL DEFAULT 'idle',   -- starting | idle | busy | stopped
    current_job_id VARCHAR(64),             -- 처리 중 잡의 job_id, idle 이면 NULL
    processed_total INTEGER NOT NULL DEFAULT 0,
    metrics JSONB,                          -- 프로세스/호스트 CPU·RAM 등 리소스 메트릭(하트비트마다 갱신)
    started_at TIMESTAMPTZ DEFAULT now(),
    last_heartbeat_at TIMESTAMPTZ DEFAULT now()
);

-- (마이그레이션) 기존 환경 컬럼 보강 — 멱등.
ALTER TABLE argus_workers ADD COLUMN IF NOT EXISTS runtime VARCHAR(20);

CREATE INDEX IF NOT EXISTS idx_argus_workers_heartbeat ON argus_workers USING btree (last_heartbeat_at);

-- ---------------------------------------------------------------------------
-- 외부 확장 서버 레플리카 레지스트리 (임베딩·리랭커·검출 모니터링)
--   LB 뒤 레플리카는 /stats 풀 프로브로 1대만 보이므로, 각 레플리카가 자신을 백엔드로
--   하트비트(push)해 등록한다. API 가 이 표로 풀 전체의 생존·리소스를 보여준다.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS argus_ext_servers (
    id VARCHAR(64) PRIMARY KEY,             -- 인스턴스 uuid
    kind VARCHAR(20) NOT NULL,              -- embedding | reranker | detection
    hostname VARCHAR(255),
    url VARCHAR(500),                       -- 레플리카 직접 주소(표시용)
    version VARCHAR(40),
    stats JSONB,                            -- /stats 스냅샷(시스템·GPU·요청·모델)
    last_heartbeat_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_argus_ext_servers_heartbeat ON argus_ext_servers USING btree (last_heartbeat_at);

-- ---------------------------------------------------------------------------
-- 관리 대상 호스트(에이전트) 레지스트리 (Argus RAG Studio Agent)
--   관리 대상 서버에 root 로 설치된 Agent(:4501)가 자신을 백엔드로 하트비트(push)한다.
--   신규 호스트는 UNREGISTERED 로 자동 등록되고, 운영자가 servermgr 로 REGISTERED 하면
--   관리 대상이 된다. 하트비트가 끊기면(타임아웃) DISCONNECTED 로 표시된다.
--   백엔드(servermgr)는 이 표의 ip_address 로 Agent 에 inspect/top/processes/terminal 을 프록시한다.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS argus_agents (
    hostname VARCHAR(255) PRIMARY KEY,      -- 에이전트가 보고한 호스트명(고유 식별자)
    ip_address VARCHAR(45) NOT NULL,        -- IPv4/IPv6 주소
    version VARCHAR(50),                    -- 에이전트 소프트웨어 버전
    kernel_version VARCHAR(255),
    os_version VARCHAR(255),
    arch VARCHAR(16),                       -- CPU 아키텍처(amd64|arm64) — 이미지 변형 선택용
    cpu_count INTEGER,                      -- 논리 CPU 수
    core_count INTEGER,                     -- 물리 코어 수
    total_memory BIGINT,                    -- 총 메모리(bytes)
    cpu_usage DOUBLE PRECISION,             -- CPU 사용률(%)
    memory_usage DOUBLE PRECISION,          -- 메모리 사용률(%)
    disk_swap_percent DOUBLE PRECISION,     -- 스왑 사용률(%)
    gpu_count INTEGER,                      -- NVIDIA GPU 수(없으면 NULL)
    gpu_usage DOUBLE PRECISION,             -- 평균 GPU 이용률(%)
    gpu_memory_usage DOUBLE PRECISION,      -- 평균 GPU 메모리 점유율(%)
    gpu_memory_total BIGINT,                -- 총 VRAM(MiB, 디스크리트 합계; 통합메모리는 NULL)
    gpu_name VARCHAR(255),                  -- 첫 GPU 모델명
    status VARCHAR(20) NOT NULL DEFAULT 'UNREGISTERED',  -- UNREGISTERED | REGISTERED | DISCONNECTED
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_argus_agents_status ON argus_agents USING btree (status);

-- 에이전트별 마지막 하트비트 타임스탬프(끊김 감지 + last_heartbeat_seconds 계산용).
CREATE TABLE IF NOT EXISTS argus_agents_heartbeat (
    hostname VARCHAR(255) PRIMARY KEY,
    last_heartbeat_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_argus_agents_heartbeat_at ON argus_agents_heartbeat USING btree (last_heartbeat_at);

-- ---------------------------------------------------------------------------
-- RAG: Document (수집된 원본 단위)
--   인제스천 파이프라인(M2)의 입력. 삭제 시 컬렉션 CASCADE.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS rag_documents (
    id SERIAL PRIMARY KEY,
    document_id VARCHAR(36) NOT NULL UNIQUE,
    collection_id INT NOT NULL REFERENCES rag_collections(id) ON DELETE CASCADE,
    name VARCHAR(500) NOT NULL,
    source_type VARCHAR(50) NOT NULL DEFAULT 'upload',
    source_uri VARCHAR(2000),
    content_hash VARCHAR(64),
    size_bytes BIGINT NOT NULL DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'registered',
    chunk_count INT NOT NULL DEFAULT 0,
    metadata_json TEXT,
    indexed_at TIMESTAMPTZ,
    created_by VARCHAR(200),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_rag_documents_collection ON rag_documents USING btree (collection_id);
CREATE INDEX IF NOT EXISTS idx_rag_documents_status ON rag_documents USING btree (status);
CREATE INDEX IF NOT EXISTS idx_rag_documents_content_hash ON rag_documents USING btree (content_hash);

-- ---------------------------------------------------------------------------
-- RAG: Chunk (M2 인제스천에서 채워짐 — M1 에서는 스키마만 준비)
--   embedding 차원은 컬렉션의 embedding_dim 과 일치해야 한다. pgvector 는 단일 컬럼에
--   고정 차원을 요구하므로, 다차원 모델 혼용이 필요해지면 컬렉션별 파티션/테이블로 분리한다.
--   기본 1024(bge-m3) 기준. HNSW 인덱스로 ANN 검색, tsv 로 BM25/렉시컬 검색을 병행한다.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS rag_chunks (
    id BIGSERIAL PRIMARY KEY,
    chunk_id VARCHAR(36) NOT NULL UNIQUE,
    document_id INT NOT NULL REFERENCES rag_documents(id) ON DELETE CASCADE,
    collection_id INT NOT NULL REFERENCES rag_collections(id) ON DELETE CASCADE,
    seq INT NOT NULL DEFAULT 0,
    text TEXT NOT NULL,
    embedding vector(1024),
    tsv tsvector,
    parent_chunk_id BIGINT REFERENCES rag_chunks(id) ON DELETE SET NULL,
    section_path VARCHAR(1000),
    metadata_json TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_rag_chunks_document ON rag_chunks USING btree (document_id);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_collection ON rag_chunks USING btree (collection_id);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_tsv ON rag_chunks USING gin (tsv);
-- 벡터 ANN 인덱스(코사인). 데이터가 쌓인 뒤 생성/튜닝하는 것이 일반적이라 주석으로 남긴다.
-- CREATE INDEX idx_rag_chunks_embedding ON rag_chunks USING hnsw (embedding vector_cosine_ops);

-- ---------------------------------------------------------------------------
-- RAG: Ingestion Job (M2 — 수집/처리 분리. 워커가 잡을 집어 처리한다)
--   라이프사이클: queued → running → succeeded / failed
--   stage: parse → chunk → embed → index (현재 단계, 진행률 표시용)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS rag_ingestion_jobs (
    id SERIAL PRIMARY KEY,
    job_id VARCHAR(36) NOT NULL UNIQUE,
    document_id INT NOT NULL REFERENCES rag_documents(id) ON DELETE CASCADE,
    collection_id INT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'queued',
    stage VARCHAR(20),
    progress INT NOT NULL DEFAULT 0,
    chunk_count INT NOT NULL DEFAULT 0,
    error TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_rag_ingestion_jobs_status ON rag_ingestion_jobs USING btree (status);
CREATE INDEX IF NOT EXISTS idx_rag_ingestion_jobs_collection ON rag_ingestion_jobs USING btree (collection_id);

-- ---------------------------------------------------------------------------
-- Annotation: 이미지 OCR 어노테이션 (AI-Hub 손글씨 라벨 포맷 호환)
--   이미지 1장(annotation_images) + 글자/단어 단위 bbox(annotation_boxes).
--   내부 좌표는 (x1,y1,x2,y2) 축정렬 사각형으로 보관하고, 내보내기 시 AI-Hub
--   규격(x=[x1,x1,x2,x2], y=[y1,y2,y1,y2])으로 직렬화한다.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS annotation_images (
    id SERIAL PRIMARY KEY,
    image_id VARCHAR(36) NOT NULL UNIQUE,
    collection_id INT REFERENCES rag_collections(id) ON DELETE SET NULL,
    filename VARCHAR(500) NOT NULL,
    -- 가상 폴더 경로(루트='' / 중첩='a/b'). 탐색기 폴더 트리·폴더별 목록 기준.
    folder VARCHAR(1000) NOT NULL DEFAULT '',
    source_uri VARCHAR(2000),
    -- 썸네일 객체 위치(s3://...). 업로드/편집기 진입 시 생성. NULL 이면 원본을 표시.
    thumb_uri VARCHAR(2000),
    content_type VARCHAR(100),
    content_hash VARCHAR(64),
    width INT NOT NULL DEFAULT 0,
    height INT NOT NULL DEFAULT 0,
    size_bytes BIGINT NOT NULL DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'draft',
    meta_json JSONB,
    created_by VARCHAR(200),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_annotation_images_collection ON annotation_images USING btree (collection_id);
CREATE INDEX IF NOT EXISTS idx_annotation_images_status ON annotation_images USING btree (status);
CREATE INDEX IF NOT EXISTS idx_annotation_images_content_hash ON annotation_images USING btree (content_hash);
CREATE INDEX IF NOT EXISTS idx_annotation_images_folder ON annotation_images USING btree (folder);

CREATE TABLE IF NOT EXISTS annotation_boxes (
    id BIGSERIAL PRIMARY KEY,
    image_id INT NOT NULL REFERENCES annotation_images(id) ON DELETE CASCADE,
    seq INT NOT NULL,
    data TEXT NOT NULL DEFAULT '',
    x1 INT NOT NULL,
    y1 INT NOT NULL,
    x2 INT NOT NULL,
    y2 INT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT uq_annotation_boxes_image_seq UNIQUE (image_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_annotation_boxes_image ON annotation_boxes USING btree (image_id);

-- ---------------------------------------------------------------------------
-- Image Recognition: 이미지 인식(분류) 실행 이력
--   업로드 1건(파일 1개) = 실행 1건. 추출 이미지(원본·썸네일)와 분석 결과는
--   분류 버킷(classification-images)의 runs/{run_id}/ 아래에 저장하고,
--   여기에는 메타(파일명·상태·개수·시각·버킷 위치)만 둔다. batch_id 로 동시 업로드 묶음을 식별.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS rag_image_recognition_runs (
    id SERIAL PRIMARY KEY,
    run_id VARCHAR(36) NOT NULL UNIQUE,
    batch_id VARCHAR(36),
    filename VARCHAR(500) NOT NULL,
    source_kind VARCHAR(50),
    status VARCHAR(20) NOT NULL DEFAULT 'running',
    extracted_count INT NOT NULL DEFAULT 0,
    analyzed_count INT NOT NULL DEFAULT 0,
    counts_by_type JSONB,
    size_bytes BIGINT NOT NULL DEFAULT 0,   -- 실행 폴더(prefix) 전체 저장 크기(byte)
    source_url VARCHAR(2000),               -- URL 가져오기인 경우 원본 페이지 URL(파일명은 HTML 타이틀)
    bucket VARCHAR(255),
    prefix VARCHAR(1000),
    error TEXT,
    created_by VARCHAR(200),
    created_at TIMESTAMPTZ DEFAULT now(),
    finished_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_rag_image_recognition_runs_created ON rag_image_recognition_runs USING btree (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_rag_image_recognition_runs_batch ON rag_image_recognition_runs USING btree (batch_id);
CREATE INDEX IF NOT EXISTS idx_rag_image_recognition_runs_status ON rag_image_recognition_runs USING btree (status);

-- ---------------------------------------------------------------------------
-- Fine-tuning: Training Dataset (학습 데이터셋 — 외부 트레이너 입력 소스)
--   UI 에서 (질의·정답·오답) 트리플을 모아 관리하고, train/valid JSONL 로 내보낸다.
--   test(홀드아웃)는 Argus 가 보관해 객관적 평가에 쓴다(extensions/retrieval-fine-tuning 계약).
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS ft_datasets (
    id SERIAL PRIMARY KEY,
    dataset_id VARCHAR(36) NOT NULL UNIQUE,
    name VARCHAR(200) NOT NULL UNIQUE,
    description TEXT,
    -- 코퍼스/소스 컬렉션(빌더·하드네거티브 마이닝 기준). 삭제 시 NULL.
    base_collection_id INT REFERENCES rag_collections(id) ON DELETE SET NULL,
    base_model VARCHAR(200),                                  -- 매니페스트 기본 베이스 모델
    task VARCHAR(20) NOT NULL DEFAULT 'embedding',            -- embedding | reranker
    prompt_format VARCHAR(20) NOT NULL DEFAULT 'e5',          -- e5 | none
    split_strategy VARCHAR(20) NOT NULL DEFAULT 'by_document',
    status VARCHAR(20) NOT NULL DEFAULT 'draft',              -- draft | ready | exported
    created_by VARCHAR(200),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ft_datasets_status ON ft_datasets USING btree (status);

CREATE TABLE IF NOT EXISTS ft_examples (
    id BIGSERIAL PRIMARY KEY,
    example_id VARCHAR(36) NOT NULL UNIQUE,
    dataset_id INT NOT NULL REFERENCES ft_datasets(id) ON DELETE CASCADE,
    split VARCHAR(10) NOT NULL DEFAULT 'train',              -- train | valid | test
    query TEXT NOT NULL,
    positive TEXT NOT NULL,
    negatives TEXT,                                          -- JSON: 문자열 배열(하드네거티브)
    positive_chunk_id BIGINT,                                -- 출처 청크(provenance, 선택)
    source VARCHAR(20) NOT NULL DEFAULT 'manual',            -- manual | goldenset | feedback | mined
    meta_json TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ft_examples_dataset ON ft_examples USING btree (dataset_id);
CREATE INDEX IF NOT EXISTS idx_ft_examples_split ON ft_examples USING btree (split);

-- ---------------------------------------------------------------------------
-- Fine-tuning: Training Job (학습 작업 — 외부 트레이너 실행 요청·상태 추적)
--   Argus 는 잡을 기록·추적하고, 실제 학습은 외부 프로그램이 수행하며 상태를 콜백으로
--   갱신한다(느슨한 결합). 라이프사이클: queued → running → succeeded/failed/canceled.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS ft_jobs (
    id SERIAL PRIMARY KEY,
    job_id VARCHAR(36) NOT NULL UNIQUE,
    dataset_id INT NOT NULL REFERENCES ft_datasets(id) ON DELETE CASCADE,
    task VARCHAR(20) NOT NULL DEFAULT 'embedding',           -- embedding | reranker (스냅샷)
    base_model VARCHAR(200),
    config_json TEXT,                                        -- 하이퍼파라미터 JSON(epochs/batch/lr 등)
    status VARCHAR(20) NOT NULL DEFAULT 'queued',            -- queued|running|succeeded|failed|canceled
    stage VARCHAR(20),                                       -- export | training | importing
    progress INT NOT NULL DEFAULT 0,
    metrics_json TEXT,                                       -- valid 지표 JSON
    artifact_uri VARCHAR(2000),                             -- 학습 결과 모델 위치
    error TEXT,
    callback_token VARCHAR(64),                             -- 잡 전용 콜백 토큰(외부 트레이너 M2M 인증)
    created_by VARCHAR(200),
    created_at TIMESTAMPTZ DEFAULT now(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_ft_jobs_dataset ON ft_jobs USING btree (dataset_id);
CREATE INDEX IF NOT EXISTS idx_ft_jobs_status ON ft_jobs USING btree (status);

-- ---------------------------------------------------------------------------
-- Fine-tuning: Model Registry (학습 결과 모델 — 서빙·평가 연결 + 선택적 발행)
--   외부 트레이너 산출물(임베딩/리랭커)을 등록해 컬렉션에 연결하고, 홀드아웃 골든셋으로
--   base 와 비교 평가한다. published_uri 는 OCI/MLflow 등 외부 배포 대상(선택).
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS ft_models (
    id SERIAL PRIMARY KEY,
    model_id VARCHAR(36) NOT NULL UNIQUE,
    name VARCHAR(200) NOT NULL UNIQUE,
    task VARCHAR(20) NOT NULL DEFAULT 'embedding',           -- embedding | reranker
    base_model VARCHAR(200),
    embedding_dim INT,                                       -- 임베딩만(리랭커는 NULL)
    format VARCHAR(40),                                      -- sentence-transformers | ...-cross-encoder
    prompt_format VARCHAR(20) NOT NULL DEFAULT 'e5',
    -- 출처(provenance) — 어떤 데이터셋/잡에서 나왔는지. 삭제 시 NULL.
    dataset_id INT REFERENCES ft_datasets(id) ON DELETE SET NULL,
    job_id INT REFERENCES ft_jobs(id) ON DELETE SET NULL,
    artifact_uri VARCHAR(2000),                             -- 모델 아티팩트 위치
    metrics_json TEXT,                                      -- valid 지표 JSON
    serving_url VARCHAR(500),                               -- 서빙 서버 URL(openai_compatible/cross_encoder)
    status VARCHAR(20) NOT NULL DEFAULT 'registered',       -- registered | serving | archived
    published_uri VARCHAR(2000),                            -- OCI/MLflow 등 외부 발행 위치(선택)
    created_by VARCHAR(200),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ft_models_status ON ft_models USING btree (status);
CREATE INDEX IF NOT EXISTS idx_ft_models_task ON ft_models USING btree (task);

-- ---------------------------------------------------------------------------
-- Fine-tuning: Glossary (도메인 용어 사전 — 합성 질의·하드네거티브 마이닝·쿼리 확장에 활용)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS ft_glossary_terms (
    id SERIAL PRIMARY KEY,
    term_id VARCHAR(36) NOT NULL UNIQUE,
    term VARCHAR(200) NOT NULL,
    definition TEXT,
    synonyms TEXT,                                          -- JSON: 문자열 배열(동의어·약어·구어체)
    domain VARCHAR(100),                                    -- 예: 세무, 법률
    created_by VARCHAR(200),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ft_glossary_domain ON ft_glossary_terms USING btree (domain);
CREATE INDEX IF NOT EXISTS idx_ft_glossary_term ON ft_glossary_terms USING btree (term);

-- ---------------------------------------------------------------------------
-- Comments
-- ---------------------------------------------------------------------------

COMMENT ON TABLE argus_roles IS '권한 역할 정의';
COMMENT ON TABLE argus_users IS '로컬 인증 사용자 계정 (Keycloak 모드는 JIT 동기화 사본)';
COMMENT ON TABLE argus_user_preferences IS '사용자별 UI 환경 설정 — 토큰 sub 키로 로컬·Keycloak 공용';
COMMENT ON TABLE argus_api_keys IS '외부 시스템 연동용 API 키(서비스 계정) — 해시만 저장, role_id 로 권한 부여';
COMMENT ON TABLE argus_workers IS '인제스천 워커 레지스트리 — 하트비트 기반 생존/현재 잡/처리량 모니터링';
COMMENT ON TABLE argus_agents IS '관리 대상 호스트(Argus RAG Studio Agent) 레지스트리 — 하트비트 기반 인벤토리 + UNREGISTERED/REGISTERED/DISCONNECTED 상태';
COMMENT ON TABLE argus_agents_heartbeat IS '에이전트별 마지막 하트비트 타임스탬프 — 끊김 감지 및 경과시간 계산';
COMMENT ON TABLE rag_collections IS 'RAG 지식베이스 — 임베딩 벡터 공간 경계';
COMMENT ON TABLE rag_documents IS 'RAG 수집 원본 문서 (인제스천 입력)';
COMMENT ON TABLE rag_chunks IS 'RAG 청크 — 임베딩 벡터 + 렉시컬 인덱스 (M2 인제스천에서 채움)';
COMMENT ON TABLE rag_ingestion_jobs IS 'RAG 인제스천 잡 — 파싱→청킹→임베딩→인덱싱 처리 추적';

-- ---------------------------------------------------------------------------
-- K8s 클러스터 등록 (배포 대상 — DeployTarget.cluster_id 참조)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS argus_k8s_clusters (
    id SERIAL PRIMARY KEY,
    cluster_id VARCHAR(64) NOT NULL UNIQUE,
    name VARCHAR(200) NOT NULL,
    api_server VARCHAR(500) NOT NULL,
    token TEXT,
    ca_cert TEXT,
    verify_ssl BOOLEAN NOT NULL DEFAULT true,
    default_namespace VARCHAR(128) NOT NULL DEFAULT 'default',
    default_arch VARCHAR(16) NOT NULL DEFAULT 'amd64',
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);
