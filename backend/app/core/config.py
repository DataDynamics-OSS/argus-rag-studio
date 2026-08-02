# SPDX-License-Identifier: Apache-2.0
"""애플리케이션 설정.

설정은 설정 디렉터리의 두 파일에서 로드된다:
1. config.properties - Java 스타일 key=value 변수 정의
2. config.yml - Spring Boot 스타일 ${variable:default} 을 사용하는 메인 YAML 설정
"""

import os
from pathlib import Path

from app import __version__
from app.core.config_loader import load_config

_CONFIG_DIR = Path(
    os.environ.get("ARGUS_RAG_STUDIO_SERVER_CONFIG_DIR", "/etc/argus-rag-studio-server")
)
_yaml_path: Path = _CONFIG_DIR / "config.yml"
_properties_path: Path = _CONFIG_DIR / "config.properties"
_raw: dict = load_config(config_dir=_CONFIG_DIR)


def _get(section: str, key: str, default=None):
    return _raw.get(section, {}).get(key, default)


def _get_nested(section: str, subsection: str, key: str, default=None):
    return _raw.get(section, {}).get(subsection, {}).get(key, default)


def _to_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes")
    return bool(value)


class Settings:
    """config.yml + config.properties 에서 로드한 전역 애플리케이션 설정."""

    def __init__(self) -> None:
        self.app_name: str = _get("app", "name", "argus-rag-studio-server")
        # 버전은 코드(app.__version__)를 단일 소스로 사용한다. config.yml 로 재정의하지 않는다.
        self.app_version: str = __version__
        self.debug: bool = _to_bool(_get("app", "debug", False))

        self.host: str = _get("server", "host", "0.0.0.0")
        self.port: int = int(_get("server", "port", 4700))

        self.log_level: str = _get("logging", "level", "INFO")
        # 로그 경로/파일명은 env 로 오버라이드 가능 — 한 호스트에 워커를 여러 개 띄울 때
        # 슬롯별로 다른 파일(예: argus-rag-worker-1.log)을 주입해 로그 충돌을 막는다.
        self.log_dir: Path = Path(os.environ.get("ARGUS_LOG_DIR") or _get("logging", "dir", "logs"))
        self.log_filename: str = os.environ.get("ARGUS_LOG_FILENAME") or _get(
            "logging", "filename", "argus-rag-studio-server.log"
        )
        self.log_rolling_type: str = _get_nested("logging", "rolling", "type", "daily")
        self.log_rolling_backup_count: int = int(
            _get_nested("logging", "rolling", "backup_count", 30)
        )

        self.data_dir: Path = Path(_get("data", "dir", "/var/lib/argus-rag-studio-server"))

        self.config_dir: Path = _CONFIG_DIR
        self.config_yaml_path: Path = _yaml_path
        self.config_properties_path: Path = _properties_path

        self.cors_origins: list[str] = _get("cors", "origins", ["*"])

        # 기반 환경(Platform Profile) — standard(기본) | databricks
        #   임베딩/LLM/벡터스토어/스토리지의 기본값과 동작을 플랫폼에 맞춰 전환한다.
        #   PlatformProfile 어댑터(app.platform)가 이 값을 읽어 정책을 공급한다.
        self.platform_base: str = _get("platform", "base", "standard")
        # Databricks workspace 접속(기반 환경=databricks 일 때 사용) — PAT 토큰 인증.
        #   host 예: https://<workspace>.cloud.databricks.com  (serving-endpoints 베이스는 임베딩/LLM server_url 로 지정)
        self.databricks_host: str = (
            os.environ.get("ARGUS_DATABRICKS_HOST") or _get("databricks", "host", "")
        )
        self.databricks_token: str = (
            os.environ.get("ARGUS_DATABRICKS_TOKEN") or _get("databricks", "token", "")
        )

        # 데이터베이스
        self.db_type: str = _get("database", "type", "postgresql")
        self.db_host: str = _get("database", "host", "localhost")
        self.db_port: int = int(_get("database", "port", 5432))
        self.db_name: str = _get("database", "name", "argus_rag_studio")
        self.db_username: str = _get("database", "username", "argus")
        self.db_password: str = _get("database", "password", "argus")
        self.db_pool_size: int = int(_get_nested("database", "pool", "size", 5))
        self.db_pool_max_overflow: int = int(_get_nested("database", "pool", "max_overflow", 10))
        self.db_pool_recycle: int = int(_get_nested("database", "pool", "recycle", 3600))
        self.db_echo: bool = _to_bool(_get("database", "echo", False))

        # 인증 — Keycloak OIDC / 로컬 JWT
        self.auth_type: str = _get("auth", "type", "local")
        self.auth_keycloak_server_url: str = _get_nested(
            "auth", "keycloak", "server_url", "http://localhost:8180"
        )
        self.auth_keycloak_realm: str = _get_nested("auth", "keycloak", "realm", "argus")
        self.auth_keycloak_client_id: str = _get_nested(
            "auth", "keycloak", "client_id", "argus-client"
        )
        self.auth_keycloak_client_secret: str = _get_nested(
            "auth", "keycloak", "client_secret", "argus-client-secret"
        )
        self.auth_keycloak_admin_role: str = _get_nested(
            "auth", "keycloak", "admin_role", "argus-admin"
        )
        self.auth_keycloak_superuser_role: str = _get_nested(
            "auth", "keycloak", "superuser_role", "argus-superuser"
        )
        self.auth_keycloak_user_role: str = _get_nested(
            "auth", "keycloak", "user_role", "argus-user"
        )
        # 로컬(내장 JWT) 토큰 만료(분). 기본 480(8시간).
        self.auth_local_jwt_expire_minutes: int = int(
            _get("auth", "local_jwt_expire_minutes", 480)
        )

        # 임베딩 기본값 — 컬렉션 생성 시 기본으로 채울 임베딩 모델/차원/거리 메트릭.
        self.embedding_default_model: str = _get(
            "embedding", "default_model", "bge-m3"
        )
        self.embedding_default_dim: int = int(_get("embedding", "default_dim", 1024))
        self.embedding_default_metric: str = _get("embedding", "default_metric", "cosine")

        # 임베딩 프로바이더(M2) — 로컬/사내 임베딩 서버 호출 설정.
        #   provider:
        #     - "openai_compatible": POST {server_url}/embeddings (TEI / Ollama-proxy / vLLM / OpenAI)
        #     - "hash": 외부 서버 없이 텍스트 해시로 결정적 더미 벡터 생성(개발/오프라인/에어갭 검증용)
        self.embedding_provider: str = _get("embedding", "provider", "openai_compatible")
        # 원격/분리 워커가 라우팅 가능한 임베딩 서버로 접속하도록 env 오버라이드 지원.
        self.embedding_server_url: str = os.environ.get("ARGUS_EMBEDDING_SERVER_URL") or _get(
            "embedding", "server_url", "http://localhost:8080/v1"
        )
        # 기본값 'changeme' — Argus 임베딩 서버 기본 키와 맞춘다(둘 다 미설정 시 바로 동작).
        # 다른 서버/무인증이면 ARGUS_EMBEDDING_API_KEY 또는 설정으로 override.
        self.embedding_api_key: str = (
            os.environ.get("ARGUS_EMBEDDING_API_KEY")
            or _get("embedding", "api_key", "changeme")
        )
        self.embedding_model: str = os.environ.get("ARGUS_EMBEDDING_MODEL") or _get(
            "embedding", "model", "bge-m3"
        )
        # 쿼리 instruction(선택) — Qwen3-Embedding 류 instruction-aware 모델은 쿼리에만 지시문을
        # 붙여야 검색 성능이 나온다(문서는 원문). 빈값이면 기반 환경 프로파일의 기본값을 따른다.
        # Databricks 서빙이 적용하는 규약과 글자 단위로 일치해야 벡터 공간이 맞으므로 명시 지정 가능.
        self.embedding_query_instruction: str = _get("embedding", "query_instruction", "")
        self.embedding_batch_size: int = int(_get("embedding", "batch_size", 32))
        self.embedding_timeout: int = int(_get("embedding", "timeout", 60))
        # 인증 헤더 커스터마이즈 — 기본은 표준 'Authorization: Bearer <key>'.
        # 게이트웨이가 다른 헤더를 요구하면 변경(예: header='X-API-Key', scheme='' → 'X-API-Key: <key>').
        self.embedding_auth_header: str = _get("embedding", "auth_header", "Authorization")
        self.embedding_auth_scheme: str = _get("embedding", "auth_scheme", "Bearer")

        # 인제스천(M2) — 청킹/워커 설정.
        self.ingestion_chunk_size: int = int(_get("ingestion", "chunk_size", 1000))
        self.ingestion_chunk_overlap: int = int(_get("ingestion", "chunk_overlap", 150))
        # 로컬(인프로세스) 워커: 이 app.main 프로세스가 색인 워커 루프를 동거 실행할지 여부.
        # API 는 ARGUS_INGESTION_LOCAL_WORKER_ENABLED=false 로 띄워 로컬 워커를 끄고,
        # 색인은 원격/분리 워커(에이전트 배포)에 맡긴다. (구 이름 ARGUS_INGESTION_WORKER_ENABLED 폴백 지원)
        self.ingestion_local_worker_enabled: bool = _to_bool(
            os.environ.get("ARGUS_INGESTION_LOCAL_WORKER_ENABLED")
            or os.environ.get("ARGUS_INGESTION_WORKER_ENABLED")
            or _get("ingestion", "local_worker_enabled", _get("ingestion", "worker_enabled", True))
        )
        self.ingestion_worker_interval: float = float(
            _get("ingestion", "worker_interval", 2.0)
        )
        # 청킹 품질 파라미터.
        #   max_kss_chars: 이 길이 초과 텍스트는 KSS(pecab) 지연을 피해 규칙 기반 문장분리로 폴백
        #   min_chunk_ratio: 청크 크기 대비 최소 청크 비율(작은 청크 병합 기준)
        #   semantic_percentile: 시맨틱 청킹 경계 임계 백분위
        self.ingestion_max_kss_chars: int = int(_get("ingestion", "max_kss_chars", 5000))
        self.ingestion_min_chunk_ratio: float = float(
            _get("ingestion", "min_chunk_ratio", 0.1)
        )
        self.ingestion_semantic_percentile: int = int(
            _get("ingestion", "semantic_percentile", 90)
        )
        # NiFi 등 외부 파이프라인이 /ingestion/register 를 호출할 때 검증할 서비스 토큰.
        # 환경변수 우선, 없으면 config, 둘 다 없으면 빈 값(개발용 — 인증 비강제).
        self.ingestion_service_token: str = (
            os.environ.get("ARGUS_INGESTION_TOKEN")
            or _get("ingestion", "service_token", "")
        )
        # 확장 서버(임베딩·리랭커·검출) 레플리카 하트비트 수신용 토큰. 빈 값이면 인증 비강제(개발).
        self.ext_heartbeat_token: str = (
            os.environ.get("ARGUS_EXT_HEARTBEAT_TOKEN")
            or _get("monitoring", "heartbeat_token", "")
        )
        # HWP/HWPX 페이지 렌더 서비스(헤드리스 브라우저 @rhwp/core) URL. 빈 값이면 근거 페이지 기능 비활성.
        self.hwp_render_url: str = (
            os.environ.get("ARGUS_HWP_RENDER_URL")
            or _get("hwp_render", "url", "")
        )

        # 에이전트(Argus RAG Studio Agent) 하트비트 끊김 감시.
        #   check_interval 초마다 점검하여, disconnect_timeout 초 넘게 무소식이면 DISCONNECTED 로 표시.
        self.agent_heartbeat_check_interval: int = int(
            os.environ.get("ARGUS_AGENT_HEARTBEAT_CHECK_INTERVAL")
            or _get("agent", "heartbeat_check_interval", 30)
        )
        self.agent_heartbeat_disconnect_timeout: int = int(
            os.environ.get("ARGUS_AGENT_HEARTBEAT_DISCONNECT_TIMEOUT")
            or _get("agent", "heartbeat_disconnect_timeout", 120)
        )
        # 에이전트로 Docker 배포 시 사용할 이미지 레지스트리/태그 기본값.
        #   image = "{registry}/argus-rag-studio-<kind>:{tag}" (registry 비면 로컬/Docker Hub).
        self.deploy_image_registry: str = (
            os.environ.get("ARGUS_DEPLOY_IMAGE_REGISTRY")
            or _get("deploy", "image_registry", "")
        )
        self.deploy_image_tag: str = (
            os.environ.get("ARGUS_DEPLOY_IMAGE_TAG")
            or _get("deploy", "image_tag", "latest")
        )
        # arm64 호스트용 vLLM 이미지 — 공식 vllm/vllm-openai 는 x86 전용이라 NGC(aarch64
        # Blackwell 빌드)를 쓴다. 에어갭은 zot 미러 주소로 교체. 전체 레퍼런스 그대로 사용
        # (registry/tag 규약 미적용). entrypoint 차이는 build_container_spec 이 흡수한다.
        self.deploy_vlm_image_arm64: str = (
            os.environ.get("ARGUS_DEPLOY_VLM_IMAGE_ARM64")
            or _get("deploy", "vlm_image_arm64", "nvcr.io/nvidia/vllm:26.02-py3")
        )

        # 검색(M3) — 하이브리드 retrieval 파라미터.
        self.retrieval_top_k: int = int(_get("retrieval", "top_k", 5))
        self.retrieval_vector_k: int = int(_get("retrieval", "vector_k", 20))
        self.retrieval_lexical_k: int = int(_get("retrieval", "lexical_k", 20))
        # RRF(Reciprocal Rank Fusion) 상수 — 클수록 순위 차이가 완만해진다.
        self.retrieval_rrf_k: int = int(_get("retrieval", "rrf_k", 60))
        # 벡터 저장/검색 백엔드 — pgvector(기본) | qdrant | weaviate | milvus | databricks. VectorStore 추상화.
        self.vector_store_provider: str = (
            os.environ.get("ARGUS_VECTOR_STORE") or _get("retrieval", "vector_store", "pgvector")
        )
        # 외부 벡터DB 연결 — provider 별 의미: url(엔드포인트), api_key(있으면), collection_prefix.
        self.vector_store_url: str = (
            os.environ.get("ARGUS_VECTOR_STORE_URL") or _get("retrieval", "vector_store_url", "")
        )
        self.vector_store_api_key: str = (
            os.environ.get("ARGUS_VECTOR_STORE_API_KEY")
            or _get("retrieval", "vector_store_api_key", "")
        )
        self.vector_store_collection_prefix: str = _get(
            "retrieval", "vector_store_collection_prefix", "argus"
        )
        # Databricks Mosaic AI Vector Search 전용 — 인증은 기반 환경의 databricks_host/token 을 재사용한다.
        #   endpoint: Vector Search 엔드포인트(컴퓨트) 이름. catalog.schema: 인덱스가 생성될 Unity Catalog 위치.
        #   인덱스 전체 이름은 ``{catalog}.{schema}.{collection_prefix}_c{id}`` (Direct Access Index).
        self.vector_store_databricks_endpoint: str = _get(
            "retrieval", "vector_store_databricks_endpoint", ""
        )
        self.vector_store_databricks_catalog: str = _get(
            "retrieval", "vector_store_databricks_catalog", "main"
        )
        self.vector_store_databricks_schema: str = _get(
            "retrieval", "vector_store_databricks_schema", "argus"
        )

        # 생성 LLM(M3) — 프로바이더 추상화.
        #   provider:
        #     - "openai_compatible": POST {server_url}/chat/completions (사내 서버/vLLM/Ollama/OpenAI)
        #     - "anthropic": Anthropic Claude (공식 anthropic SDK 사용)
        self.llm_provider: str = _get("llm", "provider", "openai_compatible")
        self.llm_server_url: str = _get("llm", "server_url", "http://localhost:8080/v1")
        self.llm_api_key: str = (
            os.environ.get("ARGUS_LLM_API_KEY") or _get("llm", "api_key", "")
        )
        # 기본 모델: openai_compatible 는 서버가 서빙하는 모델명, anthropic 은 claude-opus-4-8.
        self.llm_model: str = _get("llm", "model", "")
        self.llm_max_tokens: int = int(_get("llm", "max_tokens", 2048))
        self.llm_temperature: float = float(_get("llm", "temperature", 0.2))
        self.llm_timeout: int = int(_get("llm", "timeout", 120))
        # 인증 헤더 커스터마이즈(openai_compatible) — 기본 'Authorization: Bearer'.
        # X-API-Key 게이트웨이 예: auth_header='X-API-Key', auth_scheme=''.
        self.llm_auth_header: str = _get("llm", "auth_header", "Authorization")
        self.llm_auth_scheme: str = _get("llm", "auth_scheme", "Bearer")

        # 리랭킹(M3) — none | llm | cross_encoder
        self.rerank_provider: str = _get("rerank", "provider", "none")
        self.rerank_server_url: str = _get("rerank", "server_url", "http://localhost:8081/rerank")
        self.rerank_top_n: int = int(_get("rerank", "top_n", 5))
        # Argus 리랭커 서버 기본 키와 일치(둘 다 미설정 시 바로 동작). 무인증 서버면 빈값
        self.rerank_api_key: str = (
            os.environ.get("ARGUS_RERANK_API_KEY")
            or _get("rerank", "api_key", "changeme")
        )
        # 인증 헤더 커스터마이즈 — 기본 'Authorization: Bearer'.
        self.rerank_auth_header: str = _get("rerank", "auth_header", "Authorization")
        self.rerank_auth_scheme: str = _get("rerank", "auth_scheme", "Bearer")

        # 어노테이션 자동 bbox 인식(OCR 텍스트 검출) — 외부 detection 서버(PaddleOCR)
        # enabled=False 면 편집기 '자동 인식'이 503 으로 비활성 안내한다.
        self.detection_enabled: bool = _to_bool(_get("detection", "enabled", False))
        self.detection_server_url: str = _get("detection", "server_url", "http://localhost:8082")
        # Argus 검출 서버 기본 키와 일치(둘 다 미설정 시 바로 동작). 무인증 서버면 빈값
        self.detection_api_key: str = (
            os.environ.get("ARGUS_DETECTION_API_KEY")
            or _get("detection", "api_key", "changeme")
        )
        # 인증 헤더 커스터마이즈 — 기본 'Authorization: Bearer'.
        self.detection_auth_header: str = _get("detection", "auth_header", "Authorization")
        self.detection_auth_scheme: str = _get("detection", "auth_scheme", "Bearer")
        # 기본 언어/신뢰도 임계값(요청에서 override 가능) + 호출 타임아웃(초)
        self.detection_lang: str = _get("detection", "lang", "korean")
        self.detection_min_score: float = float(_get("detection", "min_score", 0.5))
        self.detection_timeout: int = int(_get("detection", "timeout", 60))

        # 어노테이션 문서→이미지 변환 — HWP/HWPX 변환 엔진 선택.
        #   rhwp        : 프론트엔드 클라이언트(@rhwp/core, WASM)에서 페이지를 PNG 로 렌더(서버 의존 없음, 기본)
        #   libreoffice : 백엔드 LibreOffice(soffice)로 PDF 변환 후 PyMuPDF 래스터화(soffice 설치 필요)
        # PDF·오피스(doc/ppt/xls 등)는 엔진과 무관하게 항상 백엔드에서 변환한다.
        self.image_conversion_hwp_engine: str = _get("image_conversion", "hwp_engine", "rhwp")
        # 변환 해상도/품질 + 오피스(LibreOffice) 변환 동시성/타임아웃.
        self.image_conversion_dpi: int = int(_get("image_conversion", "dpi", 150))
        self.image_conversion_thumbnail_max: int = int(
            _get("image_conversion", "thumbnail_max", 320)
        )
        # HWP(rhwp, 클라이언트) 렌더 배율 — 프론트가 convert-config 로 받아 사용.
        self.image_conversion_hwp_scale: float = float(
            _get("image_conversion", "hwp_scale", 2.0)
        )
        self.image_conversion_office_concurrency: int = int(
            _get("image_conversion", "office_concurrency", 2)
        )
        self.image_conversion_office_timeout: int = int(
            _get("image_conversion", "office_timeout", 90)
        )

        # 이미지 추출 및 분류 — 문서 내 이미지(도표/차트/사진 등)를 비전 LLM(VLM)으로 식별.
        #   enabled=False(기본)면 인제스천에서 분류를 건너뛴다(현 동작과 동일).
        #   server_url/model 이 비어 있으면 생성 LLM(llm.*) 설정을 그대로 재사용한다
        #   — 같은 OpenAI 호환 비전 엔드포인트(vLLM Qwen2.5-VL 등)를 가리키면 된다.
        self.image_classification_enabled: bool = _to_bool(
            _get("image_classification", "enabled", False)
        )
        self.image_classification_server_url: str = _get(
            "image_classification", "server_url", ""
        )
        self.image_classification_model: str = _get("image_classification", "model", "")
        # 추가 VLM 모델 카탈로그(CSV: name=repo[@max_len] 또는 repo) — 사전 정의에 병합.
        self.image_classification_extra_models: str = _get(
            "image_classification", "extra_models", ""
        )
        self.image_classification_api_key: str = (
            os.environ.get("ARGUS_IMAGE_CLASSIFICATION_API_KEY")
            or _get("image_classification", "api_key", "")
        )
        self.image_classification_auth_header: str = _get(
            "image_classification", "auth_header", "Authorization"
        )
        self.image_classification_auth_scheme: str = _get(
            "image_classification", "auth_scheme", "Bearer"
        )
        # 분류 카테고리(쉼표 구분) — 프롬프트와 검증에 사용.
        self.image_classification_categories: str = _get(
            "image_classification",
            "categories",
            "chart,table,diagram,photo,screenshot,formula,logo,other",
        )
        # 이 픽셀(긴 변) 미만 이미지는 아이콘/장식으로 보고 분류에서 제외.
        self.image_classification_min_pixels: int = int(
            _get("image_classification", "min_pixels", 64)
        )
        # 문서 1건당 분류할 최대 이미지 수(비용/지연 가드).
        self.image_classification_max_images: int = int(
            _get("image_classification", "max_images", 50)
        )
        self.image_classification_timeout: int = int(
            _get("image_classification", "timeout", 60)
        )
        # 심층 내용 분석 — 켜면 유형 분류와 함께 상세 설명·이미지 내 텍스트(OCR)·표/수식
        # 구조화를 한 번의 VLM 호출로 추출한다. 끄면 유형 + 한 줄 요약만(저비용).
        self.image_classification_content_analysis: bool = _to_bool(
            _get("image_classification", "content_analysis", True)
        )
        # 심층 분석 응답 토큰 한도 — OCR/표가 길 수 있어 넉넉히(경량 모드는 256 고정).
        self.image_classification_max_tokens: int = int(
            _get("image_classification", "max_tokens", 768)
        )
        # URL 가져오기에서 '작은 이미지 제거' 시 버릴 최소 파일 크기(KB). 이 값 미만은 아이콘·
        # 트래킹 픽셀로 보고 제외한다.
        self.image_classification_small_image_min_kb: int = int(
            _get("image_classification", "small_image_min_kb", 10)
        )

        # 내용 기반 문서 분류(P3) — 규칙(P2)이 못 잡은(other/저신뢰) 문서를 임베딩 앵커
        # 유사도로 doc_type 추정한다. 컬렉션 임베딩 서버를 재사용(에어갭). 끄면 규칙만(P2).
        self.content_classification_enabled: bool = _to_bool(
            _get("content_classification", "enabled", False)
        )
        # 앵커 유사도가 이 값(코사인) 이상일 때만 doc_type 을 채택. 미만이면 other 유지.
        self.content_classification_threshold: float = float(
            _get("content_classification", "threshold", 0.45)
        )
        # 문서 선두 텍스트를 이 길이까지만 임베딩해 유형을 추정(비용/지연 가드).
        self.content_classification_lead_chars: int = int(
            _get("content_classification", "lead_chars", 1500)
        )

        # 미리보기(S3 브라우저) — parquet/xlsx 미리보기 최대 행수.
        self.preview_max_rows: int = int(_get("preview", "max_rows", 1000))

        # 관측성 — 질의 트레이스에 저장할 답변 최대 길이(자).
        self.observability_answer_limit: int = int(
            _get("observability", "answer_limit", 2000)
        )

        # 스토리지 백엔드 — s3(기본, MinIO/S3 호환) | uc_volumes(Databricks Unity Catalog Volumes).
        #   uc_volumes 는 기반 환경의 databricks_host/token 으로 인증하고 아래 catalog/schema/volume 위치를 쓴다.
        #   (annotation/imagerecog 버킷은 이 단계에선 S3 전용 — 별도 raw boto3 사용.)
        self.storage_backend: str = (
            os.environ.get("ARGUS_STORAGE_BACKEND") or _get("object_storage", "backend", "s3")
        )
        self.storage_databricks_catalog: str = _get("object_storage", "databricks_catalog", "main")
        self.storage_databricks_schema: str = _get("object_storage", "databricks_schema", "argus")
        self.storage_databricks_volume: str = _get("object_storage", "databricks_volume", "documents")

        # Object Storage (MinIO / S3) — 원본 문서/아티팩트 저장소.
        # 원격/분리 워커가 라우팅 가능한 주소로 접근할 수 있도록 ARGUS_OS_* 환경변수 오버라이드를 지원한다
        # (config 파일 → env 우선). 미설정 시 config 값(없으면 기본값).
        self.os_endpoint: str = os.environ.get("ARGUS_OS_ENDPOINT") or _get(
            "object_storage", "endpoint", "http://localhost:9000"
        )
        self.os_access_key: str = os.environ.get("ARGUS_OS_ACCESS_KEY") or _get(
            "object_storage", "access_key", "minioadmin"
        )
        self.os_secret_key: str = os.environ.get("ARGUS_OS_SECRET_KEY") or _get(
            "object_storage", "secret_key", "minioadmin"
        )
        self.os_region: str = os.environ.get("ARGUS_OS_REGION") or _get(
            "object_storage", "region", "us-east-1"
        )
        _os_use_ssl_env = os.environ.get("ARGUS_OS_USE_SSL")
        self.os_use_ssl: bool = (
            _to_bool(_os_use_ssl_env)
            if _os_use_ssl_env is not None
            else _to_bool(_get("object_storage", "use_ssl", False))
        )
        self.os_bucket: str = os.environ.get("ARGUS_OS_BUCKET") or _get(
            "object_storage", "bucket", "rag-documents"
        )
        # 어노테이션 이미지 전용 버킷(폴더 탐색기). 원본 문서 버킷과 분리한다.
        self.os_annotation_bucket: str = _get("object_storage", "annotation_bucket", "annotation-images")
        # 이미지 추출 및 분류 결과 전용 버킷 — 원본·썸네일·분석 JSON 저장. 다른 버킷과 분리한다.
        self.os_classification_bucket: str = _get("object_storage", "classification_bucket", "classification-images")
        # presigned 다운로드 URL 만료(초).
        self.os_presign_expiry: int = int(_get("object_storage", "presign_expiry", 3600))

        # 모델 저장소 버킷(에어갭 모델 레지스트리 — design/model-packaging.md).
        self.os_models_bucket: str = _get("object_storage", "models_bucket", "argus-models")

        # 스토리지 소스(참조 인테이크의 원본 소스) — read 전 stat 로 검사하는 파일 크기 상한(MB).
        self.source_max_fetch_mb: int = int(_get("storage_sources", "max_fetch_mb", 200))

        # 소스 워치(자동 수집 — design/source-watch.md). watch_enabled=false 면 내장 워처를
        # 끄고 외부 스케줄러(NiFi 등)가 intake-scan API 를 호출하는 운영으로 대체한다.
        self.watch_enabled: bool = str(
            _get("storage_sources", "watch_enabled", "true")
        ).lower() in ("1", "true", "yes", "on")
        self.watch_tick_seconds: int = int(_get("storage_sources", "watch_tick_seconds", 15))
        self.watch_min_interval_seconds: int = int(
            _get("storage_sources", "watch_min_interval_seconds", 60)
        )
        self.watch_runs_keep: int = int(_get("storage_sources", "watch_runs_keep", 100))
        self.seen_prune_days: int = int(_get("storage_sources", "seen_prune_days", 30))


def init_settings(
    yaml_path: str | None = None,
    properties_path: str | None = None,
) -> None:
    """사용자 지정 설정 파일 경로로 설정을 재초기화한다."""
    global _raw, _yaml_path, _properties_path
    if yaml_path:
        _yaml_path = Path(yaml_path)
    if properties_path:
        _properties_path = Path(properties_path)
    _raw = load_config(
        config_dir=_CONFIG_DIR,
        yaml_path=yaml_path,
        properties_path=properties_path,
    )
    settings.__init__()


settings = Settings()
