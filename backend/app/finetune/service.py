# SPDX-License-Identifier: Apache-2.0
"""파인튜닝 학습 데이터셋 서비스 — 데이터셋/예시 CRUD + JSONL 내보내기.

외부 트레이너(extensions/retrieval-fine-tuning) 입력 계약에 맞춰 내보낸다:
    레코드: {"query", "positive", "negatives":[...], "meta":{...}}
    test(홀드아웃)는 내보내지 않는다 — Argus 가 객관적 평가에 보관한다.
"""

import json
import logging
import secrets
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.finetune.models import FtDataset, FtExample, FtGlossaryTerm, FtJob, FtModel
from app.finetune.schemas import (
    BuilderResultResponse,
    BuildFromEvalRequest,
    DatasetCreateRequest,
    DatasetResponse,
    ExampleCreateRequest,
    ExampleResponse,
    GlossaryTermCreateRequest,
    GlossaryTermResponse,
    GlossaryTermUpdateRequest,
    JobCreateRequest,
    JobResponse,
    JobUpdateRequest,
    ManifestResponse,
    MineNegativesRequest,
    ModelCreateRequest,
    ModelResponse,
    ModelUpdateRequest,
)

logger = logging.getLogger(__name__)

# 내보내기 대상 split — test 는 홀드아웃이라 제외(설계: design/fine-tuning.md §5.2)
EXPORT_SPLITS = ("train", "valid")


def _loads(text: str | None, default):
    if not text:
        return default
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return default


def _split_sources(text: str | None) -> list[str]:
    """평가 항목의 기대 출처(줄바꿈 구분 문자열) → 리스트."""
    if not text:
        return []
    return [s.strip() for s in text.splitlines() if s.strip()]


# ---------------------------------------------------------------------------
# 데이터셋
# ---------------------------------------------------------------------------

async def _split_counts(session: AsyncSession, dataset_id: int) -> dict[str, int]:
    rows = (await session.execute(
        select(FtExample.split, func.count())
        .where(FtExample.dataset_id == dataset_id)
        .group_by(FtExample.split)
    )).all()
    return {split: count for split, count in rows}


def _dataset_resp(ds: FtDataset, counts: dict[str, int]) -> DatasetResponse:
    return DatasetResponse(
        id=ds.id, dataset_id=ds.dataset_id, name=ds.name, description=ds.description,
        base_collection_id=ds.base_collection_id, base_model=ds.base_model, task=ds.task,
        prompt_format=ds.prompt_format, split_strategy=ds.split_strategy, status=ds.status,
        counts=counts, created_by=ds.created_by, created_at=ds.created_at, updated_at=ds.updated_at,
    )


async def create_dataset(
    session: AsyncSession, req: DatasetCreateRequest, created_by: str | None
) -> DatasetResponse:
    existing = (await session.execute(
        select(FtDataset).where(FtDataset.name == req.name)
    )).scalars().first()
    if existing:
        raise ValueError(f"데이터셋 '{req.name}' 은 이미 존재합니다.")
    ds = FtDataset(
        dataset_id=str(uuid.uuid4()), name=req.name, description=req.description,
        base_collection_id=req.base_collection_id, base_model=req.base_model,
        task=req.task, prompt_format=req.prompt_format, created_by=created_by,
    )
    session.add(ds)
    await session.commit()
    await session.refresh(ds)
    return _dataset_resp(ds, {})


async def list_datasets(session: AsyncSession) -> list[DatasetResponse]:
    datasets = (await session.execute(
        select(FtDataset).order_by(FtDataset.created_at.desc())
    )).scalars().all()
    rows = (await session.execute(
        select(FtExample.dataset_id, FtExample.split, func.count())
        .group_by(FtExample.dataset_id, FtExample.split)
    )).all()
    by_ds: dict[int, dict[str, int]] = {}
    for ds_id, split, count in rows:
        by_ds.setdefault(ds_id, {})[split] = count
    return [_dataset_resp(d, by_ds.get(d.id, {})) for d in datasets]


async def get_dataset(session: AsyncSession, dataset_id: int) -> FtDataset | None:
    return (await session.execute(
        select(FtDataset).where(FtDataset.id == dataset_id)
    )).scalars().first()


