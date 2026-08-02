# SPDX-License-Identifier: Apache-2.0
"""서버 관리 서비스 — argus_agents 조회/등록/해제 + 워커 배포(servicemgr) 헬퍼."""

import logging
import re

from sqlalchemy import Integer, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import ArgusAgent, ArgusAgentHeartbeat
from app.core.config import settings
from app.servermgr.schemas import (
    DeployWorkerRequest,
    PaginatedServerResponse,
    RegisterResponse,
    ServerResponse,
    UnregisterResponse,
)

# servicemgr 관리 워커 unit 접두사 (에이전트 MANAGED_PREFIX 와 일치).
WORKER_NAME_PREFIX = "argus-rag-worker-"
_WORKER_RE = re.compile(rf"^{re.escape(WORKER_NAME_PREFIX)}(\d+)$")

logger = logging.getLogger(__name__)


async def list_servers(
    session: AsyncSession,
    status: str | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 10,
) -> PaginatedServerResponse:
    """필터·페이지네이션을 적용해 서버 목록을 반환한다."""
    heartbeat_seconds = (
        func.extract("epoch", func.now() - ArgusAgentHeartbeat.last_heartbeat_at)
        .cast(Integer)
        .label("last_heartbeat_seconds")
    )

    base = select(ArgusAgent, heartbeat_seconds).outerjoin(
        ArgusAgentHeartbeat, ArgusAgent.hostname == ArgusAgentHeartbeat.hostname
    )

    if status:
        status_list = [s.strip() for s in status.split(",") if s.strip()]
        if status_list:
            base = base.where(ArgusAgent.status.in_(status_list))

    if search:
        pattern = f"%{search}%"
        base = base.where(
            or_(
                ArgusAgent.hostname.ilike(pattern),
                ArgusAgent.ip_address.ilike(pattern),
            )
        )

    count_query = select(func.count()).select_from(base.subquery())
    total = (await session.execute(count_query)).scalar() or 0

    offset = (page - 1) * page_size
    query = base.order_by(ArgusAgent.created_at.desc()).offset(offset).limit(page_size)
    result = await session.execute(query)
    rows = result.all()

    items = [
        ServerResponse(
            hostname=agent.hostname,
            ip_address=agent.ip_address,
            version=agent.version,
            os_version=agent.os_version,
            arch=agent.arch,
            core_count=agent.core_count,
            total_memory=agent.total_memory,
            cpu_usage=agent.cpu_usage,
            memory_usage=agent.memory_usage,
            disk_swap_percent=agent.disk_swap_percent,
            gpu_count=agent.gpu_count,
            gpu_usage=agent.gpu_usage,
            gpu_memory_usage=agent.gpu_memory_usage,
            gpu_memory_total=agent.gpu_memory_total,
            gpu_name=agent.gpu_name,
            status=agent.status,
            last_heartbeat_seconds=hb_seconds,
            created_at=agent.created_at,
            updated_at=agent.updated_at,
        )
        for agent, hb_seconds in rows
    ]

    return PaginatedServerResponse(items=items, total=total, page=page, page_size=page_size)


async def get_agent_by_hostname(session: AsyncSession, hostname: str) -> ArgusAgent | None:
    """hostname 으로 에이전트 조회. ORM 객체 또는 None."""
    result = await session.execute(select(ArgusAgent).where(ArgusAgent.hostname == hostname))
    return result.scalar_one_or_none()


async def register_servers(session: AsyncSession, hostnames: list[str]) -> RegisterResponse:
    """status 를 UNREGISTERED → REGISTERED 로 변경해 서버를 등록한다."""
    stmt = (
        update(ArgusAgent)
        .where(ArgusAgent.hostname.in_(hostnames))
        .where(ArgusAgent.status == "UNREGISTERED")
        .values(status="REGISTERED")
    )
    result = await session.execute(stmt)
    await session.commit()
    return RegisterResponse(updated=result.rowcount)


async def unregister_servers(session: AsyncSession, hostnames: list[str]) -> UnregisterResponse:
    """status 를 REGISTERED → UNREGISTERED 로 변경해 서버를 등록 해제한다."""
    stmt = (
        update(ArgusAgent)
        .where(ArgusAgent.hostname.in_(hostnames))
        .where(ArgusAgent.status == "REGISTERED")
        .values(status="UNREGISTERED")
    )
    result = await session.execute(stmt)
    await session.commit()
    return UnregisterResponse(updated=result.rowcount)


