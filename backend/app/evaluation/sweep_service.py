# SPDX-License-Identifier: Apache-2.0
"""설정 스윕(AutoML식 옵션 탐색) 서비스.

탐색 공간을 2축으로 나눈다:
  - index_axis(비쌈, 재인덱싱 필요): parse_strategy/chunk_strategy/chunk_size/chunk_overlap/chunk_unit
  - query_axis(쌈, 재인덱싱 0): mode/top_k/rerank

스윕은 (index 조합 × query 조합)마다 평가 Run 을 만들고, 기존 평가 워커가 그 Run 들을
실행한다(재사용). 모든 Run 이 끝나면 primary_metric 으로 베스트를 고른다.

P1: index_axis 없이 query_axis 만(=base 컬렉션 1개 위에서 스윕). P2: index_axis 후보를
임시 컬렉션으로 만들어(재인덱싱) 함께 평가. 이 모듈은 두 경우를 모두 다룬다.
"""

import hashlib
import itertools
import json
import logging
import uuid

from sqlalchemy import delete as sql_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collections.models import RagCollection
from app.core.config import settings
from app.evaluation.models import (
    RagEvalDataset,
    RagEvalItem,
    RagEvalResult,
    RagEvalRun,
    RagEvalSweep,
)
from app.evaluation.schemas import (
    LeaderboardResponse,
    LeaderboardRow,
    SweepCreateRequest,
    SweepResponse,
)

logger = logging.getLogger(__name__)

# 축별 허용 파라미터
_QUERY_PARAMS = {"mode", "top_k", "rerank"}
_INDEX_PARAMS = {"parse_strategy", "chunk_strategy", "chunk_size", "chunk_overlap", "chunk_unit"}
_VALID_MODES = {"hybrid", "vector", "lexical"}

# query_axis 미지정 시 기본 스윕(싸고 효과 큰 레버)
_DEFAULT_QUERY_AXIS = {"mode": ["hybrid", "vector", "lexical"], "top_k": [3, 5, 10], "rerank": [False, True]}

# composite 점수 가중치(존재하는 지표만으로 정규화)
_COMPOSITE_WEIGHTS = {"hit_rate": 0.5, "mrr": 0.3, "faithfulness": 0.2}

# 검색만으로 게이팅 가능한 지표(judge 전에 상위 N 선별에 사용)
_RETRIEVAL_METRICS = {"hit_rate", "mrr"}
# train 대비 holdout 점수가 이 이상 떨어지면 과적합 의심 플래그
_OVERFIT_GAP = 0.1


# ---------------------------------------------------------------------------
# 홀드아웃 분할 / 항목별 지표 (P3)
# ---------------------------------------------------------------------------

def assign_splits(items: list[RagEvalItem], holdout_ratio: float) -> dict[int, str]:
    """평가 항목을 train/holdout 으로 *결정적* 분할한다(md5(item_id) 정렬 상위 k개 = holdout).

    프로세스·실행 순서와 무관하게 항상 같은 분할을 보장(파이썬 hash() 는 솔트되어 불가).
    항목 2개 미만이거나 ratio<=0 이면 전부 train. train/holdout 각각 최소 1개를 보장한다.
    반환: {RagEvalItem.id: "train"|"holdout"}.
    """
    if not holdout_ratio or holdout_ratio <= 0 or len(items) < 2:
        return {it.id: "train" for it in items}
    k = round(len(items) * holdout_ratio)
    k = max(1, min(k, len(items) - 1))
    ordered = sorted(items, key=lambda it: hashlib.md5(it.item_id.encode()).hexdigest())
    holdout_ids = {ordered[i].id for i in range(k)}
    return {it.id: ("holdout" if it.id in holdout_ids else "train") for it in items}


