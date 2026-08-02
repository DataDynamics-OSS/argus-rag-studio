# SPDX-License-Identifier: Apache-2.0
"""K8s 클러스터 등록 — DeployTarget.cluster_id 가 참조하는 접속정보(SA 토큰/CA)."""

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, func

from app.core.database import Base


class K8sCluster(Base):
    """등록된 Kubernetes 클러스터. SA bearer 토큰 + API 서버 + CA(선택)로 접속한다."""

    __tablename__ = "argus_k8s_clusters"

    id = Column(Integer, primary_key=True)
    cluster_id = Column(String(64), nullable=False, unique=True)  # DeployTarget.cluster_id
    name = Column(String(200), nullable=False)
    api_server = Column(String(500), nullable=False)              # https://host:6443
    token = Column(Text)                                          # ServiceAccount bearer
    ca_cert = Column(Text)                                        # PEM (선택)
    verify_ssl = Column(Boolean, nullable=False, default=True)
    default_namespace = Column(String(128), nullable=False, default="default")
    default_arch = Column(String(16), nullable=False, default="amd64")  # 변형 결정용 노드풀 arch
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
