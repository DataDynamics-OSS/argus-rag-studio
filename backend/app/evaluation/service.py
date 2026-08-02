# SPDX-License-Identifier: Apache-2.0
"""평가 서비스 — 데이터셋/항목 CRUD + 평가 Run 실행.

Run 실행은 비동기 워커가 호출한다: 데이터셋 항목마다 RAG 파이프라인(검색→(리랭크)→생성)을
돌려 검색 지표(hit/rr)와 (judge=true 시) 생성 지표를 산출하고, 항목별 결과 저장 + 집계한다.

LLM 미가용 시: 생성이 처음 실패하면 이후 항목은 생성을 건너뛰어(검색 지표만) 빠르게 완주한다.
"""

import json
import logging
import uuid

from sqlalchemy import delete as sql_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collections.models import RagCollection
from app.core.config import settings
from app.evaluation import metrics as M
from app.evaluation.models import (
    RagEvalDataset,
    RagEvalItem,
    RagEvalResult,
    RagEvalRun,
)
from app.evaluation.schemas import (
    DatasetCreateRequest,
    DatasetResponse,
    ItemCreateRequest,
    ItemResponse,
    ResultResponse,
    RunCreateRequest,
    RunResponse,
)
from app.generation import service as gen
from app.llm import service as llm
from app.pipelines.service import resolve_config
from app.rerank.service import rerank
from app.retrieval import service as retrieval

logger = logging.getLogger(__name__)


def _split_sources(text: str | None) -> list[str]:
    if not text:
        return []
    return [s.strip() for s in text.splitlines() if s.strip()]


# ---------------------------------------------------------------------------
# 데이터셋 / 항목
# ---------------------------------------------------------------------------

async def create_dataset(
    session: AsyncSession, req: DatasetCreateRequest, created_by: str | None
) -> DatasetResponse:
    existing = (await session.execute(
        select(RagEvalDataset).where(RagEvalDataset.name == req.name)
    )).scalars().first()
    if existing:
        raise ValueError(f"Dataset '{req.name}' already exists")
    ds = RagEvalDataset(
        dataset_id=str(uuid.uuid4()), name=req.name, description=req.description,
        collection_id=req.collection_id, created_by=created_by,
    )
    session.add(ds)
    await session.commit()
    await session.refresh(ds)
    return _dataset_resp(ds, 0)


def _dataset_resp(ds: RagEvalDataset, item_count: int) -> DatasetResponse:
    return DatasetResponse(
        id=ds.id, dataset_id=ds.dataset_id, name=ds.name, description=ds.description,
        collection_id=ds.collection_id, item_count=item_count, created_by=ds.created_by,
        created_at=ds.created_at, updated_at=ds.updated_at,
    )


async def list_datasets(session: AsyncSession) -> list[DatasetResponse]:
    datasets = (await session.execute(
        select(RagEvalDataset).order_by(RagEvalDataset.created_at.desc())
    )).scalars().all()
    counts = dict((await session.execute(
        select(RagEvalItem.dataset_id, func.count()).group_by(RagEvalItem.dataset_id)
    )).all())
    return [_dataset_resp(d, counts.get(d.id, 0)) for d in datasets]


async def get_dataset(session: AsyncSession, dataset_id: int) -> RagEvalDataset | None:
    return (await session.execute(
        select(RagEvalDataset).where(RagEvalDataset.id == dataset_id)
    )).scalars().first()


async def get_dataset_by_uuid(session: AsyncSession, dataset_uuid: str) -> RagEvalDataset | None:
    """외부 노출용 UUID(dataset_id)로 조회. 내부 PK(id)는 응답에 포함된다."""
    return (await session.execute(
        select(RagEvalDataset).where(RagEvalDataset.dataset_id == dataset_uuid)
    )).scalars().first()


async def delete_dataset(session: AsyncSession, dataset_id: int) -> bool:
    ds = await get_dataset(session, dataset_id)
    if not ds:
        return False
    await session.delete(ds)
    await session.commit()
    return True