def _result_value(r: RagEvalResult, metric: str) -> float | None:
    """항목별 결과에서 지표값 1개를 뽑는다(없으면 None)."""
    if metric == "hit_rate":
        return None if r.hit is None else (1.0 if r.hit else 0.0)
    if metric == "mrr":
        return r.reciprocal_rank
    if metric == "faithfulness":
        return r.faithfulness
    if metric == "answer_relevance":
        return r.answer_relevance
    if metric == "correctness":
        return r.correctness
    if metric == "composite":
        num = den = 0.0
        for m, w in _COMPOSITE_WEIGHTS.items():
            v = _result_value(r, m)
            if v is not None:
                num += w * v
                den += w
        return round(num / den, 4) if den else None
    return None


def _mean(xs: list[float | None]) -> float | None:
    vals = [x for x in xs if x is not None]
    return round(sum(vals) / len(vals), 4) if vals else None


def split_metric(
    results: list[RagEvalResult], split_map: dict[int, str], metric: str, split: str
) -> float | None:
    """한 Run 의 항목별 결과 중 지정 split(train/holdout)에 대한 지표 평균."""
    return _mean([_result_value(r, metric) for r in results if split_map.get(r.item_id) == split])


def _gate_metric(primary: str) -> str:
    """judge 게이팅용 검색 지표 — primary 가 검색 지표면 그대로, 아니면 hit_rate."""
    return primary if primary in _RETRIEVAL_METRICS else "hit_rate"


# ---------------------------------------------------------------------------
# 탐색 공간 전개
# ---------------------------------------------------------------------------

def _product(axis: dict) -> list[dict]:
    """{param: [v1,v2]} → [{param:v1},{param:v2},...] 카테시안 곱. 빈 축이면 [{}]."""
    if not axis:
        return [{}]
    keys = list(axis.keys())
    value_lists = [axis[k] if isinstance(axis[k], list) else [axis[k]] for k in keys]
    return [dict(zip(keys, combo)) for combo in itertools.product(*value_lists)]


def expand_search_space(space: dict) -> tuple[list[dict], list[dict]]:
    """search_space → (index_combos, query_combos). 검증 포함."""
    space = space or {}
    index_axis = space.get("index_axis") or {}
    query_axis = space.get("query_axis") or dict(_DEFAULT_QUERY_AXIS)

    bad_q = set(query_axis) - _QUERY_PARAMS
    if bad_q:
        raise ValueError(f"query_axis 에 허용되지 않은 파라미터: {sorted(bad_q)}")
    bad_i = set(index_axis) - _INDEX_PARAMS
    if bad_i:
        raise ValueError(f"index_axis 에 허용되지 않은 파라미터: {sorted(bad_i)}")
    for m in query_axis.get("mode", []) or []:
        if m not in _VALID_MODES:
            raise ValueError(f"잘못된 mode 값: {m}")

    return _product(index_axis), _product(query_axis)


def collection_index_config(c: RagCollection) -> dict:
    """컬렉션의 인덱스 시점 설정 스냅샷(리더보드 표시·후보 비교용)."""
    return {
        "parse_strategy": c.parse_strategy,
        "chunk_strategy": c.chunk_strategy,
        "chunk_size": c.chunk_size,
        "chunk_overlap": c.chunk_overlap,
        "chunk_unit": c.chunk_unit,
        "embedding_provider": c.embedding_provider,
        "embedding_model": c.embedding_model,
        "distance_metric": c.distance_metric,
    }


# ---------------------------------------------------------------------------
# 생성
# ---------------------------------------------------------------------------

