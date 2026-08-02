# SPDX-License-Identifier: Apache-2.0
"""생성 서비스 — 컨텍스트 조립 + RAG 프롬프트 + 인용 그라운딩.

검색된 청크를 ``[1] ... [N]`` 으로 번호 매겨 컨텍스트로 패킹하고, 모델이 문맥에 근거해
답하며 ``[n]`` 으로 출처를 인용하도록 지시한다(가드레일: 문맥에 없으면 모른다고 답한다).
답변 본문에 등장한 ``[n]`` 마커를 청크와 매핑해 citations 로 돌려준다.
"""

import re

from app.generation.schemas import Citation
from app.retrieval.schemas import ChunkHit

RAG_SYSTEM = (
    "당신은 제공된 '참고 문맥'에만 근거해 사용자 질문에 답하는 한국어 어시스턴트입니다.\n"
    "- 문맥에 근거가 있으면, 사용한 출처를 문장 끝에 [1], [2] 처럼 번호로 인용하세요.\n"
    "- 문맥에서 답을 찾을 수 없으면 추측하지 말고 '제공된 문서에서 답을 찾을 수 없습니다.'라고 답하세요.\n"
    "- 간결하고 정확하게 답하세요."
)


def build_context(hits: list[ChunkHit]) -> str:
    """검색 청크를 번호 매긴 컨텍스트 블록으로 만든다."""
    parts = []
    for i, h in enumerate(hits, start=1):
        src = h.document_name + (f" · {h.section_path}" if h.section_path else "")
        parts.append(f"[{i}] (출처: {src})\n{h.text}")
    return "\n\n".join(parts)


def build_messages(hits: list[ChunkHit], history: list[dict]) -> list[dict]:
    """RAG 메시지 구성: system(지시 + 컨텍스트) + 대화 history(user/assistant)."""
    context = build_context(hits) if hits else "(관련 문맥 없음)"
    system = f"{RAG_SYSTEM}\n\n참고 문맥:\n{context}"
    return [{"role": "system", "content": system}, *history]


def extract_citations(answer: str, hits: list[ChunkHit]) -> list[Citation]:
    """답변에 등장한 [n] 마커를 청크와 매핑한다."""
    markers = sorted({int(m) for m in re.findall(r"\[(\d+)\]", answer)})
    citations: list[Citation] = []
    for marker in markers:
        if 1 <= marker <= len(hits):
            h = hits[marker - 1]
            citations.append(Citation(
                marker=marker, chunk_id=h.chunk_id, document_id=h.document_id,
                document_name=h.document_name, seq=h.seq, text=h.text,
            ))
    return citations