# ---------------------------------------------------------------------------
# 워커 배포(servicemgr) — 순수 헬퍼 (단위 테스트 대상)
# ---------------------------------------------------------------------------


def next_worker_slots(existing_names: list[str], count: int) -> list[str]:
    """기존 워커 unit 이름에서 다음 슬롯 번호 ``count`` 개를 발급한다(항상 max+1 부터)."""
    used: list[int] = []
    for name in existing_names:
        m = _WORKER_RE.match(name)
        if m:
            used.append(int(m.group(1)))
    start = (max(used) + 1) if used else 1
    return [f"{WORKER_NAME_PREFIX}{start + i}" for i in range(count)]


def default_worker_env(
    db_url: str | None = None, os_endpoint: str | None = None
) -> dict[str, str]:
    """배포 워커에 주입하는 기본 환경변수(설정에서 채움).

    원격/분리 워커가 라우팅 가능한 주소로 DB·오브젝트 스토리지에 접근하도록 연결정보를 주입한다.

    - ``db_url``: 주면 ARGUS_DB_URL 을 강제(미지정 시 서버 설정 기반 URL).
    - ``os_endpoint``: 주면 MinIO 엔드포인트(ARGUS_OS_ENDPOINT)를 강제. 미지정 시 서버 설정값
      (``settings.os_endpoint``)을 쓰는데, 그것이 localhost 면 원격 워커에서 도달 못 하므로
      bridge 네트워크 배포 시에는 라우팅 가능한 주소를 넘겨야 한다.
    """
    from app.core.database import _build_database_url

    return {
        "ARGUS_DB_URL": db_url or _build_database_url(),
        "ARGUS_INGESTION_LOCAL_WORKER_ENABLED": "true",
        "ARGUS_EMBEDDING_SERVER_URL": settings.embedding_server_url,
        "ARGUS_EMBEDDING_MODEL": settings.embedding_model,
        # 오브젝트 스토리지(MinIO/S3) — 워커가 원본 문서를 읽으려면 필수.
        "ARGUS_OS_ENDPOINT": os_endpoint or settings.os_endpoint,
        "ARGUS_OS_ACCESS_KEY": settings.os_access_key,
        "ARGUS_OS_SECRET_KEY": settings.os_secret_key,
        "ARGUS_OS_BUCKET": settings.os_bucket,
        "ARGUS_OS_USE_SSL": "true" if settings.os_use_ssl else "false",
    }


def build_worker_spec(name: str, req: DeployWorkerRequest) -> dict:
    """DeployWorkerRequest + 슬롯 이름 → 에이전트 servicemgr ServiceSpec payload(dict)."""
    # 슬롯별 로그 파일(예: argus-rag-worker-1.log) — 한 호스트 다중 워커의 로그 파일 충돌 방지.
    env = {**default_worker_env(), "ARGUS_LOG_FILENAME": f"{name}.log",
           "ARGUS_WORKER_RUNTIME": "systemd", **(req.environment or {})}
    return {
        "name": name,
        "description": f"Argus RAG Studio ingestion worker ({name})",
        "exec_start": f"{req.python_path} -m app.worker_main",
        "working_directory": req.working_directory,
        "user": req.user,
        "environment": env,
        "restart": "on-failure",
        "restart_sec": 5,
        "limit_nofile": 65536,
        "kind": "worker",
        "version": req.version,
        "enable": True,
        "start": True,
    }


# ---------------------------------------------------------------------------
# Docker 컨테이너 배포 — kind 카탈로그 + spec 빌더 (순수, 단위 테스트 대상)
# ---------------------------------------------------------------------------