async def create_sweep(
    session: AsyncSession, dataset: RagEvalDataset, req: SweepCreateRequest, created_by: str | None
) -> SweepResponse:
    base_collection_id = req.base_collection_id or dataset.collection_id
    if not base_collection_id:
        raise ValueError("기준 컬렉션(base_collection_id)이 지정되지 않았습니다.")
    base = (await session.execute(
        select(RagCollection).where(RagCollection.id == base_collection_id)
    )).scalars().first()
    if not base:
        raise ValueError("기준 컬렉션을 찾을 수 없습니다.")

    item_count = (await session.execute(
        select(func.count()).where(RagEvalItem.dataset_id == dataset.id)
    )).scalar() or 0
    if item_count == 0:
        raise ValueError("데이터셋에 평가 항목이 없습니다.")

    if req.primary_metric not in (
        "hit_rate", "mrr", "faithfulness", "answer_relevance", "correctness", "composite"
    ):
        raise ValueError(f"잘못된 primary_metric: {req.primary_metric}")

    # P3 검증 — judge 게이팅은 judge 가 켜져 있어야 의미가 있다.
    if req.judge_top_n and not req.judge:
        raise ValueError("judge_top_n(judge 게이팅)은 judge 를 켰을 때만 사용할 수 있습니다.")
    if req.holdout_ratio and item_count < 2:
        raise ValueError("홀드아웃을 쓰려면 평가 항목이 최소 2개 이상이어야 합니다.")
    if req.primary_metric in ("faithfulness", "answer_relevance", "correctness") and not req.judge:
        raise ValueError(f"primary_metric '{req.primary_metric}' 는 judge 가 켜져 있어야 산출됩니다.")

    index_combos, query_combos = expand_search_space(req.search_space)
    total = len(index_combos) * len(query_combos)
    if total > req.max_runs:
        raise ValueError(
            f"조합 수 {total}개가 max_runs {req.max_runs}개를 초과합니다. "
            f"탐색 공간을 줄이거나 max_runs 를 높이세요."
        )

    sweep = RagEvalSweep(
        sweep_id=str(uuid.uuid4()), name=req.name, dataset_id=dataset.id,
        base_collection_id=base_collection_id, search_space=json.dumps(req.search_space or {}),
        primary_metric=req.primary_metric, judge=req.judge,
        judge_top_n=req.judge_top_n, holdout_ratio=req.holdout_ratio or 0.0,
        max_runs=req.max_runs, status="queued", total_runs=total, created_by=created_by,
    )
    session.add(sweep)
    await session.commit()
    await session.refresh(sweep)
    logger.info(
        "스윕 enqueue: %s (id=%d) index=%d × query=%d = %d Run, judge=%s top_n=%s holdout=%.2f",
        sweep.name, sweep.id, len(index_combos), len(query_combos), total,
        req.judge, req.judge_top_n, req.holdout_ratio or 0.0,
    )
    return sweep_resp(sweep)


# ---------------------------------------------------------------------------
# 점수 / 리더보드 / 응답
# ---------------------------------------------------------------------------

def composite_score(run: RagEvalRun) -> float | None:
    num = den = 0.0
    for key, w in _COMPOSITE_WEIGHTS.items():
        v = getattr(run, key, None)
        if v is not None:
            num += w * v
            den += w
    return round(num / den, 4) if den else None


def run_score(run: RagEvalRun, primary: str) -> float | None:
    if primary == "composite":
        return composite_score(run)
    return getattr(run, primary, None)


def sweep_resp(s: RagEvalSweep) -> SweepResponse:
    return SweepResponse(
        id=s.id, sweep_id=s.sweep_id, name=s.name, dataset_id=s.dataset_id,
        base_collection_id=s.base_collection_id, primary_metric=s.primary_metric,
        judge=s.judge, judge_top_n=s.judge_top_n, holdout_ratio=s.holdout_ratio or 0.0,
        max_runs=s.max_runs, status=s.status, total_runs=s.total_runs,
        completed_runs=s.completed_runs, best_run_id=s.best_run_id, error=s.error,
        created_by=s.created_by, created_at=s.created_at,
        started_at=s.started_at, finished_at=s.finished_at,
    )


def _parse_config(run: RagEvalRun) -> tuple[dict, dict]:
    try:
        cfg = json.loads(run.config_json) if run.config_json else {}
    except (ValueError, TypeError):
        cfg = {}
    return cfg.get("index", {}), cfg.get("query", {})


async def get_sweep(session: AsyncSession, sweep_id: str) -> RagEvalSweep | None:
    return (await session.execute(
        select(RagEvalSweep).where(RagEvalSweep.sweep_id == sweep_id)
    )).scalars().first()


