# SPDX-License-Identifier: Apache-2.0
"""파이프라인 서비스 — 버전 생성/롤백, diff, 실행용 config 해석.

설정 수정은 append-only: ``update_config`` 가 새 버전을 만들고 ``active_version`` 을 그 버전으로
올린다. ``set_active`` 는 active 포인터만 과거 버전으로 이동(롤백). ``resolve_config`` 는 실행
경로(검색/생성)가 사용할 활성 버전 설정을 돌려준다.
"""

import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.pipelines.models import RagPipeline, RagPipelineVersion
from app.pipelines.schemas import (
    DiffEntry,
    DiffResponse,
    PipelineConfig,
    PipelineCreateRequest,
    PipelineResponse,
    VersionResponse,
)

logger = logging.getLogger(__name__)


async def _version_row(
    session: AsyncSession, pipeline_id: int, version: int
) -> RagPipelineVersion | None:
    return (await session.execute(
        select(RagPipelineVersion).where(
            RagPipelineVersion.pipeline_id == pipeline_id,
            RagPipelineVersion.version == version,
        )
    )).scalars().first()


async def _config_of(session: AsyncSession, pipeline_id: int, version: int) -> PipelineConfig:
    row = await _version_row(session, pipeline_id, version)
    if not row:
        return PipelineConfig()
    return PipelineConfig.model_validate_json(row.config_json)


async def _pipeline_resp(session: AsyncSession, p: RagPipeline) -> PipelineResponse:
    count = (await session.execute(
        select(func.count()).where(RagPipelineVersion.pipeline_id == p.id)
    )).scalar() or 0
    config = await _config_of(session, p.id, p.active_version)
    return PipelineResponse(
        id=p.id, pipeline_id=p.pipeline_id, name=p.name, description=p.description,
        stage=p.stage, active_version=p.active_version, version_count=count, config=config,
        created_by=p.created_by, created_at=p.created_at, updated_at=p.updated_at,
    )


async def create_pipeline(
    session: AsyncSession, req: PipelineCreateRequest, created_by: str | None
) -> PipelineResponse:
    existing = (await session.execute(
        select(RagPipeline).where(RagPipeline.name == req.name)
    )).scalars().first()
    if existing:
        raise ValueError(f"Pipeline '{req.name}' already exists")

    config = req.config or PipelineConfig.from_settings()
    pipeline = RagPipeline(
        pipeline_id=str(uuid.uuid4()), name=req.name, description=req.description,
        stage=req.stage, active_version=1, created_by=created_by,
    )
    session.add(pipeline)
    await session.flush()
    session.add(RagPipelineVersion(
        pipeline_id=pipeline.id, version=1, config_json=config.model_dump_json(),
        note="initial", created_by=created_by,
    ))
    await session.commit()
    await session.refresh(pipeline)
    logger.info("파이프라인 생성: %s (id=%d)", pipeline.name, pipeline.id)
    return await _pipeline_resp(session, pipeline)


async def get_pipeline(session: AsyncSession, pipeline_id: int) -> RagPipeline | None:
    return (await session.execute(
        select(RagPipeline).where(RagPipeline.id == pipeline_id)
    )).scalars().first()


async def list_pipelines(session: AsyncSession) -> list[PipelineResponse]:
    pipelines = (await session.execute(
        select(RagPipeline).order_by(RagPipeline.created_at.desc())
    )).scalars().all()
    return [await _pipeline_resp(session, p) for p in pipelines]


async def get_pipeline_resp(session: AsyncSession, pipeline_id: int) -> PipelineResponse | None:
    p = await get_pipeline(session, pipeline_id)
    return await _pipeline_resp(session, p) if p else None


async def get_pipeline_by_uuid(session: AsyncSession, pipeline_uuid: str) -> RagPipeline | None:
    """외부 노출용 UUID(pipeline_id)로 조회. 내부 PK(id)는 응답에 포함된다."""
    return (await session.execute(
        select(RagPipeline).where(RagPipeline.pipeline_id == pipeline_uuid)
    )).scalars().first()