async def get_dataset_resp(session: AsyncSession, dataset_id: int) -> DatasetResponse | None:
    ds = await get_dataset(session, dataset_id)
    if not ds:
        return None
    return _dataset_resp(ds, await _split_counts(session, dataset_id))


# 외부 노출용 UUID 리졸버 — 내부 PK(id)는 응답에 포함된다.
async def get_dataset_by_uuid(session: AsyncSession, dataset_uuid: str) -> FtDataset | None:
    return (await session.execute(
        select(FtDataset).where(FtDataset.dataset_id == dataset_uuid)
    )).scalars().first()


async def get_job_by_uuid(session: AsyncSession, job_uuid: str) -> FtJob | None:
    return (await session.execute(
        select(FtJob).where(FtJob.job_id == job_uuid)
    )).scalars().first()


async def get_model_by_uuid(session: AsyncSession, model_uuid: str) -> FtModel | None:
    return (await session.execute(
        select(FtModel).where(FtModel.model_id == model_uuid)
    )).scalars().first()


async def delete_dataset(session: AsyncSession, dataset_id: int) -> bool:
    ds = await get_dataset(session, dataset_id)
    if not ds:
        return False
    await session.delete(ds)
    await session.commit()
    return True


# ---------------------------------------------------------------------------
# 예시(Example)
# ---------------------------------------------------------------------------

def _example_resp(ex: FtExample) -> ExampleResponse:
    return ExampleResponse(
        id=ex.id, example_id=ex.example_id, dataset_id=ex.dataset_id, split=ex.split,
        query=ex.query, positive=ex.positive, negatives=_loads(ex.negatives, []),
        positive_chunk_id=ex.positive_chunk_id, source=ex.source,
        meta=_loads(ex.meta_json, None), created_at=ex.created_at,
    )


async def add_example(
    session: AsyncSession, dataset_id: int, req: ExampleCreateRequest
) -> ExampleResponse:
    ex = FtExample(
        example_id=str(uuid.uuid4()), dataset_id=dataset_id, split=req.split,
        query=req.query.strip(), positive=req.positive.strip(),
        negatives=json.dumps([n.strip() for n in req.negatives if n.strip()], ensure_ascii=False),
        positive_chunk_id=req.positive_chunk_id, source=req.source,
        meta_json=json.dumps(req.meta, ensure_ascii=False) if req.meta else None,
    )
    session.add(ex)
    await session.commit()
    await session.refresh(ex)
    return _example_resp(ex)


async def list_examples(
    session: AsyncSession, dataset_id: int, split: str | None = None, limit: int = 200
) -> list[ExampleResponse]:
    stmt = select(FtExample).where(FtExample.dataset_id == dataset_id)
    if split:
        stmt = stmt.where(FtExample.split == split)
    stmt = stmt.order_by(FtExample.created_at.desc()).limit(limit)
    examples = (await session.execute(stmt)).scalars().all()
    return [_example_resp(e) for e in examples]


async def delete_example(session: AsyncSession, example_uuid: str) -> bool:
    # 외부 노출 식별자는 예시 UUID(example_id).
    ex = (await session.execute(
        select(FtExample).where(FtExample.example_id == example_uuid)
    )).scalars().first()
    if not ex:
        return False
    await session.delete(ex)
    await session.commit()
    return True


# ---------------------------------------------------------------------------
# 내보내기
# ---------------------------------------------------------------------------

async def build_manifest(session: AsyncSession, ds: FtDataset) -> ManifestResponse:
    return ManifestResponse(
        dataset_id=ds.dataset_id, name=ds.name, base_model=ds.base_model, task=ds.task,
        prompt_format=ds.prompt_format, split_strategy=ds.split_strategy,
        counts=await _split_counts(session, ds.id), created_at=ds.created_at,
    )