async def list_sweeps(session: AsyncSession, dataset_id: int) -> list[SweepResponse]:
    rows = (await session.execute(
        select(RagEvalSweep).where(RagEvalSweep.dataset_id == dataset_id)
        .order_by(RagEvalSweep.created_at.desc())
    )).scalars().all()
    return [sweep_resp(s) for s in rows]


async def list_all_sweeps(session: AsyncSession, limit: int = 200) -> list[SweepResponse]:
    """전역 스윕 목록(최신순) — 잡 모니터링용."""
    rows = (await session.execute(
        select(RagEvalSweep).order_by(RagEvalSweep.created_at.desc()).limit(limit)
    )).scalars().all()
    return [sweep_resp(s) for s in rows]


async def _sweep_runs(session: AsyncSession, sweep: RagEvalSweep) -> list[RagEvalRun]:
    return list((await session.execute(
        select(RagEvalRun).where(RagEvalRun.sweep_id == sweep.id)
    )).scalars().all())


async def _sweep_items(session: AsyncSession, sweep: RagEvalSweep) -> list[RagEvalItem]:
    return list((await session.execute(
        select(RagEvalItem).where(RagEvalItem.dataset_id == sweep.dataset_id)
        .order_by(RagEvalItem.created_at)
    )).scalars().all())


async def _results_by_run(session: AsyncSession, sweep: RagEvalSweep) -> dict[int, list[RagEvalResult]]:
    """스윕의 모든 Run 의 항목별 결과를 {run.id: [RagEvalResult]} 로 적재(한 번에)."""
    rows = (await session.execute(
        select(RagEvalResult).join(RagEvalRun, RagEvalResult.run_id == RagEvalRun.id)
        .where(RagEvalRun.sweep_id == sweep.id)
    )).scalars().all()
    out: dict[int, list[RagEvalResult]] = {}
    for r in rows:
        out.setdefault(r.run_id, []).append(r)
    return out


async def leaderboard(session: AsyncSession, sweep: RagEvalSweep) -> LeaderboardResponse:
    runs = await _sweep_runs(session, sweep)
    items = await _sweep_items(session, sweep)
    split_map = assign_splits(items, sweep.holdout_ratio)
    results = await _results_by_run(session, sweep)
    primary = sweep.primary_metric
    use_holdout = bool(sweep.holdout_ratio and sweep.holdout_ratio > 0)

    def metric(rs, r, m):
        # 결과가 있으면 train 부분집합 기준, 없으면(아직 미실행) Run 집계로 폴백.
        return split_metric(rs, split_map, m, "train") if rs else run_score(r, m)

    scored = []
    for r in runs:
        rs = results.get(r.id, [])
        idx, qry = _parse_config(r)
        train = metric(rs, r, primary)
        holdout = split_metric(rs, split_map, primary, "holdout") if (rs and use_holdout) else None
        overfit = bool(
            use_holdout and train is not None and holdout is not None
            and (train - holdout) > _OVERFIT_GAP
        )
        judged = any(_result_value(x, "faithfulness") is not None for x in rs) or r.faithfulness is not None
        scored.append((r, train, holdout, overfit, judged, idx, qry, rs))

    # 점수 내림차순(None 은 뒤로), 동점이면 succeeded 우선
    scored.sort(key=lambda t: (t[1] is None, -(t[1] or 0.0), t[0].status != "succeeded"))

    rows: list[LeaderboardRow] = []
    for rank, (r, train, holdout, overfit, judged, idx, qry, rs) in enumerate(scored, start=1):
        rows.append(LeaderboardRow(
            run_id=r.run_id, rank=rank, status=r.status, index_config=idx, query_config=qry,
            collection_id=r.collection_id, ephemeral=bool(idx.get("_ephemeral")),
            hit_rate=metric(rs, r, "hit_rate"), mrr=metric(rs, r, "mrr"),
            faithfulness=metric(rs, r, "faithfulness"), answer_relevance=metric(rs, r, "answer_relevance"),
            correctness=metric(rs, r, "correctness"),
            score=train, holdout_score=holdout, overfit=overfit, judged=judged,
            is_best=(r.id == sweep.best_run_id),
        ))
    return LeaderboardResponse(
        sweep=sweep_resp(sweep), primary_metric=primary,
        holdout_ratio=sweep.holdout_ratio or 0.0, rows=rows,
    )


