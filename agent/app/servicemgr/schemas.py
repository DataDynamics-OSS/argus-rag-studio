"""Service (systemd unit) management schemas."""

from pydantic import BaseModel, Field

# servicemgr가 관리하는 unit 접두사 — 임의 시스템 서비스 조작을 막는 안전장치.
# systemd 배포 대상은 worker 뿐이라 worker 로 좁힌다(에이전트 자신 등 제외).
MANAGED_PREFIX = "argus-rag-worker-"


class OperationResult(BaseModel):
    """Generic success/failure result."""

    success: bool
    message: str


class ServiceSpec(BaseModel):
    """systemd unit 정의. name 은 MANAGED_PREFIX 로 시작해야 한다."""

    name: str = Field(..., description="Unit name without .service, e.g. 'argus-rag-worker-1'")
    description: str = Field("", description="Unit Description=")
    exec_start: str = Field(..., description="ExecStart= command line")
    working_directory: str | None = Field(None, description="WorkingDirectory=")
    user: str | None = Field(None, description="User= to run as")
    group: str | None = Field(None, description="Group=")
    environment: dict[str, str] = Field(default_factory=dict, description="Environment= entries")
    restart: str = Field("on-failure", description="Restart= policy")
    restart_sec: int = Field(5, ge=0, description="RestartSec= seconds")
    limit_nofile: int | None = Field(None, description="LimitNOFILE=")
    after: list[str] = Field(
        default_factory=lambda: ["network.target"], description="After= units"
    )
    wanted_by: str = Field("multi-user.target", description="WantedBy= for [Install]")
    # 메타데이터(heartbeat 인벤토리 표기용) — unit X-Argus- 주석으로 보존
    kind: str = Field("worker", description="Logical kind: worker|embedding|reranker|vllm")
    version: str | None = Field(None, description="Deployed app version, for inventory")
    enable: bool = Field(True, description="Enable on boot after create")
    start: bool = Field(True, description="Start immediately after create")


class EnabledRequest(BaseModel):
    """Enable/disable a unit on boot."""

    enabled: bool = Field(..., description="True=enable on boot, False=disable")


class ServiceStatus(BaseModel):
    """`systemctl show` 파싱 결과 + 관리 메타데이터."""

    name: str
    exists: bool = Field(description="unit 파일이 존재하는가")
    load_state: str | None = Field(None, description="loaded|not-found|error")
    active_state: str | None = Field(None, description="active|inactive|failed|activating")
    sub_state: str | None = Field(None, description="running|dead|exited|...")
    enabled: bool | None = Field(None, description="부팅 시 자동기동 여부")
    pid: int | None = None
    memory_bytes: int | None = None
    since: str | None = Field(None, description="ActiveEnterTimestamp")
    exit_code: int | None = None
    kind: str | None = None
    version: str | None = None
    message: str = ""
