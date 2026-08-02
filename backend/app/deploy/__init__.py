# SPDX-License-Identifier: Apache-2.0
"""배포 추상화 — 방식 무관 DeploySpec/DeployTarget + 전략(docker/systemd/k8s).

설계: design/deploy-strategy.md. 기존 servermgr 의 카탈로그/변형/이미지/설정주입 헬퍼를
재사용하며, 배포 오케스트레이션을 전략으로 일원화한다.
"""