# ---------------------------------------------------------------------------
# 오케스트레이션 (스윕 워커가 호출)
# ---------------------------------------------------------------------------

async def _create_runs_for_collection(
    session: AsyncSession, sweep: RagEvalSweep, collection: RagCollection,
    index_config: dict, query_combos: list[dict], item_count: int,
) -> None:
    """한 후보 컬렉션 위에서 query 조합마다 평가 Run(queued)을 생성한다.

    judge 게이팅(judge_top_n)이 켜진 스윕이면 wave-1 은 judge=False(검색만, 쌈)로 만든다.
    이후 finalize 의 judging 단계에서 검색 상위 N개만 judge=True 로 재실행한다.
    """
    wave1_judge = bool(sweep.judge) and not sweep.judge_top_n
    for q in query_combos:
        mode = q.get("mode", "hybrid")
        top_k = int(q.get("top_k", settings.retrieval_top_k))
        rerank = bool(q.get("rerank", False))
        cfg = {"index": index_config, "query": {"mode": mode, "top_k": top_k, "rerank": rerank}}
        session.add(RagEvalRun(
            run_id=str(uuid.uuid4()), dataset_id=sweep.dataset_id, collection_id=collection.id,
            sweep_id=sweep.id, config_json=json.dumps(cfg, ensure_ascii=False),
            status="queued", mode=mode, distance_metric=collection.distance_metric,
            rerank=rerank, judge=wave1_judge, top_k=top_k, total_items=item_count,
            created_by=sweep.created_by,
        ))
    await session.commit()


async def _provision_ephemeral(
    session: AsyncSession, sweep: RagEvalSweep, base: RagCollection, index_combo: dict
) -> RagCollection:
    """index_combo 로 override 한 임시 후보 컬렉션을 만들고 base 의 원본 문서를 인제스천한다(P2).

    P2 에서 구현. 그전까지 index_axis 가 있으면 명확히 실패시킨다.
    """
    try:
        from app.evaluation.sweep_index import provision_ephemeral_collection
    except ImportError:
        raise ValueError("인덱스 축 스윕(P2)은 아직 지원되지 않습니다. 쿼리 축만 사용하세요.")
    return await provision_ephemeral_collection(session, sweep, base, index_combo)


async def plan_sweep(session: AsyncSession, sweep: RagEvalSweep) -> None:
    """queued 스윕을 계획한다: 후보 컬렉션 결정 → (즉시 또는 인덱싱 후) Run 생성."""
    base = (await session.execute(
        select(RagCollection).where(RagCollection.id == sweep.base_collection_id)
    )).scalars().first()
    if not base:
        raise ValueError("기준 컬렉션을 찾을 수 없습니다.")

    index_combos, query_combos = expand_search_space(json.loads(sweep.search_space or "{}"))
    item_count = (await session.execute(
        select(func.count()).where(RagEvalItem.dataset_id == sweep.dataset_id)
    )).scalar() or 0
    base_index = collection_index_config(base)

    candidates: list[dict] = []
    needs_indexing = False
    for combo in index_combos:
        if not combo:  # 빈 조합 = base 그대로(P1, 재인덱싱 0)
            candidates.append({"collection_id": base.id, "index_config": base_index, "ephemeral": False})
        else:          # P2: 임시 컬렉션 생성 + 인제스천
            ephem = await _provision_ephemeral(session, sweep, base, combo)
            candidates.append({
                "collection_id": ephem.id,
                "index_config": {**base_index, **combo, "_ephemeral": True},
                "ephemeral": True,
            })
            needs_indexing = True

    sweep.candidate_collections = json.dumps(candidates, ensure_ascii=False)
    sweep.started_at = func.now()

    if needs_indexing:
        # 후보 인덱싱 완료를 기다렸다가(워커의 indexing 단계) Run 을 만든다.
        sweep.status = "indexing"
        await session.commit()
        logger.info("스윕 %s: 임시 후보 %d개 인덱싱 대기", sweep.sweep_id, len(candidates))
    else:
        for cand in candidates:
            await _create_runs_for_collection(
                session, sweep, base, cand["index_config"], query_combos, item_count
            )
        sweep.status = "running"
        await session.commit()
        logger.info("스윕 %s: Run %d개 생성(running)", sweep.sweep_id, sweep.total_runs)