# kind -> 이미지 베이스/포트/포트 env 키/모델 볼륨/설정 키/URL 접미사 +
#         gpu_variant: {arch: 변형} (빈 dict 면 GPU 미지원).
CONTAINER_KINDS: dict[str, dict] = {
    "worker": {
        "image": "argus-rag-studio-backend", "port": None, "gpu_variant": {},
        "port_env": None, "volumes": [], "setting": None, "suffix": "",
    },
    # VLM(비전 LLM) — 이미지 분류/내용 주입용 OpenAI 호환 서버(vLLM). 업스트림 이미지를
    # 레지스트리에 미러링해 사용(에어갭). 모델은 command 로 지정(기본 Qwen2-VL-7B) —
    # 배포 환경변수 VLLM_ARGS 로 서빙 인자 전체를 교체할 수 있다(모델/파라미터 변경).
    # 배포 후 wire_settings 가 image_classification.server_url 을 새 서버로 연결한다.
    # 주의: served-model-name 을 바꾸면 image_classification.model 설정도 맞춰야 한다.
    "vlm": {
        "image": "vllm/vllm-openai", "port": 8000, "gpu_variant": {},
        "port_env": None,
        "volumes": ["argus-rag-vlm-models:/models"],
        "env": {"HF_HOME": "/models"},  # 온라인 다운로드도 같은 볼륨에 캐시
        "ipc": "host",  # vLLM 공유메모리 요구(기본 shm 64MB 로는 멀티모달 페이로드에 부족)
        "setting": "image_classification.server_url", "suffix": "/v1",
    },
    "embedding": {
        "image": "argus-rag-studio-embedding-server", "port": 8080,
        "gpu_variant": {"amd64": "gpu", "arm64": "gpu-torch"},
        "port_env": "EMBED_PORT", "volumes": ["argus-rag-embed-models:/models"],
        "env": {"EMBED_CACHE_DIR": "/models"},  # 사전 설치(hf-cache)·온라인 캐시 공용 볼륨
        "setting": "embedding.server_url", "suffix": "/v1",
    },
    "reranker": {
        "image": "argus-rag-studio-reranker-server", "port": 8081,
        "gpu_variant": {"amd64": "gpu", "arm64": "gpu-torch"},
        "port_env": "RERANK_PORT", "volumes": ["argus-rag-rerank-models:/models"],
        "env": {"RERANK_CACHE_DIR": "/models"},  # 사전 설치(hf-cache)·온라인 캐시 공용 볼륨
        "setting": "rerank.server_url", "suffix": "/rerank",
    },
    "detection": {
        "image": "argus-rag-studio-detection-server", "port": 8082,
        "gpu_variant": {"amd64": "gpu", "arm64": "gpu"},
        "port_env": "DETECT_PORT", "volumes": ["argus-rag-detect-models:/models"],
        "setting": "detection.server_url", "suffix": "",
    },
    "hwp_render": {
        "image": "argus-rag-studio-hwp-render-server", "port": 8085, "gpu_variant": {},
        "port_env": "HWP_RENDER_PORT", "volumes": [], "setting": "hwp_render.url", "suffix": "",
    },
}


class VariantError(Exception):
    """변형 선택 불가(미지원 kind/arch, GPU 없음 등). 라우터가 409 로 변환."""


def resolve_variant(kind: str, req, *, arch: str | None, gpu_count: int | None) -> str:
    """배포 변형을 결정한다. 반환 "" = cpu/단일, 그 외 = 태그 접미사(gpu|gpu-torch).

    req.variant: auto(기본) | cpu | gpu | gpu-torch.
    req.gpus(디바이스 선택)는 auto 판단의 보조 신호(하위호환).
    """
    cat = CONTAINER_KINDS[kind]
    gpu_map: dict = cat.get("gpu_variant", {})
    v = (getattr(req, "variant", None) or "auto").lower()

    if v == "cpu":
        return ""
    if v in ("gpu", "gpu-torch"):
        if not gpu_map:
            raise VariantError(f"{kind} 는 GPU 변형을 지원하지 않습니다")
        if v not in set(gpu_map.values()):
            raise VariantError(
                f"{kind} 는 {v} 변형이 없습니다 (가능: {sorted(set(gpu_map.values()))})"
            )
        return v

    # auto
    want_gpu = bool(getattr(req, "gpus", None)) or (bool(gpu_count) and bool(gpu_map))
    if not want_gpu or not gpu_map:
        return ""
    chosen = gpu_map.get(arch or "amd64")
    if not chosen:
        raise VariantError(f"{kind} 는 {arch or 'amd64'} 에서 GPU 변형이 없습니다")
    return chosen


def container_prefix(kind: str) -> str:
    """kind -> 컨테이너 이름 접두사 (예: hwp_render -> 'argus-rag-hwp-render-')."""
    return f"argus-rag-{kind.replace('_', '-')}-"


