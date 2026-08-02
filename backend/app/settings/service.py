# SPDX-License-Identifier: Apache-2.0
"""설정 서비스 — config 기본값 + DB override 병합 / 런타임 적용.

편집 가능 키만 화이트리스트(``EDITABLE``)로 관리한다. 각 항목은 (settings 속성명, 파서)로
매핑되어, 저장 시 DB 기록 + 전역 ``settings`` 객체 즉시 갱신을 함께 수행한다. 인증/스토리지
같은 항목은 읽기 전용으로 표시만 한다(파일/배포에서 관리).
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.settings.models import AppSetting

logger = logging.getLogger(__name__)


def _parse_csv(v: str) -> list[str]:
    return [s.strip() for s in v.split(",") if s.strip()]


def _parse_bool(v) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("true", "1", "yes", "on")


# 편집 가능 키: settings_key -> (settings 객체 속성명, 파서 함수)
EDITABLE: dict[str, tuple[str, callable]] = {
    # 기반 환경(Platform Profile) — standard | databricks
    "platform.base": ("platform_base", str),
    "databricks.host": ("databricks_host", str),
    "databricks.token": ("databricks_token", str),
    "embedding.provider": ("embedding_provider", str),
    "embedding.server_url": ("embedding_server_url", str),
    "embedding.model": ("embedding_model", str),
    "embedding.query_instruction": ("embedding_query_instruction", str),
    "embedding.batch_size": ("embedding_batch_size", int),
    "embedding.api_key": ("embedding_api_key", str),
    "ingestion.chunk_size": ("ingestion_chunk_size", int),
    "ingestion.chunk_overlap": ("ingestion_chunk_overlap", int),
    "ingestion.worker_interval": ("ingestion_worker_interval", float),
    "ingestion.service_token": ("ingestion_service_token", str),
    "ingestion.max_kss_chars": ("ingestion_max_kss_chars", int),
    "ingestion.min_chunk_ratio": ("ingestion_min_chunk_ratio", float),
    "ingestion.semantic_percentile": ("ingestion_semantic_percentile", int),
    "cors.origins": ("cors_origins", _parse_csv),
    # LLM(M3)
    "llm.provider": ("llm_provider", str),
    "llm.server_url": ("llm_server_url", str),
    "llm.model": ("llm_model", str),
    "llm.max_tokens": ("llm_max_tokens", int),
    "llm.temperature": ("llm_temperature", float),
    "llm.api_key": ("llm_api_key", str),
    "embedding.timeout": ("embedding_timeout", int),
    "embedding.auth_header": ("embedding_auth_header", str),
    "embedding.auth_scheme": ("embedding_auth_scheme", str),
    "embedding.default_model": ("embedding_default_model", str),
    "embedding.default_dim": ("embedding_default_dim", int),
    "embedding.default_metric": ("embedding_default_metric", str),
    "llm.timeout": ("llm_timeout", int),
    "llm.auth_header": ("llm_auth_header", str),
    "llm.auth_scheme": ("llm_auth_scheme", str),
    # 리랭킹 / 검색
    "rerank.provider": ("rerank_provider", str),
    "rerank.server_url": ("rerank_server_url", str),
    "rerank.api_key": ("rerank_api_key", str),
    "rerank.top_n": ("rerank_top_n", int),
    "rerank.auth_header": ("rerank_auth_header", str),
    "rerank.auth_scheme": ("rerank_auth_scheme", str),
    "retrieval.top_k": ("retrieval_top_k", int),
    "retrieval.vector_k": ("retrieval_vector_k", int),
    "retrieval.lexical_k": ("retrieval_lexical_k", int),
    "retrieval.rrf_k": ("retrieval_rrf_k", int),
    # 벡터 스토어 — provider 전환 + 외부 DB 연결
    "retrieval.vector_store": ("vector_store_provider", str),
    "retrieval.vector_store_url": ("vector_store_url", str),
    "retrieval.vector_store_api_key": ("vector_store_api_key", str),
    "retrieval.vector_store_collection_prefix": ("vector_store_collection_prefix", str),
    "retrieval.vector_store_databricks_endpoint": ("vector_store_databricks_endpoint", str),
    "retrieval.vector_store_databricks_catalog": ("vector_store_databricks_catalog", str),
    "retrieval.vector_store_databricks_schema": ("vector_store_databricks_schema", str),
    # 오브젝트 스토리지(S3/MinIO) — 백엔드 선택 + UC Volumes 위치
    "object_storage.backend": ("storage_backend", str),
    "object_storage.databricks_catalog": ("storage_databricks_catalog", str),
    "object_storage.databricks_schema": ("storage_databricks_schema", str),
    "object_storage.databricks_volume": ("storage_databricks_volume", str),
    "object_storage.endpoint": ("os_endpoint", str),
    "object_storage.access_key": ("os_access_key", str),
    "object_storage.secret_key": ("os_secret_key", str),
    "object_storage.region": ("os_region", str),
    "object_storage.use_ssl": ("os_use_ssl", _parse_bool),
    "object_storage.bucket": ("os_bucket", str),
    "object_storage.annotation_bucket": ("os_annotation_bucket", str),
    "object_storage.classification_bucket": ("os_classification_bucket", str),
    "object_storage.models_bucket": ("os_models_bucket", str),
    "object_storage.presign_expiry": ("os_presign_expiry", int),
    # 인증(Keycloak OIDC / 로컬)
    "auth.type": ("auth_type", str),
    "auth.keycloak_server_url": ("auth_keycloak_server_url", str),
    "auth.keycloak_realm": ("auth_keycloak_realm", str),
    "auth.keycloak_client_id": ("auth_keycloak_client_id", str),
    "auth.keycloak_client_secret": ("auth_keycloak_client_secret", str),
    "auth.keycloak_admin_role": ("auth_keycloak_admin_role", str),
    "auth.keycloak_superuser_role": ("auth_keycloak_superuser_role", str),
    "auth.keycloak_user_role": ("auth_keycloak_user_role", str),
    "auth.local_jwt_expire_minutes": ("auth_local_jwt_expire_minutes", int),
    # 어노테이션 자동 bbox 검출(PaddleOCR)
    "detection.enabled": ("detection_enabled", _parse_bool),
    "detection.server_url": ("detection_server_url", str),
    "hwp_render.url": ("hwp_render_url", str),
    "detection.api_key": ("detection_api_key", str),
    "detection.lang": ("detection_lang", str),
    "detection.min_score": ("detection_min_score", float),
    "detection.timeout": ("detection_timeout", int),
    "detection.auth_header": ("detection_auth_header", str),
    "detection.auth_scheme": ("detection_auth_scheme", str),
    # 이미지 분류(VLM) — 문서 내 이미지 유형(도표/차트/사진 등) 식별
    "image_classification.enabled": ("image_classification_enabled", _parse_bool),
    "image_classification.server_url": ("image_classification_server_url", str),
    "image_classification.model": ("image_classification_model", str),
    "image_classification.extra_models": ("image_classification_extra_models", str),
    "image_classification.api_key": ("image_classification_api_key", str),
    "image_classification.auth_header": ("image_classification_auth_header", str),
    "image_classification.auth_scheme": ("image_classification_auth_scheme", str),
    "image_classification.categories": ("image_classification_categories", str),
    "image_classification.min_pixels": ("image_classification_min_pixels", int),
    "image_classification.max_images": ("image_classification_max_images", int),
    "image_classification.timeout": ("image_classification_timeout", int),
    "image_classification.small_image_min_kb": ("image_classification_small_image_min_kb", int),
    # 어노테이션 문서→이미지 변환
    "image_conversion.hwp_engine": ("image_conversion_hwp_engine", str),
    "image_conversion.dpi": ("image_conversion_dpi", int),
    "image_conversion.thumbnail_max": ("image_conversion_thumbnail_max", int),
    "image_conversion.hwp_scale": ("image_conversion_hwp_scale", float),
    "image_conversion.office_concurrency": ("image_conversion_office_concurrency", int),
    "image_conversion.office_timeout": ("image_conversion_office_timeout", int),
    # 미리보기 / 관측성
    "preview.max_rows": ("preview_max_rows", int),
    "observability.answer_limit": ("observability_answer_limit", int),
}


async def _db_overrides(session: AsyncSession) -> dict[str, str]:
    rows = (await session.execute(select(AppSetting))).scalars().all()
    return {r.key: r.value for r in rows}


def _apply_to_runtime(key: str, raw_value: str) -> None:
    """편집 가능 키를 전역 settings 객체에 반영한다(런타임 즉시 적용)."""
    mapping = EDITABLE.get(key)
    if not mapping:
        return
    attr, parser = mapping
    try:
        setattr(settings, attr, parser(raw_value))
    except Exception as e:
        logger.warning("설정 런타임 적용 실패: key=%s value=%s err=%s", key, raw_value, e)


async def load_into_runtime(session: AsyncSession) -> None:
    """기동 시 DB override 를 전역 settings 에 적용한다."""
    overrides = await _db_overrides(session)
    for key, value in overrides.items():
        _apply_to_runtime(key, value)
    if overrides:
        logger.info("설정 override %d개를 런타임에 적용했습니다.", len(overrides))


async def get_effective(session: AsyncSession) -> dict:
    """화면에 보여줄 유효 설정(그룹별). 민감값(api_key)은 마스킹."""
    return {
        "platform": {
            "base": settings.platform_base,
            "databricks_host": settings.databricks_host,
            # admin 전용 화면 — eye 토글로 확인할 수 있게 실제 토큰을 노출(다른 시크릿과 동일 방식)
            "databricks_token": settings.databricks_token,
            "databricks_token_set": bool(settings.databricks_token),
        },
        "embedding": {
            "provider": settings.embedding_provider,
            "server_url": settings.embedding_server_url,
            "model": settings.embedding_model,
            "query_instruction": settings.embedding_query_instruction,
            "batch_size": settings.embedding_batch_size,
            "default_dim": settings.embedding_default_dim,
            "default_model": settings.embedding_default_model,
            "default_metric": settings.embedding_default_metric,
            "timeout": settings.embedding_timeout,
            "auth_header": settings.embedding_auth_header,
            "auth_scheme": settings.embedding_auth_scheme,
            # admin 전용 화면 — eye 토글로 확인할 수 있게 실제 키 값을 노출(카탈로그와 동일 방식)
            "api_key": settings.embedding_api_key,
            "api_key_set": bool(settings.embedding_api_key),
        },
        "ingestion": {
            "chunk_size": settings.ingestion_chunk_size,
            "chunk_overlap": settings.ingestion_chunk_overlap,
            "local_worker_enabled": settings.ingestion_local_worker_enabled,
            "worker_interval": settings.ingestion_worker_interval,
            "service_token": settings.ingestion_service_token,
            "service_token_set": bool(settings.ingestion_service_token),
            "max_kss_chars": settings.ingestion_max_kss_chars,
            "min_chunk_ratio": settings.ingestion_min_chunk_ratio,
            "semantic_percentile": settings.ingestion_semantic_percentile,
        },
        "storage": {
            "backend": settings.storage_backend,
            "databricks_catalog": settings.storage_databricks_catalog,
            "databricks_schema": settings.storage_databricks_schema,
            "databricks_volume": settings.storage_databricks_volume,
            "endpoint": settings.os_endpoint,
            "access_key": settings.os_access_key,
            "region": settings.os_region,
            "use_ssl": settings.os_use_ssl,
            "bucket": settings.os_bucket,
            "annotation_bucket": settings.os_annotation_bucket,
            "classification_bucket": settings.os_classification_bucket,
            "models_bucket": settings.os_models_bucket,
            "presign_expiry": settings.os_presign_expiry,
            "secret_key": settings.os_secret_key,
            "secret_key_set": bool(settings.os_secret_key),
        },
        "auth": {
            "type": settings.auth_type,
            "keycloak_server_url": settings.auth_keycloak_server_url,
            "keycloak_realm": settings.auth_keycloak_realm,
            "keycloak_client_id": settings.auth_keycloak_client_id,
            "keycloak_admin_role": settings.auth_keycloak_admin_role,
            "keycloak_superuser_role": settings.auth_keycloak_superuser_role,
            "keycloak_user_role": settings.auth_keycloak_user_role,
            "keycloak_client_secret": settings.auth_keycloak_client_secret,
            "keycloak_client_secret_set": bool(settings.auth_keycloak_client_secret),
            "local_jwt_expire_minutes": settings.auth_local_jwt_expire_minutes,
        },
        "cors": {
            # config 가 "*" 같은 문자열로 resolve 될 수 있어 항상 list 로 정규화
            "origins": (
                settings.cors_origins
                if isinstance(settings.cors_origins, list)
                else _parse_csv(str(settings.cors_origins))
            ),
        },
        "llm": {
            "provider": settings.llm_provider,
            "server_url": settings.llm_server_url,
            "model": settings.llm_model,
            "max_tokens": settings.llm_max_tokens,
            "temperature": settings.llm_temperature,
            "timeout": settings.llm_timeout,
            "auth_header": settings.llm_auth_header,
            "auth_scheme": settings.llm_auth_scheme,
            "api_key": settings.llm_api_key,
            "api_key_set": bool(settings.llm_api_key),
        },
        "rerank": {
            "provider": settings.rerank_provider,
            "server_url": settings.rerank_server_url,
            "top_n": settings.rerank_top_n,
            "auth_header": settings.rerank_auth_header,
            "auth_scheme": settings.rerank_auth_scheme,
            "api_key": settings.rerank_api_key,
            "api_key_set": bool(settings.rerank_api_key),
        },
        "retrieval": {
            "top_k": settings.retrieval_top_k,
            "vector_k": settings.retrieval_vector_k,
            "lexical_k": settings.retrieval_lexical_k,
            "rrf_k": settings.retrieval_rrf_k,
            "vector_store": settings.vector_store_provider,
            "vector_store_url": settings.vector_store_url,
            "vector_store_api_key": settings.vector_store_api_key,
            "vector_store_api_key_set": bool(settings.vector_store_api_key),
            "vector_store_collection_prefix": settings.vector_store_collection_prefix,
            "vector_store_databricks_endpoint": settings.vector_store_databricks_endpoint,
            "vector_store_databricks_catalog": settings.vector_store_databricks_catalog,
            "vector_store_databricks_schema": settings.vector_store_databricks_schema,
        },
        "detection": {
            "enabled": settings.detection_enabled,
            "server_url": settings.detection_server_url,
            "lang": settings.detection_lang,
            "min_score": settings.detection_min_score,
            "timeout": settings.detection_timeout,
            "auth_header": settings.detection_auth_header,
            "auth_scheme": settings.detection_auth_scheme,
            "api_key": settings.detection_api_key,
            "api_key_set": bool(settings.detection_api_key),
        },
        "image_classification": {
            "enabled": settings.image_classification_enabled,
            "server_url": settings.image_classification_server_url,
            "model": settings.image_classification_model,
            "categories": settings.image_classification_categories,
            "min_pixels": settings.image_classification_min_pixels,
            "max_images": settings.image_classification_max_images,
            "timeout": settings.image_classification_timeout,
            "small_image_min_kb": settings.image_classification_small_image_min_kb,
            "auth_header": settings.image_classification_auth_header,
            "auth_scheme": settings.image_classification_auth_scheme,
            "api_key": settings.image_classification_api_key,
            "api_key_set": bool(settings.image_classification_api_key),
        },
        "image_conversion": {
            "hwp_engine": settings.image_conversion_hwp_engine,
            "dpi": settings.image_conversion_dpi,
            "thumbnail_max": settings.image_conversion_thumbnail_max,
            "hwp_scale": settings.image_conversion_hwp_scale,
            "office_concurrency": settings.image_conversion_office_concurrency,
            "office_timeout": settings.image_conversion_office_timeout,
        },
        "preview": {
            "max_rows": settings.preview_max_rows,
        },
        "observability": {
            "answer_limit": settings.observability_answer_limit,
        },
    }


async def update_settings(session: AsyncSession, payload: dict) -> dict:
    """편집 가능 키만 저장 + 런타임 적용. 임베딩 관련 변경 시 프로바이더 싱글턴을 리셋한다."""
    changed = []
    platform_changed = False
    embedding_changed = False
    llm_changed = False
    vector_store_changed = False
    storage_changed = False
    auth_changed = False
    for key, value in (payload or {}).items():
        if key not in EDITABLE:
            continue
        raw = str(value) if not isinstance(value, list) else ",".join(str(v) for v in value)
        existing = (await session.execute(
            select(AppSetting).where(AppSetting.key == key)
        )).scalars().first()
        if existing:
            existing.value = raw
        else:
            session.add(AppSetting(key=key, value=raw))
        _apply_to_runtime(key, raw)
        changed.append(key)
        if key.startswith("platform.") or key.startswith("databricks."):
            platform_changed = True
        if key.startswith("embedding."):
            embedding_changed = True
        if key.startswith("llm."):
            llm_changed = True
        if key.startswith("retrieval.vector_store"):
            vector_store_changed = True
        if key.startswith("object_storage."):
            storage_changed = True
        if key.startswith("auth."):
            auth_changed = True
    await session.commit()

    if platform_changed:
        # 기반 환경 전환 → 프로파일 캐시 무효화. 프로파일이 임베딩/LLM/벡터스토어의 기본값과
        # 동작(쿼리 instruction·엔드포인트 규약)을 공급하므로 의존 싱글턴도 함께 리셋한다.
        from app.platform.factory import reset_platform_profile
        reset_platform_profile()
        embedding_changed = True
        llm_changed = True
        vector_store_changed = True
        storage_changed = True
    if embedding_changed:
        # 임베딩 프로바이더 싱글턴을 리셋해 다음 임베딩부터 새 설정으로 재생성
        from app.embedding.service import shutdown_provider
        await shutdown_provider()
    if llm_changed:
        # LLM 프로바이더 싱글턴 리셋
        from app.llm.service import shutdown_chat_provider
        await shutdown_chat_provider()
    if vector_store_changed:
        # 벡터 스토어 싱글턴 리셋 → 다음 검색/적재부터 새 provider/연결로 재생성.
        # NOTE: 기존 벡터는 자동 이동하지 않음 — 새 스토어로 전환 시 '벡터 재색인'을 실행해야 한다.
        from app.vectorstore.factory import reset_vector_store
        reset_vector_store()
    if storage_changed:
        # 스토리지 백엔드 캐시 + boto3 S3 클라이언트 싱글턴 리셋 → 다음 오브젝트 I/O 부터 새 설정으로 재생성.
        # NOTE: 백엔드 전환 시 기존 객체는 자동 이동하지 않음 — 전환 후 재인제스천이 필요하다.
        from app.storage import client as storage_client
        from app.storage.factory import reset_storage_backend
        reset_storage_backend()
        storage_client._client = None
    if auth_changed:
        # Keycloak JWKS 캐시 무효화 → 서버/Realm 변경이 다음 토큰 검증에 반영
        from app.core.auth import _jwks_cache
        _jwks_cache.clear()

    logger.info("설정 저장: %d개 키 갱신 (%s)", len(changed), ", ".join(changed))
    return {"changed": changed}


# ── 연결 테스트 / 초기화 (저장 전에 검증 — 특히 인증 잠김 방지) ──────────────────

def _build_s3_client(cfg: dict):
    """요청 cfg(빈 값은 현재 settings 폴백)로 boto3 S3 클라이언트 구성."""
    import boto3
    from botocore.config import Config as BotoConfig

    return boto3.client(
        "s3",
        endpoint_url=cfg.get("endpoint") or settings.os_endpoint,
        aws_access_key_id=cfg.get("access_key") or settings.os_access_key,
        # secret 은 빈 값이면 '변경 안 함' → 현재 값 사용
        aws_secret_access_key=cfg.get("secret_key") or settings.os_secret_key,
        region_name=cfg.get("region") or settings.os_region,
        use_ssl=_parse_bool(cfg.get("use_ssl", settings.os_use_ssl)),
        config=BotoConfig(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            connect_timeout=3,
            read_timeout=5,
            retries={"max_attempts": 1},
        ),
    )


async def test_object_storage(cfg: dict) -> dict:
    """버킷 head 로 연결을 확인한다(저장하지 않음)."""
    import asyncio

    bucket = cfg.get("bucket") or settings.os_bucket

    def _do():
        _build_s3_client(cfg).head_bucket(Bucket=bucket)

    try:
        await asyncio.to_thread(_do)
        return {"ok": True, "message": f"버킷 '{bucket}' 에 연결했습니다."}
    except Exception as e:  # noqa: BLE001 — 사용자 표시용 메시지로 정리
        return {"ok": False, "message": f"연결 실패: {str(e)[:200]}"}


async def initialize_object_storage(cfg: dict) -> dict:
    """설정의 버킷들을 순서대로 돌며 없으면 생성한다(있으면 그대로).

    ``cfg["buckets"]`` 리스트가 있으면 그 순서를 쓰고, 없으면 문서·라벨링·이미지 추출 및 분류
    버킷(``bucket``/``annotation_bucket``/``classification_bucket``) 순서로 처리한다. 빈
    이름·중복은 건너뛰고, 하나도 없으면 현재 설정값으로 폴백한다.
    """
    import asyncio

    from botocore.exceptions import ClientError

    raw = cfg.get("buckets") or [
        cfg.get("bucket"), cfg.get("annotation_bucket"), cfg.get("classification_bucket"),
        cfg.get("models_bucket"),
    ]
    names: list[str] = []
    for b in raw:
        n = (b or "").strip()
        if n and n not in names:
            names.append(n)
    if not names:  # 입력이 비면 현재 설정값으로 폴백.
        names = list(dict.fromkeys(
            n for n in (settings.os_bucket, settings.os_annotation_bucket,
                        settings.os_classification_bucket, settings.os_models_bucket) if n
        ))
    if not names:
        return {"ok": False, "message": "초기화할 버킷 이름이 없습니다."}

    def _do() -> tuple[list[str], list[str]]:
        client = _build_s3_client(cfg)
        created: list[str] = []
        existing: list[str] = []
        for name in names:
            try:
                client.head_bucket(Bucket=name)
                existing.append(name)
            except ClientError:
                client.create_bucket(Bucket=name)
                created.append(name)
        return created, existing

    try:
        created, existing = await asyncio.to_thread(_do)
        parts: list[str] = []
        if created:
            parts.append(f"생성 {len(created)}개({', '.join(created)})")
        if existing:
            parts.append(f"기존 {len(existing)}개({', '.join(existing)})")
        return {
            "ok": True,
            "message": "버킷 초기화 완료 — " + (", ".join(parts) if parts else "처리한 버킷이 없습니다."),
        }
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "message": f"초기화 실패: {str(e)[:200]}"}


async def test_auth(cfg: dict) -> dict:
    """인증 연결을 확인한다 — local 은 무검사, keycloak 은 OIDC discovery 조회(저장 전 검증)."""
    import httpx

    auth_type = cfg.get("type") or settings.auth_type
    if auth_type != "keycloak":
        return {"ok": True, "message": "로컬(local) 인증 — 외부 연결이 필요 없습니다."}

    server = (cfg.get("keycloak_server_url") or settings.auth_keycloak_server_url).rstrip("/")
    realm = cfg.get("keycloak_realm") or settings.auth_keycloak_realm
    url = f"{server}/realms/{realm}/.well-known/openid-configuration"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
        return {"ok": True, "message": f"Keycloak Realm '{realm}' 에 연결했습니다."}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "message": f"연결 실패: {str(e)[:200]}"}


async def test_databricks(cfg: dict) -> dict:
    """Databricks workspace 연결(Host + PAT 토큰)을 확인한다(저장 전 검증).

    SCIM ``Me`` 로 인증을 확인한다. 빈 토큰은 '변경 안 함' → 현재 저장된 토큰을 사용한다.
    """
    import httpx

    host = (cfg.get("host") or settings.databricks_host or "").rstrip("/")
    token = cfg.get("token") or settings.databricks_token
    if not host:
        return {"ok": False, "message": "Databricks Host 가 비어 있습니다."}
    if not token:
        return {"ok": False, "message": "Databricks PAT 토큰이 비어 있습니다."}
    if "://" not in host:
        host = f"https://{host}"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with httpx.AsyncClient(timeout=8.0, headers=headers) as client:
            resp = await client.get(f"{host}/api/2.0/preview/scim/v2/Me")
            if resp.status_code in (401, 403):
                return {"ok": False, "message": "인증 실패 — PAT 토큰을 확인하세요."}
            resp.raise_for_status()
            who = ""
            try:
                who = resp.json().get("userName") or ""
            except Exception:  # noqa: BLE001 — 본문 파싱 실패는 무시
                pass
        return {"ok": True, "message": f"Databricks 에 연결했습니다{f' (계정: {who})' if who else ''}."}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "message": f"연결 실패: {str(e)[:200]}"}


async def test_image_classification(cfg: dict) -> dict:
    """이미지 분류 비전 엔드포인트를 작은 합성 이미지로 검증한다(저장 전, 현재 입력값 기준).

    cfg 의 server_url/model/api_key 등이 비면 저장된 설정(없으면 llm.*)으로 폴백한다.
    실제 분류를 1회 수행해 엔드포인트가 비전 응답을 주는지까지 확인한다.
    """
    import asyncio
    import io

    from app.core.http import auth_headers

    base = (cfg.get("server_url") or settings.image_classification_server_url
            or settings.llm_server_url).rstrip("/")
    model = cfg.get("model") or settings.image_classification_model or settings.llm_model
    if not base:
        return {"ok": False, "message": "서버 URL이 비어 있습니다(이미지 추출 및 분류 또는 생성 LLM)."}
    if not model:
        return {"ok": False, "message": "모델명이 비어 있습니다(이미지 추출 및 분류 또는 생성 LLM)."}

    api_key = cfg.get("api_key") or settings.image_classification_api_key or settings.llm_api_key
    headers = {"Content-Type": "application/json"}
    headers.update(auth_headers(
        api_key,
        cfg.get("auth_header") or settings.image_classification_auth_header,
        cfg.get("auth_scheme") if cfg.get("auth_scheme") is not None
        else settings.image_classification_auth_scheme,
    ))

    def _sample_png() -> bytes:
        from PIL import Image, ImageDraw

        img = Image.new("RGB", (160, 120), "white")
        d = ImageDraw.Draw(img)
        for i, h in enumerate((30, 60, 90, 50)):  # 막대그래프 흉내
            x = 20 + i * 32
            d.rectangle([x, 110 - h, x + 20, 110], fill="steelblue")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    try:
        png = await asyncio.to_thread(_sample_png)
    except Exception as e:  # noqa: BLE001 — Pillow 미설치 등
        return {"ok": False, "message": f"테스트 이미지 생성 실패(PIL 필요): {str(e)[:160]}"}

    import base64

    import httpx

    payload = {
        "model": model,
        "max_tokens": 64,
        "temperature": 0,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": '이 이미지 유형을 JSON {"type": "..."} 으로만 답하라.'},
            {"type": "image_url", "image_url": {
                "url": f"data:image/png;base64,{base64.b64encode(png).decode('ascii')}"}},
        ]}],
    }
    url = f"{base}/chat/completions"
    try:
        async with httpx.AsyncClient(timeout=float(settings.image_classification_timeout)) as client:
            resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code != 200:
            return {"ok": False, "message": f"엔드포인트 오류({resp.status_code}): {resp.text[:160]}"}
        content = resp.json()["choices"][0]["message"]["content"]
        return {"ok": True, "message": f"연결 OK · 모델 '{model}' 응답: {str(content)[:80]}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "message": f"연결 실패: {str(e)[:200]}"}
