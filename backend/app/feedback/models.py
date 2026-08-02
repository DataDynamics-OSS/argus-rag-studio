# SPDX-License-Identifier: Apache-2.0
"""피드백(Feedback) 모듈의 SQLAlchemy ORM 모델.

``RagFeedback``: 답변에 대한 사용자 평가(👍/👎) + 코멘트/수정답변. 트레이스(rag_query_traces)에
연결되며, 골든셋으로 승격(promote)되면 ``status='promoted'`` + ``promoted_item_id`` 가 채워진다.
"""

from sqlalchemy import Column, DateTime, Integer, String, Text, func

from app.core.database import Base


class RagFeedback(Base):
    __tablename__ = "rag_feedback"

    id = Column(Integer, primary_key=True, autoincrement=True)
    feedback_id = Column(String(36), nullable=False, unique=True)
    trace_id = Column(String(36))  # rag_query_traces.trace_id (선택)
    collection_id = Column(Integer)
    query = Column(Text, nullable=False)
    answer = Column(Text)
    rating = Column(String(4), nullable=False)  # up | down
    comment = Column(Text)
    corrected_answer = Column(Text)  # 사용자가 제시한 더 나은 답변(승격 시 expected_answer)
    expected_sources = Column(Text)  # 줄바꿈 구분 기대 출처(선택)
    status = Column(String(12), nullable=False, default="new")  # new | promoted | dismissed
    promoted_item_id = Column(Integer)  # 승격으로 생성된 rag_eval_items.id
    created_by = Column(String(200))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
