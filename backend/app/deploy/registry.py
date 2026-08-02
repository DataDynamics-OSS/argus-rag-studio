# SPDX-License-Identifier: Apache-2.0
"""전략 팩토리 — DeployTarget 으로 DeployStrategy 선택. 설계 design/deploy-strategy.md §7."""

from __future__ import annotations

from app.deploy.docker_strategy import DockerStrategy
from app.deploy.k8s_strategy import K8sStrategy
from app.deploy.models import DeployError, DeployTarget
from app.deploy.strategy import DeployStrategy
from app.deploy.systemd_strategy import SystemdStrategy


def get_strategy(target: DeployTarget) -> DeployStrategy:
    """대상 종류로 전략을 고른다. 새 방식 = 전략 1개 + 분기 1줄."""
    if target.type == "k8s":
        return K8sStrategy()
    if target.type == "agent_host":
        if target.method == "systemd":
            return SystemdStrategy()
        return DockerStrategy()  # 기본 docker
    raise DeployError(f"unknown target type: {target.type}", code=400)