async def get_pipeline_resp_by_uuid(
    session: AsyncSession, pipeline_uuid: str
) -> PipelineResponse | None:
    p = await get_pipeline_by_uuid(session, pipeline_uuid)
    return await _pipeline_resp(session, p) if p else None


async def update_config(
    session: AsyncSession, pipeline: RagPipeline, config: PipelineConfig, note: str | None,
    created_by: str | None,
) -> PipelineResponse:
    """새 버전을 생성하고 active 로 만든다(append-only)."""
    next_version = ((await session.execute(
        select(func.max(RagPipelineVersion.version)).where(
            RagPipelineVersion.pipeline_id == pipeline.id
        )
    )).scalar() or 0) + 1
    session.add(RagPipelineVersion(
        pipeline_id=pipeline.id, version=next_version, config_json=config.model_dump_json(),
        note=note, created_by=created_by,
    ))
    pipeline.active_version = next_version
    await session.commit()
    await session.refresh(pipeline)  # onupdate(updated_at) 갱신값 로드 — lazy IO 방지
    logger.info("파이프라인 새 버전: %s v%d (active)", pipeline.name, next_version)
    return await _pipeline_resp(session, pipeline)


async def set_active(
    session: AsyncSession, pipeline: RagPipeline, version: int
) -> PipelineResponse:
    """active 포인터를 지정 버전으로 이동(롤백). 존재하지 않으면 ValueError."""
    if not await _version_row(session, pipeline.id, version):
        raise ValueError(f"버전 {version} 이(가) 없습니다.")
    pipeline.active_version = version
    await session.commit()
    await session.refresh(pipeline)
    logger.info("파이프라인 active 변경: %s → v%d", pipeline.name, version)
    return await _pipeline_resp(session, pipeline)


async def update_meta(
    session: AsyncSession, pipeline: RagPipeline, stage: str | None, description: str | None
) -> PipelineResponse:
    if stage is not None:
        pipeline.stage = stage
    if description is not None:
        pipeline.description = description
    await session.commit()
    await session.refresh(pipeline)
    return await _pipeline_resp(session, pipeline)


async def delete_pipeline(session: AsyncSession, pipeline_id: int) -> bool:
    p = await get_pipeline(session, pipeline_id)
    if not p:
        return False
    await session.delete(p)
    await session.commit()
    return True


async def list_versions(session: AsyncSession, pipeline_id: int) -> list[VersionResponse]:
    rows = (await session.execute(
        select(RagPipelineVersion).where(RagPipelineVersion.pipeline_id == pipeline_id)
        .order_by(RagPipelineVersion.version.desc())
    )).scalars().all()
    return [
        VersionResponse(
            version=r.version, config=PipelineConfig.model_validate_json(r.config_json),
            note=r.note, created_by=r.created_by, created_at=r.created_at,
        )
        for r in rows
    ]


def _flatten(d: dict, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in d.items():
        path = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(_flatten(v, f"{path}."))
        else:
            out[path] = str(v)
    return out


async def diff(
    session: AsyncSession, pipeline_id: int, from_version: int, to_version: int
) -> DiffResponse:
    a = (await _config_of(session, pipeline_id, from_version)).model_dump(mode="json")
    b = (await _config_of(session, pipeline_id, to_version)).model_dump(mode="json")
    fa, fb = _flatten(a), _flatten(b)
    changes = []
    for key in sorted(set(fa) | set(fb)):
        if fa.get(key) != fb.get(key):
            changes.append(DiffEntry(path=key, from_value=fa.get(key), to_value=fb.get(key)))
    return DiffResponse(from_version=from_version, to_version=to_version, changes=changes)


async def resolve_config(session: AsyncSession, pipeline_id: int) -> PipelineConfig | None:
    """실행용 — 파이프라인의 활성 버전 설정을 반환한다."""
    p = await get_pipeline(session, pipeline_id)
    if not p:
        return None
    return await _config_of(session, p.id, p.active_version)
