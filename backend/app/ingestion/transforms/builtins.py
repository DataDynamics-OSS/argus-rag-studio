# SPDX-License-Identifier: Apache-2.0
"""기본 제공 인제스천 보강(transform)들. 새 보강은 여기(또는 별도 모듈)에 추가하고 등록만 하면 된다."""

from app.ingestion.chunking import _clean_table_rows
from app.ingestion.transforms.base import Transform, register_transform


@register_transform
class TableRowCleanup(Transform):
    id = "table_row_cleanup"
    label = "표 빈칸 정리"
    description = "마크다운 표의 빈 셀/구분선 행을 제거하고 내용 셀을 압축한다(양식 문서 검색 노이즈↓)."
    phase = "post_parse"

    def apply(self, text, cfg, ctx=None):
        return _clean_table_rows(text or "")


@register_transform
class DropTinyChunks(Transform):
    id = "drop_tiny_chunks"
    label = "작은 청크 제거"
    description = "지정한 문자수 미만 청크를 제거한다(표 부스러기·노이즈 제거). 전부 작으면 원본 유지."
    phase = "post_chunk"
    config_schema = {"min_chars": {"type": "int", "default": 50, "min": 1, "max": 2000}}

    def apply(self, pieces, cfg, ctx=None):
        n = int(cfg.get("min_chars", 50) or 50)
        kept = [p for p in pieces if len((p.get("text") or "").strip()) >= n]
        return kept or pieces  # 전부 걸러지면 안전하게 원본 유지