async def add_item(
    session: AsyncSession, dataset_id: int, req: ItemCreateRequest
) -> ItemResponse:
    item = RagEvalItem(
        item_id=str(uuid.uuid4()), dataset_id=dataset_id, question=req.question,
        expected_answer=req.expected_answer,
        expected_sources="\n".join(req.expected_sources),
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return _item_resp(item)


def _item_resp(item: RagEvalItem) -> ItemResponse:
    return ItemResponse(
        id=item.id, item_id=item.item_id, dataset_id=item.dataset_id,
        question=item.question, expected_answer=item.expected_answer,
        expected_sources=_split_sources(item.expected_sources), created_at=item.created_at,
    )


async def list_items(session: AsyncSession, dataset_id: int) -> list[ItemResponse]:
    items = (await session.execute(
        select(RagEvalItem).where(RagEvalItem.dataset_id == dataset_id)
        .order_by(RagEvalItem.created_at)
    )).scalars().all()
    return [_item_resp(i) for i in items]


async def delete_item(session: AsyncSession, item_uuid: str) -> bool:
    # 외부 노출 식별자는 항목 UUID(item_id).
    item = (await session.execute(
        select(RagEvalItem).where(RagEvalItem.item_id == item_uuid)
    )).scalars().first()
    if not item:
        return False
    await session.delete(item)
    await session.commit()
    return True


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

def _run_resp(run: RagEvalRun) -> RunResponse:
    return RunResponse(
        id=run.id, run_id=run.run_id, dataset_id=run.dataset_id, collection_id=run.collection_id,
        pipeline_id=run.pipeline_id,
        status=run.status, mode=run.mode, distance_metric=run.distance_metric,
        rerank=run.rerank, judge=run.judge, top_k=run.top_k,
        total_items=run.total_items, completed_items=run.completed_items,
        hit_rate=run.hit_rate, mrr=run.mrr, faithfulness=run.faithfulness,
        answer_relevance=run.answer_relevance, correctness=run.correctness,
        error=run.error, created_at=run.created_at,
        started_at=run.started_at, finished_at=run.finished_at,
    )


async def create_run(
    session: AsyncSession, dataset: RagEvalDataset, req: RunCreateRequest, created_by: str | None
) -> RunResponse:
    """평가 Run 을 queued 로 생성한다. 컬렉션은 요청 > 데이터셋 기본 순으로 결정."""
    collection_id = req.collection_id or dataset.collection_id
    if not collection_id:
        raise ValueError("평가 대상 컬렉션이 지정되지 않았습니다.")
    metric = (await session.execute(
        select(RagCollection.distance_metric).where(RagCollection.id == collection_id)
    )).scalar()
    total = (await session.execute(
        select(func.count()).where(RagEvalItem.dataset_id == dataset.id)
    )).scalar() or 0
    if total == 0:
        raise ValueError("데이터셋에 평가 항목이 없습니다.")

    # 파이프라인 지정 시 표시용 mode/rerank/top_k/metric 을 활성 버전 설정으로 맞춘다(실행도 동일 적용).
    mode_v, rerank_v, top_k_v, metric_v = req.mode.value, req.rerank, req.top_k or settings.retrieval_top_k, metric
    if req.pipeline_id:
        cfg = await resolve_config(session, req.pipeline_id)
        if not cfg:
            raise ValueError("지정한 파이프라인을 찾을 수 없습니다.")
        mode_v = cfg.retrieval.mode.value
        rerank_v = cfg.rerank.enabled
        top_k_v = cfg.retrieval.top_k
        metric_v = cfg.retrieval.distance_metric or metric

    run = RagEvalRun(
        run_id=str(uuid.uuid4()), dataset_id=dataset.id, collection_id=collection_id,
        pipeline_id=req.pipeline_id,
        status="queued", mode=mode_v, distance_metric=metric_v,
        rerank=rerank_v, judge=req.judge,
        top_k=top_k_v, total_items=total, created_by=created_by,
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    logger.info("평가 Run enqueue: run=%s dataset=%s items=%d", run.run_id, dataset.name, total)
    return _run_resp(run)


async def claim_next_run(session: AsyncSession) -> RagEvalRun | None:
    row = (await session.execute(
        select(RagEvalRun).where(RagEvalRun.status == "queued")
        .order_by(RagEvalRun.created_at).limit(1).with_for_update(skip_locked=True)
    )).scalars().first()
    if not row:
        return None
    row.status = "running"
    row.started_at = func.now()
    await session.commit()
    await session.refresh(row)
    return row


async def run_evaluation(session: AsyncSession, run: RagEvalRun) -> None:
    """Run 을 실행한다: 항목별 RAG 파이프라인 + 지표 산출 → 결과 저장 + 집계."""
    collection = (await session.execute(
        select(RagCollection).where(RagCollection.id == run.collection_id)
    )).scalars().first()
    if not collection:
        run.status = "failed"
        run.error = "컬렉션을 찾을 수 없습니다."
        run.finished_at = func.now()
        await session.commit()
        return

    items = (await session.execute(
        select(RagEvalItem).where(RagEvalItem.dataset_id == run.dataset_id)
        .order_by(RagEvalItem.created_at)
    )).scalars().all()

    # 재실행(스윕 judge 게이팅 등) 멱등성 — 이전 결과를 지우고 처음부터 다시 채운다.
    await session.execute(sql_delete(RagEvalResult).where(RagEvalResult.run_id == run.id))
    run.completed_items = 0
    await session.commit()

    agg = {"hit": [], "rr": [], "faith": [], "rel": [], "corr": []}
    gen_failed = False

    # 파이프라인 지정 시 활성 버전의 검색·리랭크 세부 설정을 적용한다(미지정이면 run 의 mode/top_k/rerank).
    cfg = await resolve_config(session, run.pipeline_id) if run.pipeline_id else None

    try:
        for item in items:
            expected = _split_sources(item.expected_sources)
            # 1) 검색
            if cfg:
                r = cfg.retrieval
                hits = await retrieval.search(
                    session, collection, item.question, r.mode.value, r.top_k,
                    vector_k=r.vector_k, lexical_k=r.lexical_k, rrf_k=r.rrf_k,
                    distance_metric=r.distance_metric or None,
                )
                if cfg.rerank.enabled:
                    hits = await rerank(item.question, hits, cfg.rerank.top_n, provider=cfg.rerank.provider)
            else:
                hits = await retrieval.search(session, collection, item.question, run.mode, run.top_k)
                if run.rerank:
                    hits = await rerank(item.question, hits, run.top_k)
            retrieved_docs = [h.document_name for h in hits]
            hit, rr = M.retrieval_metrics(expected, retrieved_docs)

            # 2) 생성 (LLM 가용 시). 한 번 실패하면 이후 항목은 생략(빠른 완주).
            answer = ""
            if not gen_failed:
                try:
                    messages = gen.build_messages(hits, [{"role": "user", "content": item.question}])
                    answer = await llm.complete(messages)
                except Exception as e:
                    gen_failed = True
                    logger.warning("평가 생성 실패 — 이후 항목은 검색 지표만: %s", e)

            # 3) 생성 지표 (judge=true 이고 답변이 있을 때)
            faith = rel = corr = None
            if run.judge and answer:
                context = gen.build_context(hits)
                scores = await M.judge_generation(item.question, context, answer, item.expected_answer)
                faith, rel, corr = scores["faithfulness"], scores["answer_relevance"], scores["correctness"]

            session.add(RagEvalResult(
                run_id=run.id, item_id=item.id, question=item.question, answer=answer,
                retrieved_docs=json.dumps(retrieved_docs, ensure_ascii=False),
                hit=hit, reciprocal_rank=rr, faithfulness=faith, answer_relevance=rel, correctness=corr,
            ))
            if hit is not None:
                agg["hit"].append(1.0 if hit else 0.0)
            if rr is not None:
                agg["rr"].append(rr)
            for key, val in (("faith", faith), ("rel", rel), ("corr", corr)):
                if val is not None:
                    agg[key].append(val)

            run.completed_items += 1
            await session.commit()

        def _mean(xs):
            return round(sum(xs) / len(xs), 4) if xs else None

        run.hit_rate = _mean(agg["hit"])
        run.mrr = _mean(agg["rr"])
        run.faithfulness = _mean(agg["faith"])
        run.answer_relevance = _mean(agg["rel"])
        run.correctness = _mean(agg["corr"])
        run.status = "succeeded"
        run.finished_at = func.now()
        await session.commit()
        logger.info(
            "평가 완료: run=%s hit_rate=%s mrr=%s faith=%s",
            run.run_id, run.hit_rate, run.mrr, run.faithfulness,
        )
    except Exception as e:
        await session.rollback()
        logger.warning("평가 Run 실패: run=%s err=%s", run.run_id, e)
        run_row = (await session.execute(
            select(RagEvalRun).where(RagEvalRun.id == run.id)
        )).scalars().first()
        if run_row:
            run_row.status = "failed"
            run_row.error = str(e)[:2000]
            run_row.finished_at = func.now()
            await session.commit()


async def get_run(session: AsyncSession, run_id: str) -> RunResponse | None:
    run = (await session.execute(
        select(RagEvalRun).where(RagEvalRun.run_id == run_id)
    )).scalars().first()
    return _run_resp(run) if run else None


async def list_runs(session: AsyncSession, dataset_id: int) -> list[RunResponse]:
    runs = (await session.execute(
        select(RagEvalRun).where(RagEvalRun.dataset_id == dataset_id)
        .order_by(RagEvalRun.created_at.desc())
    )).scalars().all()
    return [_run_resp(r) for r in runs]


async def list_all_runs(session: AsyncSession, limit: int = 200) -> list[RunResponse]:
    """전역 평가 런 목록(최신순) — 잡 모니터링용."""
    runs = (await session.execute(
        select(RagEvalRun).order_by(RagEvalRun.created_at.desc()).limit(limit)
    )).scalars().all()
    return [_run_resp(r) for r in runs]


async def list_results(session: AsyncSession, run_id: str) -> list[ResultResponse]:
    run = (await session.execute(
        select(RagEvalRun).where(RagEvalRun.run_id == run_id)
    )).scalars().first()
    if not run:
        return []
    results = (await session.execute(
        select(RagEvalResult).where(RagEvalResult.run_id == run.id).order_by(RagEvalResult.id)
    )).scalars().all()
    out = []
    for r in results:
        try:
            docs = json.loads(r.retrieved_docs) if r.retrieved_docs else []
        except Exception:
            docs = []
        out.append(ResultResponse(
            id=r.id, item_id=r.item_id, question=r.question, answer=r.answer,
            retrieved_docs=docs, hit=r.hit, reciprocal_rank=r.reciprocal_rank,
            faithfulness=r.faithfulness, answer_relevance=r.answer_relevance, correctness=r.correctness,
        ))
    return out
