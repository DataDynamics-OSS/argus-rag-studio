# SPDX-License-Identifier: Apache-2.0
"""평가 지표 — 검색 지표(계산식) + 생성 지표(LLM-as-judge).

검색 지표는 LLM 없이 계산한다(기대 출처 문서명 매칭). 생성 지표는 LLM 판정관(judge)이
faithfulness/answer_relevance/correctness 를 0~1 로 채점한다(judge=true 일 때만, 실패 시 None).
"""

import json
import logging
import re

logger = logging.getLogger(__name__)


def retrieval_metrics(
    expected_sources: list[str], retrieved_docs: list[str]
) -> tuple[bool | None, float | None]:
    """기대 출처가 검색 결과에 등장하는지로 hit / reciprocal_rank 를 계산한다.

    - hit: 기대 출처(문서명 부분문자열) 중 하나라도 검색된 문서에 포함되면 True
    - reciprocal_rank: 기대 출처가 처음 등장한 순위의 역수(1-based), 없으면 0.0
    기대 출처가 비어 있으면 (None, None) — 검색 지표 산출 불가.
    """
    if not expected_sources:
        return None, None
    expected = [s.strip().lower() for s in expected_sources if s.strip()]
    if not expected:
        return None, None
    best_rank: int | None = None
    for rank, doc in enumerate(retrieved_docs):
        dl = (doc or "").lower()
        if any(exp in dl for exp in expected):
            best_rank = rank
            break
    if best_rank is None:
        return False, 0.0
    return True, 1.0 / (best_rank + 1)


_JUDGE_SYSTEM = (
    "당신은 RAG 시스템의 답변 품질을 엄격하게 채점하는 평가관입니다. "
    "각 항목을 0.0~1.0 사이 숫자로 채점하고 JSON 으로만 답하세요."
)


async def judge_generation(
    question: str, context: str, answer: str, expected_answer: str | None
) -> dict[str, float | None]:
    """LLM-as-judge — 생성 답변을 채점한다.

    - faithfulness: 답변이 제공된 문맥에 충실한가(환각 없음)
    - answer_relevance: 답변이 질문에 적절히 답하는가
    - correctness: 기대답변과 의미적으로 일치하는가(기대답변이 있을 때만)
    실패 시 모든 값 None.
    """
    from app.llm.service import complete

    rubric = (
        "다음을 0.0~1.0 으로 채점하세요:\n"
        "- faithfulness: 답변이 '문맥'에 근거하는가(문맥에 없는 주장=낮음)\n"
        "- answer_relevance: 답변이 '질문'에 직접 답하는가\n"
    )
    correctness_line = ""
    if expected_answer:
        rubric += "- correctness: 답변이 '기대답변'과 의미적으로 일치하는가\n"
        correctness_line = f"\n기대답변:\n{expected_answer}\n"
    fmt = '{"faithfulness": 0.0, "answer_relevance": 0.0'
    fmt += ', "correctness": 0.0}' if expected_answer else "}"

    prompt = (
        f"{rubric}\n질문:\n{question}\n\n문맥:\n{context}\n{correctness_line}\n답변:\n{answer}\n\n"
        f"JSON 으로만 답하세요(예: {fmt}):"
    )
    try:
        out = await complete([
            {"role": "system", "content": _JUDGE_SYSTEM},
            {"role": "user", "content": prompt},
        ])
        match = re.search(r"\{.*\}", out, re.DOTALL)
        data = json.loads(match.group(0)) if match else {}
    except Exception as e:
        logger.warning("LLM judge 실패: %s", e)
        return {"faithfulness": None, "answer_relevance": None, "correctness": None}

    def _clip(v):
        try:
            return max(0.0, min(1.0, float(v)))
        except (TypeError, ValueError):
            return None

    return {
        "faithfulness": _clip(data.get("faithfulness")),
        "answer_relevance": _clip(data.get("answer_relevance")),
        "correctness": _clip(data.get("correctness")) if expected_answer else None,
    }