async def start_runs_after_indexing(session: AsyncSession, sweep: RagEvalSweep) -> bool:
    """indexing 상태 스윕 — 후보 컬렉션이 모두 인덱싱 완료면 Run 을 만들고 running 으로.

    반환: 아직 인덱싱 중이면 False, Run 생성 완료면 True.
    """
    from app.documents.models import RagDocument

    candidates = json.loads(sweep.candidate_collections or "[]")
    _, query_combos = expand_search_space(json.loads(sweep.search_space or "{}"))
    item_count = (await session.execute(
        select(func.count()).where(RagEvalItem.dataset_id == sweep.dataset_id)
    )).scalar() or 0

    # 모든 후보 컬렉션의 문서가 처리 끝(indexed/failed)인지 확인
    for cand in candidates:
        pending = (await session.execute(
            select(func.count()).where(
                RagDocument.collection_id == cand["collection_id"],
                RagDocument.status.in_(("registered", "processing")),
            )
        )).scalar() or 0
        if pending > 0:
            return False  # 아직 인덱싱 중

    for cand in candidates:
        coll = (await session.execute(
            select(RagCollection).where(RagCollection.id == cand["collection_id"])
        )).scalars().first()
        if coll:
            await _create_runs_for_collection(
                session, sweep, coll, cand["index_config"], query_combos, item_count
            )
    sweep.status = "running"
    await session.commit()
    logger.info("스윕 %s: 인덱싱 완료 → Run %d개 생성(running)", sweep.sweep_id, sweep.total_runs)
    return True


async def finalize_if_done(session: AsyncSession, sweep: RagEvalSweep) -> bool:
    """running/judging 스윕을 전진시킨다.

    - running 단계: 모든 Run 이 끝나면
        · judge 게이팅(judge_top_n) 설정 시 → 검색(train) 상위 N개를 judge=True 로 재실행하고 judging 으로.
        · 아니면 → 베스트(train primary) 선정 + 정리 + succeeded.
    - judging 단계: 재실행 Run 까지 모두 끝나면 베스트 선정 + 정리 + succeeded.

    반환: 스윕이 완전히 끝났으면 True.
    """
    runs = await _sweep_runs(session, sweep)
    settled = [r for r in runs if r.status in ("succeeded", "failed")]
    sweep.completed_runs = len(settled)

    if not (sweep.total_runs > 0 and len(settled) >= sweep.total_runs):
        await session.commit()
        return False

    items = await _sweep_items(session, sweep)
    split_map = assign_splits(items, sweep.holdout_ratio)
    results = await _results_by_run(session, sweep)
    succeeded = [r for r in runs if r.status == "succeeded"]

    def train_score(r: RagEvalRun, m: str) -> float | None:
        rs = results.get(r.id, [])
        return split_metric(rs, split_map, m, "train") if rs else run_score(r, m)

    # judge 게이팅: running 에서 1차 완료 → 검색 상위 N개만 judge 재실행.
    if sweep.status == "running" and sweep.judge and sweep.judge_top_n:
        gate = _gate_metric(sweep.primary_metric)
        ranked = sorted(succeeded, key=lambda r: (train_score(r, gate) or -1.0), reverse=True)
        topn = ranked[: sweep.judge_top_n]
        for r in topn:
            # 재실행: 기존 결과 삭제 후 judge=True 로 다시 큐잉(검색→생성→judge).
            await session.execute(sql_delete(RagEvalResult).where(RagEvalResult.run_id == r.id))
            r.judge = True
            r.status = "queued"
            r.completed_items = 0
            r.faithfulness = r.answer_relevance = r.correctness = None
        sweep.status = "judging"
        await session.commit()
        logger.info(
            "스윕 %s: 검색(%s) 상위 %d개 judge 재실행 → judging",
            sweep.sweep_id, gate, len(topn),
        )
        return False

    # 최종 선정 — train primary 점수 최댓값.
    best = None
    if succeeded:
        best = max(succeeded, key=lambda r: (train_score(r, sweep.primary_metric) or -1.0))
    sweep.best_run_id = best.id if best else None
    await _cleanup_ephemeral(session, sweep)
    sweep.status = "succeeded"
    sweep.finished_at = func.now()
    await session.commit()
    logger.info(
        "스윕 완료: %s — best run=%s (train %s=%s)",
        sweep.sweep_id, best.run_id if best else None,
        sweep.primary_metric, train_score(best, sweep.primary_metric) if best else None,
    )
    return True