async def export_jsonl(session: AsyncSession, dataset_id: int, split: str) -> str:
    """지정 split 의 예시를 외부 트레이너 계약 포맷(JSONL 문자열)으로 반환한다."""
    if split not in EXPORT_SPLITS:
        raise ValueError(f"내보낼 수 있는 split 은 {EXPORT_SPLITS} 입니다(test 는 홀드아웃).")
    examples = (await session.execute(
        select(FtExample).where(FtExample.dataset_id == dataset_id, FtExample.split == split)
        .order_by(FtExample.created_at)
    )).scalars().all()
    lines = []
    for ex in examples:
        rec = {
            "query": ex.query,
            "positive": ex.positive,
            "negatives": _loads(ex.negatives, []),
        }
        meta = _loads(ex.meta_json, None)
        if meta:
            rec["meta"] = meta
        lines.append(json.dumps(rec, ensure_ascii=False))
    return "\n".join(lines) + ("\n" if lines else "")


# ---------------------------------------------------------------------------
# 학습 작업(Job)
# ---------------------------------------------------------------------------

_TERMINAL = ("succeeded", "failed", "canceled")


def _job_resp(
    job: FtJob, dataset_name: str | None = None, *, include_token: bool = False
) -> JobResponse:
    # 콜백 토큰은 시크릿이라 superuser 컨텍스트에서만 노출(include_token=True).
    return JobResponse(
        id=job.id, job_id=job.job_id, dataset_id=job.dataset_id, dataset_name=dataset_name,
        task=job.task, base_model=job.base_model, config=_loads(job.config_json, {}),
        status=job.status, stage=job.stage, progress=job.progress,
        metrics=_loads(job.metrics_json, None), artifact_uri=job.artifact_uri, error=job.error,
        callback_token=job.callback_token if include_token else None,
        created_by=job.created_by, created_at=job.created_at,
        started_at=job.started_at, finished_at=job.finished_at,
    )


async def authorize_by_job_token(
    session: AsyncSession, token: str | None, *, job_id: int | None = None,
    dataset_id: int | None = None,
) -> bool:
    """잡 콜백 토큰으로 인증한다(M2M). 토큰이 어떤 잡의 callback_token 과 일치하고,
    그 잡이 대상 job_id(콜백) 또는 dataset_id(export)에 해당하면 True.
    """
    if not token:
        return False
    job = (await session.execute(
        select(FtJob).where(FtJob.callback_token == token)
    )).scalars().first()
    if not job:
        return False
    if job_id is not None and job.id != job_id:
        return False
    if dataset_id is not None and job.dataset_id != dataset_id:
        return False
    return True


