# SPDX-License-Identifier: Apache-2.0
"""AI-Hub 손글씨 OCR 라벨 포맷 ↔ 내부 표현 변환 + 코드값 매핑.

⚠️  코드값(정수) 의 의미는 공개 샘플과 공개 레포(ssuai/mocr) 기반의 **best-effort 추정**이다.
    AI-Hub 공식 "구축활용가이드(규격 정의서)" 로 반드시 교차검증해 교정할 것.
    매핑이 이 파일 한 곳에 격리되어 있으므로, 정의서 확보 시 여기만 수정하면 된다.

AI-Hub bbox 좌표 규칙(특이점):
    각 박스를 ``x = [x1, x1, x2, x2]``, ``y = [y1, y2, y1, y2]`` 로 4개씩 저장한다.
    실제로는 좌상단(x1,y1) / 우하단(x2,y2) 두 점만으로 결정되는 축정렬 사각형이다.
"""

import os

# ---------------------------------------------------------------------------
# 코드값 매핑 (best-effort 추정 — 정의서로 교정 필요)
#   키: 정수 코드, 값: 사람이 읽는 라벨
# ---------------------------------------------------------------------------

# 데이터셋 카테고리(도메인/출처).
DATASET_CATEGORY: dict[int, str] = {0: "일반 손글씨", 1: "서식 손글씨"}

# 데이터셋 용도(데이터 분할) — 학습/검증/시험 Phase.
DATASET_TYPE: dict[int, str] = {0: "학습용(Train)", 1: "검증용(Validation)", 2: "시험용(Test)"}

WRITER_SEX: dict[int, str] = {0: "남성", 1: "여성"}
PEN_TYPE: dict[int, str] = {0: "볼펜", 1: "연필", 2: "수성펜"}
MEDIA_TYPE: dict[int, str] = {0: "종이", 1: "디지털 기기"}
WRITTEN_CONTENT: dict[int, str] = {0: "일반 텍스트", 1: "숫자 조합"}
OBJECT_RECOGNITION: dict[int, str] = {0: "일반 문자(OCR)", 1: "특정 객체 포함"}
TEXT_LANGUAGE: dict[int, str] = {0: "한국어", 1: "영어", 2: "다국어"}
BACKGROUND: dict[int, str] = {0: "흰색", 1: "무늬/격자"}

# 자유 입력(문자열) 필드 — 참고용 후보값
PEN_COLOR_CHOICES: list[str] = ["black", "blue", "red"]
ACQUISITION_LOCATION_CHOICES: list[str] = ["공공", "민간", "자택"]


def default_meta() -> dict:
    """새 이미지의 기본 메타 블록 템플릿(Annotation/Dataset/Images).

    width/height/identifier/type 은 업로드/내보내기 시점에 실제 값으로 덮어쓴다.
    """
    return {
        "Annotation": {
            "object_recognition": 0,
            "text_language": 0,
        },
        "Dataset": {
            "category": 0,
            "identifier": "",
            "label_path": "",
            "name": "대용량 손글씨 데이터셋",
            "src_path": "",
            "type": 1,
        },
        "Images": {
            "acquistion_location": "공공",
            "application_field": "필사본",
            "background": 0,
            "data_captured": "",
            "media_type": 0,
            "pen_color": "black",
            "pen_type": 0,
            "writer_age": 0,
            "writer_sex": 0,
            "written_content": 0,
        },
    }


# ---------------------------------------------------------------------------
# bbox 좌표 변환
# ---------------------------------------------------------------------------

def to_aihub_bbox(seq: int, data: str, x1: int, y1: int, x2: int, y2: int) -> dict:
    """내부 (x1,y1,x2,y2) → AI-Hub bbox 항목."""
    return {
        "data": data,
        "id": seq,
        "x": [x1, x1, x2, x2],
        "y": [y1, y2, y1, y2],
    }


def from_aihub_bbox(obj: dict) -> dict:
    """AI-Hub bbox 항목 → 내부 표현. 회전 박스 대비 min/max 로 정규화한다."""
    xs = [int(v) for v in obj.get("x", [])]
    ys = [int(v) for v in obj.get("y", [])]
    if not xs or not ys:
        raise ValueError("bbox 좌표(x/y)가 비어 있습니다.")
    return {
        "seq": int(obj.get("id", 0)),
        "data": str(obj.get("data", "")),
        "x1": min(xs),
        "y1": min(ys),
        "x2": max(xs),
        "y2": max(ys),
    }


# ---------------------------------------------------------------------------
# 전체 문서 직렬화 / 역직렬화
# ---------------------------------------------------------------------------

def build_export(
    *,
    filename: str,
    width: int,
    height: int,
    meta: dict | None,
    boxes: list,
) -> dict:
    """내부 데이터 → AI-Hub JSON(dict).

    ``meta`` 의 Annotation/Dataset/Images 블록을 기반으로 하되, width/height/identifier/
    type/bbox 는 실제 값으로 덮어써 정합성을 보장한다. ``boxes`` 는 ``seq`` 오름차순 정렬.
    """
    meta = meta or default_meta()
    stem, ext = os.path.splitext(filename)
    ext = (ext.lstrip(".") or "png").lower()

    images_block = dict(meta.get("Images", {}))
    images_block.setdefault("identifier", stem)
    images_block["width"] = width
    images_block["height"] = height
    images_block["type"] = ext

    dataset_block = dict(meta.get("Dataset", {}))
    if not dataset_block.get("identifier"):
        # 파일명 규칙(IMG_OCR_53_4PO_09451)에서 데이터셋 식별자(IMG_OCR_53)를 추정
        parts = stem.split("_")
        dataset_block["identifier"] = "_".join(parts[:3]) if len(parts) >= 3 else stem

    ordered = sorted(boxes, key=lambda b: b.seq)
    bbox = [to_aihub_bbox(b.seq, b.data, b.x1, b.y1, b.x2, b.y2) for b in ordered]

    return {
        "Annotation": dict(meta.get("Annotation", {})),
        "Dataset": dataset_block,
        "Images": images_block,
        "bbox": bbox,
    }


def parse_import(payload: dict) -> tuple[dict, list[dict], int, int]:
    """AI-Hub JSON → (meta, 내부 boxes, width, height).

    bbox 의 ``id`` 가 비어있거나 중복이면 1부터 재부여한다.
    """
    meta = {
        "Annotation": dict(payload.get("Annotation", {})),
        "Dataset": dict(payload.get("Dataset", {})),
        "Images": dict(payload.get("Images", {})),
    }
    images_block = meta["Images"]
    width = int(images_block.get("width", 0) or 0)
    height = int(images_block.get("height", 0) or 0)

    raw_boxes = [from_aihub_bbox(b) for b in payload.get("bbox", [])]
    seqs = [b["seq"] for b in raw_boxes]
    needs_reseq = any(s <= 0 for s in seqs) or len(set(seqs)) != len(seqs)
    if needs_reseq:
        for i, b in enumerate(raw_boxes, start=1):
            b["seq"] = i
    return meta, raw_boxes, width, height
