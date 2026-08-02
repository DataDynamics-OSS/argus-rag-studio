# SPDX-License-Identifier: Apache-2.0
"""DeployStrategy 추상 인터페이스. 설계 design/deploy-strategy.md §3.

모든 전략은 동일 시그니처를 구현하고, DeploySpec → 네이티브(컨테이너/유닛/매니페스트) 변환만 다르다.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.deploy.models import (
    DeploySpec,
    DeployTarget,
    ManagedService,
    Privilege,
    ServiceKind,
)


class DeployStrategy(ABC):
    """배포 방식 1개를 캡슐화."""

    runtime: str  # "docker" | "systemd" | "k8s"

    @abstractmethod
    def required_privilege(self) -> Privilege:
        """이 전략이 요구하는 권한 등급 (UI 안내·가드)."""

    @abstractmethod
    def supports(self, kind: ServiceKind) -> bool:
        """해당 kind 를 이 전략으로 배포 가능한가."""

    @abstractmethod
    async def deploy(self, spec: DeploySpec, target: DeployTarget) -> ManagedService: ...

    @abstractmethod
    async def list(self, target: DeployTarget) -> list[ManagedService]: ...

    @abstractmethod
    async def status(self, target: DeployTarget, name: str) -> ManagedService: ...

    @abstractmethod
    async def scale(self, target: DeployTarget, name: str, replicas: int) -> ManagedService: ...

    @abstractmethod
    async def action(self, target: DeployTarget, name: str, action: str) -> ManagedService:
        """action: start | stop | restart."""

    @abstractmethod
    async def remove(self, target: DeployTarget, name: str) -> None: ...

    @abstractmethod
    async def logs(
        self, target: DeployTarget, name: str, *, tail: int = 200, instance: str | None = None
    ) -> str: ...