async def create_job(
    session: AsyncSession, req: JobCreateRequest, created_by: str | None
) -> JobResponse:
    ds = await get_dataset(session, req.dataset_id)
    if not ds:
        raise ValueError("데이터셋을 찾을 수 없습니다.")
    config = {
        "epochs": req.epochs, "batch_size": req.batch_size,
        "lr": req.lr, "max_negatives": req.max_negatives,
    }
    job = FtJob(
        job_id=str(uuid.uuid4()), dataset_id=ds.id,
        task=req.task or ds.task, base_model=req.base_model or ds.base_model,
        config_json=json.dumps(config, ensure_ascii=False), status="queued",
        callback_token=secrets.token_urlsafe(32), created_by=created_by,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return _job_resp(job, ds.name, include_token=True)


async def list_jobs(session: AsyncSession, dataset_id: int | None = None) -> list[JobResponse]:
    stmt = select(FtJob, FtDataset.name).join(FtDataset, FtJob.dataset_id == FtDataset.id)
    if dataset_id is not None:
        stmt = stmt.where(FtJob.dataset_id == dataset_id)
    stmt = stmt.order_by(FtJob.created_at.desc())
    rows = (await session.execute(stmt)).all()
    return [_job_resp(job, name) for job, name in rows]


async def get_job(session: AsyncSession, job_pk: int) -> FtJob | None:
    return (await session.execute(
        select(FtJob).where(FtJob.id == job_pk)
    )).scalars().first()


async def get_job_resp(
    session: AsyncSession, job_pk: int, *, include_token: bool = False
) -> JobResponse | None:
    job = await get_job(session, job_pk)
    if not job:
        return None
    ds = await get_dataset(session, job.dataset_id)
    return _job_resp(job, ds.name if ds else None, include_token=include_token)


async def update_job(
    session: AsyncSession, job_pk: int, req: JobUpdateRequest
) -> JobResponse | None:
    """외부 트레이너/운영자 콜백으로 잡 상태를 갱신한다."""
    job = await get_job(session, job_pk)
    if not job:
        return None
    if req.status is not None:
        # queued→running 진입 시 started_at, 종료 상태 진입 시 finished_at 기록
        if req.status == "running" and job.started_at is None:
            job.started_at = func.now()
        if req.status in _TERMINAL:
            job.finished_at = func.now()
        job.status = req.status
    if req.stage is not None:
        job.stage = req.stage
    if req.progress is not None:
        job.progress = req.progress
    if req.metrics is not None:
        job.metrics_json = json.dumps(req.metrics, ensure_ascii=False)
    if req.artifact_uri is not None:
        job.artifact_uri = req.artifact_uri
    if req.error is not None:
        job.error = req.error
    await session.commit()
    await session.refresh(job)
    ds = await get_dataset(session, job.dataset_id)
    return _job_resp(job, ds.name if ds else None)


async def cancel_job(session: AsyncSession, job_pk: int) -> JobResponse | None:
    job = await get_job(session, job_pk)
    if not job:
        return None
    if job.status not in _TERMINAL:
        job.status = "canceled"
        job.finished_at = func.now()
        await session.commit()
        await session.refresh(job)
    ds = await get_dataset(session, job.dataset_id)
    return _job_resp(job, ds.name if ds else None)


async def delete_job(session: AsyncSession, job_pk: int) -> bool:
    job = await get_job(session, job_pk)
    if not job:
        return False
    await session.delete(job)
    await session.commit()
    return True


# ---------------------------------------------------------------------------
# 모델 레지스트리(Model)
# ---------------------------------------------------------------------------

def _model_resp(m: FtModel) -> ModelResponse:
    return ModelResponse(
        id=m.id, model_id=m.model_id, name=m.name, task=m.task, base_model=m.base_model,
        embedding_dim=m.embedding_dim, format=m.format, prompt_format=m.prompt_format,
        dataset_id=m.dataset_id, job_id=m.job_id, artifact_uri=m.artifact_uri,
        metrics=_loads(m.metrics_json, None), serving_url=m.serving_url, status=m.status,
        published_uri=m.published_uri, created_by=m.created_by,
        created_at=m.created_at, updated_at=m.updated_at,
    )


async def register_model(
    session: AsyncSession, req: ModelCreateRequest, created_by: str | None
) -> ModelResponse:
    existing = (await session.execute(
        select(FtModel).where(FtModel.name == req.name)
    )).scalars().first()
    if existing:
        raise ValueError(f"모델 '{req.name}' 은 이미 존재합니다.")
    m = FtModel(
        model_id=str(uuid.uuid4()), name=req.name, task=req.task, base_model=req.base_model,
        embedding_dim=req.embedding_dim, format=req.format, prompt_format=req.prompt_format,
        dataset_id=req.dataset_id, job_id=req.job_id, artifact_uri=req.artifact_uri,
        metrics_json=json.dumps(req.metrics, ensure_ascii=False) if req.metrics else None,
        serving_url=req.serving_url, created_by=created_by,
    )
    session.add(m)
    await session.commit()
    await session.refresh(m)
    return _model_resp(m)


async def register_from_job(
    session: AsyncSession, job_pk: int, name: str | None, created_by: str | None
) -> ModelResponse:
    """성공한 잡의 아티팩트를 등록 모델로 승격한다."""
    job = await get_job(session, job_pk)
    if not job:
        raise ValueError("작업을 찾을 수 없습니다.")
    if job.status != "succeeded":
        raise ValueError("성공(succeeded)한 작업만 모델로 등록할 수 있습니다.")
    fmt = "sentence-transformers-cross-encoder" if job.task == "reranker" else "sentence-transformers"
    req = ModelCreateRequest(
        name=name or f"{(job.base_model or 'model').split('/')[-1]}-ft-job{job.id}",
        task=job.task, base_model=job.base_model, format=fmt,
        dataset_id=job.dataset_id, job_id=job.id, artifact_uri=job.artifact_uri,
        metrics=_loads(job.metrics_json, None),
    )
    return await register_model(session, req, created_by)


async def list_models(session: AsyncSession) -> list[ModelResponse]:
    models = (await session.execute(
        select(FtModel).order_by(FtModel.created_at.desc())
    )).scalars().all()
    return [_model_resp(m) for m in models]


async def get_model(session: AsyncSession, model_pk: int) -> FtModel | None:
    return (await session.execute(
        select(FtModel).where(FtModel.id == model_pk)
    )).scalars().first()


async def get_model_resp(session: AsyncSession, model_pk: int) -> ModelResponse | None:
    m = await get_model(session, model_pk)
    return _model_resp(m) if m else None


async def update_model(
    session: AsyncSession, model_pk: int, req: ModelUpdateRequest
) -> ModelResponse | None:
    m = await get_model(session, model_pk)
    if not m:
        return None
    if req.serving_url is not None:
        m.serving_url = req.serving_url
    if req.status is not None:
        m.status = req.status
    if req.published_uri is not None:
        m.published_uri = req.published_uri
    await session.commit()
    await session.refresh(m)
    return _model_resp(m)


async def delete_model(session: AsyncSession, model_pk: int) -> bool:
    m = await get_model(session, model_pk)
    if not m:
        return False
    await session.delete(m)
    await session.commit()
    return True


# ---------------------------------------------------------------------------
# 용어 사전(Glossary)
# ---------------------------------------------------------------------------

def _term_resp(t: FtGlossaryTerm) -> GlossaryTermResponse:
    return GlossaryTermResponse(
        id=t.id, term_id=t.term_id, term=t.term, definition=t.definition,
        synonyms=_loads(t.synonyms, []), domain=t.domain, created_by=t.created_by,
        created_at=t.created_at, updated_at=t.updated_at,
    )


async def list_terms(session: AsyncSession, domain: str | None = None) -> list[GlossaryTermResponse]:
    stmt = select(FtGlossaryTerm)
    if domain:
        stmt = stmt.where(FtGlossaryTerm.domain == domain)
    stmt = stmt.order_by(FtGlossaryTerm.term)
    terms = (await session.execute(stmt)).scalars().all()
    return [_term_resp(t) for t in terms]


async def create_term(
    session: AsyncSession, req: GlossaryTermCreateRequest, created_by: str | None
) -> GlossaryTermResponse:
    t = FtGlossaryTerm(
        term_id=str(uuid.uuid4()), term=req.term.strip(), definition=req.definition,
        synonyms=json.dumps([s.strip() for s in req.synonyms if s.strip()], ensure_ascii=False),
        domain=(req.domain or None), created_by=created_by,
    )
    session.add(t)
    await session.commit()
    await session.refresh(t)
    return _term_resp(t)


async def _get_term(session: AsyncSession, term_pk: int) -> FtGlossaryTerm | None:
    return (await session.execute(
        select(FtGlossaryTerm).where(FtGlossaryTerm.id == term_pk)
    )).scalars().first()


async def update_term(
    session: AsyncSession, term_pk: int, req: GlossaryTermUpdateRequest
) -> GlossaryTermResponse | None:
    t = await _get_term(session, term_pk)
    if not t:
        return None
    if req.term is not None:
        t.term = req.term.strip()
    if req.definition is not None:
        t.definition = req.definition
    if req.synonyms is not None:
        t.synonyms = json.dumps([s.strip() for s in req.synonyms if s.strip()], ensure_ascii=False)
    if req.domain is not None:
        t.domain = req.domain or None
    await session.commit()
    await session.refresh(t)
    return _term_resp(t)


async def delete_term(session: AsyncSession, term_pk: int) -> bool:
    t = await _get_term(session, term_pk)
    if not t:
        return False
    await session.delete(t)
    await session.commit()
    return True


# ---------------------------------------------------------------------------
# 빌더 / 하드네거티브 마이닝 (검색 기반)
# ---------------------------------------------------------------------------

async def _collection_obj(session: AsyncSession, collection_id: int):
    from app.collections.models import RagCollection
    return (await session.execute(
        select(RagCollection).where(RagCollection.id == collection_id)
    )).scalars().first()


def _matches_source(doc_name: str, expected_sources: list[str]) -> bool:
    dl = (doc_name or "").lower()
    return any(s.lower() in dl for s in expected_sources if s.strip())


async def build_from_eval(
    session: AsyncSession, ft_dataset_id: int, req: BuildFromEvalRequest
) -> BuilderResultResponse:
    """평가 골든셋(질문+기대출처)에서 검색으로 (질의·정답·오답) 트리플을 생성한다."""
    from app.evaluation.models import RagEvalDataset, RagEvalItem
    from app.retrieval import service as retrieval

    ds = await get_dataset(session, ft_dataset_id)
    if not ds:
        raise ValueError("학습 데이터셋을 찾을 수 없습니다.")
    eval_ds = (await session.execute(
        select(RagEvalDataset).where(RagEvalDataset.id == req.eval_dataset_id)
    )).scalars().first()
    if not eval_ds:
        raise ValueError("평가 데이터셋을 찾을 수 없습니다.")
    if not eval_ds.collection_id:
        raise ValueError("평가 데이터셋에 연결된 컬렉션이 없어 검색으로 빌드할 수 없습니다.")
    collection = await _collection_obj(session, eval_ds.collection_id)
    if not collection:
        raise ValueError("평가 데이터셋의 컬렉션을 찾을 수 없습니다.")

    items = (await session.execute(
        select(RagEvalItem).where(RagEvalItem.dataset_id == eval_ds.id)
    )).scalars().all()

    built = skipped = 0
    for item in items:
        expected = _split_sources(item.expected_sources)
        if not expected:
            skipped += 1
            continue
        hits = await retrieval.search(session, collection, item.question, "vector", req.top_k)
        positive = next((h for h in hits if _matches_source(h.document_name, expected)), None)
        if not positive:
            skipped += 1
            continue
        negatives = [
            h.text for h in hits
            if h.chunk_id != positive.chunk_id and not _matches_source(h.document_name, expected)
        ][: req.max_negatives]
        session.add(FtExample(
            example_id=str(uuid.uuid4()), dataset_id=ds.id, split=req.split,
            query=item.question, positive=positive.text,
            negatives=json.dumps(negatives, ensure_ascii=False),
            positive_chunk_id=None, source="goldenset",
            meta_json=json.dumps({"eval_dataset_id": eval_ds.id}, ensure_ascii=False),
        ))
        built += 1

    # 빌드에 쓴 컬렉션을 데이터셋 기준 컬렉션으로 기록(이후 마이닝에 사용)
    if built and not ds.base_collection_id:
        ds.base_collection_id = collection.id
    await session.commit()
    return BuilderResultResponse(
        built=built, skipped=skipped,
        message=f"{built}건 생성, {skipped}건 건너뜀(기대출처 없음/정답 미검색)",
    )


async def mine_negatives(
    session: AsyncSession, ft_dataset_id: int, req: MineNegativesRequest
) -> BuilderResultResponse:
    """데이터셋 기준 컬렉션에서 검색으로 각 예시의 하드네거티브를 보강한다."""
    from app.retrieval import service as retrieval

    ds = await get_dataset(session, ft_dataset_id)
    if not ds:
        raise ValueError("학습 데이터셋을 찾을 수 없습니다.")
    if not ds.base_collection_id:
        raise ValueError("기준 컬렉션이 없습니다. 먼저 골든셋에서 빌드하거나 컬렉션을 지정하세요.")
    collection = await _collection_obj(session, ds.base_collection_id)
    if not collection:
        raise ValueError("기준 컬렉션을 찾을 수 없습니다.")

    examples = (await session.execute(
        select(FtExample).where(FtExample.dataset_id == ds.id)
    )).scalars().all()

    updated = 0
    for ex in examples:
        existing = _loads(ex.negatives, [])
        if req.only_missing and existing:
            continue
        hits = await retrieval.search(session, collection, ex.query, "vector", req.top_k)
        mined = [
            h.text for h in hits
            if h.text != ex.positive and h.text not in existing
        ][: req.per_example]
        if not mined:
            continue
        ex.negatives = json.dumps(existing + mined, ensure_ascii=False)
        updated += 1

    await session.commit()
    return BuilderResultResponse(updated=updated, message=f"{updated}개 예시에 하드네거티브 추가")