async def _cleanup_ephemeral(session: AsyncSession, sweep: RagEvalSweep) -> None:
    """스윕이 만든 임시 후보 컬렉션을 삭제(청크·문서 CASCADE)."""
    ephem = list((await session.execute(
        select(RagCollection).where(RagCollection.ephemeral_sweep_id == sweep.id)
    )).scalars().all())
    for c in ephem:
        await session.delete(c)
    if ephem:
        await session.commit()
        logger.info("스윕 %s: 임시 컬렉션 %d개 정리", sweep.sweep_id, len(ephem))


async def cancel_sweep(session: AsyncSession, sweep: RagEvalSweep) -> None:
    """스윕 취소 — 대기 Run 제거 + 임시 컬렉션 정리 + canceled."""
    await session.execute(
        sql_delete(RagEvalRun).where(
            RagEvalRun.sweep_id == sweep.id, RagEvalRun.status == "queued"
        )
    )
    await _cleanup_ephemeral(session, sweep)
    sweep.status = "canceled"
    sweep.finished_at = func.now()
    await session.commit()


async def apply_config(session: AsyncSession, sweep: RagEvalSweep, run: RagEvalRun) -> dict:
    """우승 Run 의 설정을 base 컬렉션에 적용. 인덱스 설정이 바뀌면 재인덱싱.

    반환: {applied_fields, reindexed, recommended_runtime, collection_id}
    """
    from app.collections.schemas import (
        ChunkStrategy, ChunkUnit, CollectionReindexRequest, DistanceMetric, ParseStrategy,
    )
    from app.collections.service import reindex_collection

    index_cfg, query_cfg = _parse_config(run)
    base = (await session.execute(
        select(RagCollection).where(RagCollection.id == sweep.base_collection_id)
    )).scalars().first()
    if not base:
        raise ValueError("기준 컬렉션을 찾을 수 없습니다.")

    # 인덱스 시점 설정 중 base 와 다른 것만 추려 재인덱싱 요청 구성
    changed: list[str] = []
    reindex_kwargs: dict = {}
    mapping = [
        ("parse_strategy", ParseStrategy), ("chunk_strategy", ChunkStrategy),
        ("chunk_unit", ChunkUnit), ("distance_metric", DistanceMetric),
    ]
    for field, enum_cls in mapping:
        val = index_cfg.get(field)
        if val is not None and getattr(base, field) != val:
            reindex_kwargs[field] = enum_cls(val)
            changed.append(field)
    for field in ("chunk_size", "chunk_overlap"):
        val = index_cfg.get(field)
        if val is not None and getattr(base, field) != val:
            reindex_kwargs[field] = val
            changed.append(field)

    reindexed = False
    if reindex_kwargs:
        await reindex_collection(session, base.id, CollectionReindexRequest(**reindex_kwargs))
        reindexed = True

    return {
        "applied_fields": changed,
        "reindexed": reindexed,
        "recommended_runtime": query_cfg,  # mode/top_k/rerank — 쿼리 시점 권장값
        "collection_id": base.id,
    }
