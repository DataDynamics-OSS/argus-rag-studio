# SPDX-License-Identifier: Apache-2.0
"""K8s 클러스터 등록 CRUD."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session
from app.deploy.cluster_models import K8sCluster
from app.deploy.models import DeployError


async def list_clusters(session: AsyncSession) -> list[K8sCluster]:
    return list((await session.execute(select(K8sCluster).order_by(K8sCluster.created_at))).scalars())


async def get_cluster(session: AsyncSession, cluster_id: str) -> K8sCluster | None:
    return (
        await session.execute(select(K8sCluster).where(K8sCluster.cluster_id == cluster_id))
    ).scalar_one_or_none()


async def require_cluster(cluster_id: str) -> K8sCluster:
    """짧은 세션으로 클러스터 조회 — 전략에서 사용. 미존재 404."""
    async with async_session() as session:
        c = await get_cluster(session, cluster_id)
    if not c:
        raise DeployError(f"클러스터를 찾을 수 없습니다: {cluster_id}", code=404)
    return c


async def upsert_cluster(session: AsyncSession, data: dict) -> K8sCluster:
    existing = await get_cluster(session, data["cluster_id"])
    if existing:
        for k, v in data.items():
            setattr(existing, k, v)
        cluster = existing
    else:
        cluster = K8sCluster(**data)
        session.add(cluster)
    await session.commit()
    await session.refresh(cluster)
    return cluster


async def delete_cluster(session: AsyncSession, cluster_id: str) -> int:
    res = await session.execute(delete(K8sCluster).where(K8sCluster.cluster_id == cluster_id))
    await session.commit()
    return res.rowcount
