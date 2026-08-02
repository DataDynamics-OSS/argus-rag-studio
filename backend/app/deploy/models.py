# SPDX-License-Identifier: Apache-2.0
"""배포 도메인 모델 — 방식(docker/systemd/k8s) 무관. 설계 design/deploy-strategy.md §2."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class DeployError(Exception):
    """배포 실패 — code 로 HTTP 매핑(404 미존재 / 409 권한·상태 / 502 통신 / 400 잘못된 요청)."""

    def __init__(self, message: str, code: int = 400) -> None:
        super().__init__(message)
        self.code = code


class ServiceKind(StrEnum):
    """배포 가능한 워크로드 종류 (= servermgr.CONTAINER_KINDS 키)."""

    worker = "worker"
    embedding = "embedding"
    reranker = "reranker"
    detection = "detection"
    hwp_render = "hwp_render"
    vlm = "vlm"


class Runtime(StrEnum):
    docker = "docker"
    systemd = "systemd"
    k8s = "k8s"


class Privilege(StrEnum):
    """전략이 요구하는 권한 등급 (UI 안내·백엔드 가드용). design/deployment-privileges.md."""

    host_docker = "host_docker"      # 호스트 Docker 데몬 접근(root/도커그룹)
    host_user = "host_user"          # rootless(podman+CDI) — 호스트 root 불필요
    host_root = "host_root"          # systemd 등 호스트 root 필수
    cluster_rbac = "cluster_rbac"    # k8s 네임스페이스 RBAC


@dataclass
class DeploySpec:
    """무엇을 배포하나 — 방식 무관 의도."""

    kind: ServiceKind
    replicas: int = 1
    variant: str = "auto"            # auto|cpu|gpu|gpu-torch (target arch 로 해석)
    image: str | None = None         # override (없으면 image_for 로 산출)
    version: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    gpu: bool = False                # GPU 요청 (전략별 --gpus / nvidia.com/gpu 로 번역)
    wire_settings: bool = True       # 배포 후 embedding.server_url 등 자동 주입
    # docker/host 네트워킹 (전략이 무시 가능)
    network: str | None = None
    extra_hosts: list[str] = field(default_factory=list)
    db_url: str | None = None
    os_endpoint: str | None = None
    # 호스트 포트 오버라이드(docker 전용) — 기본 포트가 호스트에서 점유된 경우
    # (예: DGX 8080=node). 컨테이너 내부 포트는 그대로, 매핑·설정 주입만 바뀐다.
    host_port: int | None = None


@dataclass
class DeployTarget:
    """어디에 배포하나."""

    type: str                                  # "agent_host" | "k8s"
    # agent_host
    hostname: str | None = None
    method: str | None = None                  # "docker" | "systemd"
    # k8s
    cluster_id: str | None = None
    namespace: str | None = None


@dataclass
class ManagedInstance:
    """물리 단위 (container / pod / unit)."""

    id: str
    state: str
    node: str | None = None
    pid: int | None = None  # systemd MainPID — 워커 레지스트리 정밀 매칭 키


@dataclass
class ManagedService:
    """논리 단위 — list/status/deploy 반환. 복제 모델 차이를 흡수."""

    name: str
    kind: str
    runtime: str
    desired_replicas: int = 1
    ready_replicas: int = 0
    state: str = "unknown"                      # running|partial|stopped|pending|failed|unknown
    image: str | None = None
    version: str | None = None
    endpoint: str | None = None                # 서버형 접속 URL (설정 주입·표시)
    started_at: str | None = None              # 가동 시작 시각(ISO) — uptime 표시용
    exit_code: int | None = None               # 비정상 종료 코드(있으면)
    message: str | None = None                 # 상태/에러 메시지(크래시 사유 등)
    restart_count: int | None = None           # 재시작 횟수(크래시 루프)
    health: str | None = None                  # healthcheck 상태(있으면)
    cpu_percent: float | None = None           # 컨테이너 CPU%(docker stats)
    mem_percent: float | None = None           # 컨테이너 MEM%(docker stats)
    command: list[str] = field(default_factory=list)  # 컨테이너 Cmd(서빙 인자 — vlm 모델명 근거)
    # heartbeat /stats 요약(model·models_loaded·device·gpu·uptime 등) — overview 가 병합.
    stats: dict | None = None
    # worker 전용 — 워커 레지스트리(argus_workers) 교차참조(컨테이너 id ↔ 워커 hostname).
    worker_alive: bool | None = None
    worker_status: str | None = None           # starting|idle|busy|stopped
    worker_current_job: str | None = None
    worker_processed_total: int | None = None
    worker_mode: str | None = None             # standalone|in_process
    instances: list[ManagedInstance] = field(default_factory=list)
