# SPDX-License-Identifier: Apache-2.0
"""모델 레지스트리 시드 — 순수 데이터(DB·설정 임포트 없음).

설계: design/model-registry.md §3.1. 이 목록은 두 곳에서 쓰인다:

  1. DB 시드 — 기동 시 ``rag_model_registry`` 에 없는 항목을 투입(builtin).
  2. 외부망 폴백 — ``scripts/pack_model.py`` 는 DB 없는 외부망 머신에서 돌므로
     이 목록(+ 명시 ``--repo`` 인자)만으로 동작한다.

**원칙: 여기는 동작에 꼭 필요한 최소 셋만.** 기본 VLM(DEFAULT_VLM_NAME)·운영
임베딩/리랭커·검출처럼 코드가 폴백으로 알아야 하는 항목만 남기고, 추천 카탈로그성
모델은 SQL DDL 시드(packaging/config/argus-rag-studio-postgresql.sql 의
rag_model_registry 카탈로그 섹션)가 단일 출처다 — 소스 수정 없이 DB 로 관리한다.

note 서식: 1행 = 핵심 요약(목록 표시), 2행~ = 특징·추천 이유·제약(툴팁 표시).

target 은 kind 로 정해진다: vlm/detection 은 flat(vLLM 로컬 경로/Paddle 디렉터리 서빙),
embedding/reranker 는 hf-cache(sentence-transformers 가 이름으로 캐시 조회).
"""

from __future__ import annotations

KIND_TARGETS: dict[str, str] = {
    "vlm": "flat",
    "embedding": "hf-cache",
    "reranker": "hf-cache",
    "detection": "flat",
}

DEFAULT_VLM_NAME = "qwen2-vl-7b"

# params: kind 별 부가 정보 — vlm: max_len(서빙 인자), embedding: dim(차원),
# 공통: approx_gb(반입 용량 안내).
SEED_MODELS: list[dict] = [
    # vlm — name 은 served-model-name(= image_classification.model 값)
    {"kind": "vlm", "name": "qwen2-vl-7b", "repo": "Qwen/Qwen2-VL-7B-Instruct",
     "params": {"max_len": 8192, "approx_gb": 16},
     "note": "기본 — 현행 운영 모델\n"
             "Qwen 2세대 비전-언어 모델(7B, Apache-2.0). 문서 이미지 OCR·표/차트 해석이 "
             "안정적이고 한국어 문서 인식 품질이 검증됨. vLLM 서빙 기준 VRAM 약 20GB(권장 24GB+)."},
    # embedding — 확장 서버(192.0.2.48:8090)가 서빙 중인 운영 세트
    {"kind": "embedding", "name": "multilingual-e5-large", "repo": "intfloat/multilingual-e5-large",
     "params": {"approx_gb": 2.2, "dim": 1024},
     "note": "한국어 포함 다국어 — HWP/PPT 지식베이스 사용\n"
             "intfloat 다국어 임베딩(560M, dim 1024, MIT). 약 100개 언어 학습으로 한국어 검색 "
             "무난 — 현행 운영 기본 모델."},
    {"kind": "embedding", "name": "mxbai-embed-large-v1", "repo": "mixedbread-ai/mxbai-embed-large-v1",
     "params": {"approx_gb": 1.3, "dim": 1024},
     "note": "영문 — DOC 지식베이스 사용\n"
             "mixedbread.ai 영문 임베딩(335M, dim 1024, Apache-2.0). 영문 MTEB 상위권."},
    # reranker
    {"kind": "reranker", "name": "bge-reranker-v2-m3", "repo": "BAAI/bge-reranker-v2-m3",
     "params": {"approx_gb": 2.2},
     "note": "다국어 cross-encoder\n"
             "BAAI bge-m3 기반 리랭커(568M, Apache-2.0). 한국어 포함 다국어 재순위의 표준적 "
             "선택 — 현행 운영 모델."},
    # detection — Paddle 저장소 배포(pack_model.py 미지원, 수동 반입)
    {"kind": "detection", "name": "paddleocr-det-rec", "repo": "PaddlePaddle/PaddleOCR",
     "source": "paddle", "params": {"approx_gb": 0.1},
     "note": "det/rec 모델 — Paddle 저장소 배포, 수동 반입(볼륨에 직접 전개)\n"
             "PaddleOCR 텍스트 검출/인식 모델 — bbox 자동 검출 서버가 사용. pack_model "
             "미지원이므로 볼륨에 직접 전개한다."},
]


def seed_entry(m: dict) -> dict:
    """시드 1개를 전체 필드로 정규화 — source/target/revision 기본값 채움."""
    return {
        "kind": m["kind"], "name": m["name"], "repo": m["repo"],
        "revision": m.get("revision", "main"),
        "source": m.get("source", "hf"),
        "target": m.get("target") or KIND_TARGETS.get(m["kind"], "hf-cache"),
        "params": dict(m.get("params") or {}),
        "note": m.get("note", ""),
    }