def next_slots(prefix: str, existing_names: list[str], count: int) -> list[str]:
    """주어진 접두사 기준 다음 슬롯 번호 ``count`` 개를 발급(항상 max+1 부터)."""
    pat = re.compile(rf"^{re.escape(prefix)}(\d+)$")
    used = [int(m.group(1)) for n in existing_names if (m := pat.match(n))]
    start = (max(used) + 1) if used else 1
    return [f"{prefix}{start + i}" for i in range(count)]


def image_for(kind: str, variant: str = "", override: str | None = None) -> str:
    """kind/variant/override + 레지스트리/태그 설정으로 최종 이미지 레퍼런스 산출.

    variant 가 있으면 태그에 ``-{variant}`` 접미사를 붙인다(예: 0.4.2-gpu-torch).
    """
    if override:
        return override
    base = CONTAINER_KINDS[kind]["image"]
    registry = settings.deploy_image_registry.strip().rstrip("/")
    tag = settings.deploy_image_tag.strip() or "latest"
    if variant:
        tag = f"{tag}-{variant}"
    ref = f"{base}:{tag}"
    return f"{registry}/{ref}" if registry else ref


def build_container_spec(
    kind: str, name: str, req, *, arch: str | None = None, gpu_count: int | None = None
) -> dict:
    """kind + 슬롯 이름 + DeployContainerRequest → 에이전트 ContainerSpec payload(dict).

    호스트 arch/gpu_count 로 변형(cpu/gpu/gpu-torch)을 결정해 이미지 태그와 --gpus 를 맞춘다.
    """
    if kind not in CONTAINER_KINDS:
        raise ValueError(f"unknown kind: {kind}")
    cat = CONTAINER_KINDS[kind]

    variant = resolve_variant(kind, req, arch=arch, gpu_count=gpu_count)

    env: dict[str, str] = {}
    env.update(cat.get("env") or {})
    if cat["port_env"] and cat["port"]:
        env[cat["port_env"]] = str(cat["port"])
    if kind == "worker":
        env.update(
            default_worker_env(getattr(req, "db_url", None), getattr(req, "os_endpoint", None))
        )
        # 슬롯별 로그 파일 — 컨테이너 내부에서도 슬롯명으로 구분(docker logs 와 별개로 파일 식별).
        env["ARGUS_LOG_FILENAME"] = f"{name}.log"
        env["ARGUS_WORKER_RUNTIME"] = "docker"  # 잡 모니터링 워커 탭의 배포 방식 표시
    env.update(req.environment or {})

    # 호스트 포트 오버라이드(기본 포트 점유 시) — 컨테이너 내부 포트는 kind 기본 유지.
    host_port = getattr(req, "host_port", None) or cat["port"]
    ports = [f"{host_port}:{cat['port']}"] if cat["port"] else []
    # 변형이 GPU 면 --gpus 기본 all (req.gpus 명시 시 그것 우선).
    gpus = req.gpus or ("all" if variant else None)
    # worker 는 공용 이미지를 worker_main 으로 실행(기본 CMD=uvicorn app.main 대신) →
    # 진짜 standalone 워커(포트 바인딩 없음, :4700 충돌 없음, mode=standalone).
    command = (
        ["python", "-m", "app.worker_main"] if kind == "worker"
        else list(cat.get("command") or [])
    )
    # 임베딩/리랭커 — 모델 준비 단계(prepare_kind_models)가 스태시한 선택 모델을
    # 서버 env(EMBED_*/RERANK_*)로 변환. 미선택이면 서버 자체 설정의 기본 세트로 뜬다.
    if kind in ("embedding", "reranker"):
        prefix = "EMBED_" if kind == "embedding" else "RERANK_"
        for k in ("MODEL_NAMES", "DEFAULT_MODEL", "ALLOW_ONLINE_MODEL"):
            env.pop(k, None)  # 오케스트레이션 입력 — 컨테이너에 전달 안 함
        repos = env.pop("MODELS_REPOS", None)
        default_repo = env.pop("DEFAULT_REPO", None)
        offline = env.pop("MODELS_OFFLINE", None)
        if repos:
            env[f"{prefix}MODELS"] = repos            # 서빙 허용 목록(HF repo CSV)
            env[f"{prefix}DEFAULT_MODEL"] = default_repo or repos.split(",")[0]
        if offline:
            # 전부 볼륨에 설치됨 — 외부(HF) 접근을 차단해 에어갭에서 무음 행을 방지.
            env["HF_HUB_OFFLINE"] = "1"
            env["TRANSFORMERS_OFFLINE"] = "1"
    # vlm 서빙 command 구성 — 우선순위: VLLM_ARGS(고급, 전체 직접 지정) >
    # 로컬 경로(모델 준비 단계가 볼륨에 설치 — 오프라인 강제) > 카탈로그 모델(온라인 HF).
    if kind == "vlm":
        env.pop("ALLOW_ONLINE_MODEL", None)  # 오케스트레이션 플래그 — 컨테이너에 전달 안 함
        local_path = env.pop("VLM_LOCAL_PATH", None)
        if env.get("VLLM_ARGS"):
            import shlex

            command = shlex.split(env.pop("VLLM_ARGS"))
        else:
            # 모델 준비 단계(model_prep, 레지스트리 DB 조회)가 해석 결과를 env 에 스태시.
            # 준비 단계 없이 직접 빌드된 경우만 시드 폴백으로 해석한다(동기 문맥이라 DB 불가).
            m_name = env.pop("VLM_MODEL", None)
            m_repo = env.pop("VLM_REPO", None)
            m_len = env.pop("VLM_MAX_LEN", None)
            if not (m_name and m_repo and m_len):
                from app.servermgr.vlm_models import resolve_vlm_model

                m = resolve_vlm_model(m_name)  # 미지정=기본 모델
                if m is None:
                    raise ValueError("알 수 없는 VLM 모델입니다(모델 관리에 등록된 name 또는 repo 로 지정).")
                m_name, m_repo, m_len = m["name"], m["repo"], m["max_len"]
            command = [local_path or m_repo, "--served-model-name", m_name,
                       "--max-model-len", str(m_len)]
            if local_path:
                # 로컬 전개본 서빙 — 외부(HF) 접근을 강제 차단해 에어갭에서 무음 행을 방지.
                env["HF_HUB_OFFLINE"] = "1"
                env["TRANSFORMERS_OFFLINE"] = "1"

    # vlm × arm64 — 공식 vllm/vllm-openai 는 x86 전용이라 NGC 이미지로 자동 전환.
    # NGC 는 entrypoint 가 nvidia_entrypoint.sh(커맨드 전체 필요)라 "vllm serve" 를
    # 앞에 붙인다(VLLM_ARGS 로 전체 지정한 경우는 이미 포함돼 있어 건너뜀).
    image_override = req.image
    if kind == "vlm" and (arch or "amd64") == "arm64":
        if not image_override:
            image_override = settings.deploy_vlm_image_arm64
        if command and command[0] != "vllm":
            command = ["vllm", "serve"] + command

    return {
        "name": name,
        "image": image_for(kind, variant, image_override),
        "command": command,
        "environment": env,
        "ports": ports,
        "volumes": list(cat["volumes"]),
        "gpus": gpus,
        "ipc": cat.get("ipc"),
        "restart": "unless-stopped",
        "network": getattr(req, "network", None),
        "extra_hosts": list(getattr(req, "extra_hosts", []) or []),
        "labels": {"argus.variant": variant or "cpu"},
        "kind": kind,
        "version": req.version,
        "pull": True,
        "start": True,
    }


