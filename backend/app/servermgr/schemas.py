# SPDX-License-Identifier: Apache-2.0
"""서버 관리 스키마."""

from datetime import datetime

from pydantic import BaseModel, Field


class ServerResponse(BaseModel):
    """클라이언트에 반환하는 서버(에이전트) 정보."""

    hostname: str
    ip_address: str
    version: str | None = None
    os_version: str | None = None
    arch: str | None = None
    core_count: int | None = None
    total_memory: int | None = None
    cpu_usage: float | None = None
    memory_usage: float | None = None
    disk_swap_percent: float | None = None
    gpu_count: int | None = None
    gpu_usage: float | None = None
    gpu_memory_usage: float | None = None
    gpu_memory_total: int | None = None
    gpu_name: str | None = None
    status: str
    last_heartbeat_seconds: int | None = None
    created_at: datetime
    updated_at: datetime


class PaginatedServerResponse(BaseModel):
    """서버 목록(페이지네이션)."""

    items: list[ServerResponse]
    total: int
    page: int
    page_size: int


class RegisterRequest(BaseModel):
    """hostname 기준 서버 등록 요청."""

    hostnames: list[str]


class RegisterResponse(BaseModel):
    updated: int


class UnregisterRequest(BaseModel):
    """hostname 기준 서버 등록 해제 요청."""

    hostnames: list[str]


class UnregisterResponse(BaseModel):
    updated: int


# ---------------------------------------------------------------------------
# 워커 배포(servicemgr)
# ---------------------------------------------------------------------------


class ManagedServiceResponse(BaseModel):
    """에이전트 servicemgr 가 관리하는 서비스 1개(systemd unit)."""

    name: str
    kind: str | None = None
    version: str | None = None
    active_state: str | None = None
    sub_state: str | None = None
    enabled: bool | None = None
    pid: int | None = None


class DeployWorkerRequest(BaseModel):
    """워커 배포 요청 — 에이전트 servicemgr ServiceSpec 으로 변환된다."""

    replicas: int = Field(1, ge=1, le=32, description="이 호스트에 띄울 워커 수")
    working_directory: str = Field(..., description="RAG Studio backend 경로")
    python_path: str = Field("python", description="venv python 실행 파일 경로")
    user: str | None = None
    version: str | None = None
    environment: dict[str, str] = Field(
        default_factory=dict, description="추가 env(기본 env에 병합)"
    )


class DeployWorkerResponse(BaseModel):
    services: list[ManagedServiceResponse]
    message: str


# ---------------------------------------------------------------------------
# Docker 컨테이너 배포 (에이전트 containermgr)
# ---------------------------------------------------------------------------


class ContainerInfo(BaseModel):
    """에이전트 containermgr 가 관리하는 컨테이너 1개."""

    name: str
    image: str | None = None
    state: str | None = None
    kind: str | None = None
    version: str | None = None
    id: str | None = None


class DeployContainerRequest(BaseModel):
    """컨테이너 배포 요청 — kind 별 ContainerSpec 으로 변환된다."""

    kind: str = Field(..., description="worker|embedding|reranker|detection|hwp_render")
    replicas: int = Field(1, ge=1, le=32, description="worker 만 N개, 서버형은 1로 강제")
    image: str | None = Field(None, description="이미지 override(미지정 시 레지스트리/태그 기본값)")
    variant: str = Field(
        "auto", description="이미지 변형 auto|cpu|gpu|gpu-torch (auto=호스트 arch·GPU로 결정)"
    )
    gpus: str | None = Field(None, description="--gpus 값('all'|'0,1'); None=CPU")
    force: bool = Field(False, description="GPU 미탑재 호스트에도 GPU 변형 강제(가드 우회)")
    version: str | None = None
    environment: dict[str, str] = Field(default_factory=dict, description="추가 env(병합)")
    wire_settings: bool = Field(True, description="배포 후 RAG Studio 설정(server_url 등) 자동 주입")
    # 네트워킹 — 원격 호스트의 컨테이너가 RAG Studio DB/서비스에 도달하도록 제어.
    network: str | None = Field(None, description="--network (bridge 기본 | host | <custom>)")
    extra_hosts: list[str] = Field(
        default_factory=list, description="--add-host 'name:ip' 목록"
    )
    db_url: str | None = Field(
        None,
        description="worker 컨테이너의 ARGUS_DB_URL override(미지정 시 서버 설정값). "
        "bridge 네트워크면 localhost 가 아닌 라우팅 가능한 주소를 넣어야 한다.",
    )
    os_endpoint: str | None = Field(
        None,
        description="worker 컨테이너의 MinIO 엔드포인트(ARGUS_OS_ENDPOINT) override(미지정 시 서버 설정값). "
        "원격/bridge 네트워크면 localhost 가 아닌 라우팅 가능한 주소를 넣어야 원본 문서를 읽는다.",
    )
    host_port: int | None = Field(
        None, ge=1, le=65535,
        description="호스트 포트 오버라이드 — 기본 포트가 호스트에서 점유된 경우"
        "(컨테이너 내부 포트는 kind 기본 유지, 매핑·설정 주입만 변경)",
    )


class DeployContainerResponse(BaseModel):
    containers: list[ContainerInfo]
    applied_settings: dict[str, str] = Field(default_factory=dict)
    message: str
