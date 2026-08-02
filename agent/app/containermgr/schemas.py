"""Container (Docker/Podman) management schemas."""

from pydantic import BaseModel, Field

# containermgr 가 관리하는 컨테이너 이름 접두사 — 임의 컨테이너 조작을 막는 안전장치.
MANAGED_PREFIX = "argus-rag-"


class OperationResult(BaseModel):
    """Generic success/failure result."""

    success: bool
    message: str


class ContainerSpec(BaseModel):
    """단일 컨테이너 실행 정의. name 은 MANAGED_PREFIX 로 시작해야 한다."""

    name: str = Field(..., description="Container name, e.g. 'argus-rag-embedding-1'")
    image: str = Field(..., description="Image reference, e.g. 'argus/embedding-server:latest'")
    command: list[str] = Field(default_factory=list, description="Override CMD (args)")
    environment: dict[str, str] = Field(default_factory=dict, description="-e KEY=VALUE")
    ports: list[str] = Field(default_factory=list, description="'host:container' 매핑 목록")
    volumes: list[str] = Field(
        default_factory=list, description="'name:/path' 또는 '/host:/cont[:ro]' 목록"
    )
    gpus: str | None = Field(None, description="--gpus 값 ('all' | '0,1' | None=미사용)")
    ipc: str | None = Field(None, description="--ipc (예: 'host' — vLLM 등 공유메모리 요구 워크로드)")
    restart: str = Field("unless-stopped", description="--restart 정책")
    network: str | None = Field(None, description="--network (bridge|host|<custom>)")
    extra_hosts: list[str] = Field(
        default_factory=list, description="--add-host 'name:ip' (예: studio-db:192.0.2.10)"
    )
    pull: bool = Field(True, description="실행 전 이미지 pull 여부")
    labels: dict[str, str] = Field(default_factory=dict, description="추가 --label")
    kind: str = Field("worker", description="worker|embedding|reranker|detection|hwp_render")
    version: str | None = Field(None, description="Deployed version, for inventory")
    start: bool = Field(True, description="생성 후 즉시 시작(run) / False 면 create 만")


class ContainerStatus(BaseModel):
    """`inspect` 파싱 결과 + 관리 메타데이터."""

    name: str
    exists: bool = Field(description="컨테이너가 존재하는가")
    id: str | None = None
    image: str | None = None
    state: str | None = Field(None, description="running|exited|created|paused|...")
    exit_code: int | None = None
    started_at: str | None = None
    kind: str | None = None
    version: str | None = None
    restart_count: int | None = None      # 재시작 횟수(크래시 루프 감지)
    ports: list[str] = Field(default_factory=list)  # "host:container" 매핑(호스트 노출분만)
    command: list[str] = Field(default_factory=list)  # Config.Cmd(서빙 인자 — vlm 모델명 파싱 등)
    health: str | None = None             # healthcheck 상태(healthy|unhealthy|...), 없으면 None
    cpu_percent: float | None = None      # docker stats CPU%
    mem_percent: float | None = None      # docker stats MEM%
    message: str = ""


class ContainerLogs(BaseModel):
    """컨테이너 로그 tail 결과."""

    name: str
    logs: str