def vlm_setting_injection(env: dict | None) -> dict[str, str]:
    """vlm 배포 시 추가 주입 — 선택 모델의 served-model-name 을 image_classification.model 로.

    VLLM_ARGS(고급, 인자 직접 지정) 사용 시에는 모델명을 파싱할 수 없어 주입하지 않는다
    (이 경우 image_classification.model 은 사용자가 설정 화면에서 맞춘다)."""
    env = env or {}
    if env.get("VLLM_ARGS"):
        return {}
    # 모델 준비 단계가 VLM_MODEL 을 레지스트리 name 으로 정규화해 둠 — 그대로 주입.
    if env.get("VLM_MODEL"):
        return {"image_classification.model": env["VLM_MODEL"]}
    from app.servermgr.vlm_models import resolve_vlm_model

    m = resolve_vlm_model(None)  # 미지정=기본 모델(시드 폴백)
    return {"image_classification.model": m["name"]} if m else {}


def setting_injection(kind: str, ip: str, host_port: int | None = None) -> tuple[str, str] | None:
    """배포 후 RAG Studio 에 주입할 설정 (key, value). 해당 없으면 None."""
    cat = CONTAINER_KINDS.get(kind)
    if not cat or not cat["setting"]:
        return None
    return cat["setting"], f"http://{ip}:{host_port or cat['port']}{cat['suffix']}"
