// AI-Hub 손글씨 OCR 라벨 — 코드값 ↔ 라벨 매핑 (프론트 표시용)
//
// ⚠️  코드값의 의미는 공개 샘플/레포 기반 best-effort 추정이다. AI-Hub 공식
//     "구축활용가이드(규격 정의서)" 로 교차검증해 교정할 것. 백엔드의
//     app/annotations/aihub.py 와 의미가 일치해야 한다(둘 다 정의서로 교정).

export interface CodeOption {
  value: number
  label: string
}

const opt = (m: Record<number, string>): CodeOption[] =>
  Object.entries(m).map(([v, label]) => ({ value: Number(v), label }))

// 데이터셋 카테고리(도메인/출처).
export const DATASET_CATEGORY = opt({ 0: "일반 손글씨", 1: "서식 손글씨" })

// 데이터셋 용도(데이터 분할) — 학습/검증/시험 Phase.
export const DATASET_TYPE = opt({ 0: "학습용(Train)", 1: "검증용(Validation)", 2: "시험용(Test)" })

export const WRITER_SEX = opt({ 0: "남성", 1: "여성" })
export const PEN_TYPE = opt({ 0: "볼펜", 1: "연필", 2: "수성펜" })
export const MEDIA_TYPE = opt({ 0: "종이", 1: "디지털 기기" })
export const WRITTEN_CONTENT = opt({ 0: "일반 텍스트", 1: "숫자 조합" })
export const OBJECT_RECOGNITION = opt({ 0: "일반 문자(OCR)", 1: "특정 객체 포함" })
export const TEXT_LANGUAGE = opt({ 0: "한국어", 1: "영어", 2: "다국어" })
export const BACKGROUND = opt({ 0: "흰색", 1: "무늬/격자" })

// 자유 입력(문자열) 필드의 추천 후보값
export const PEN_COLOR_CHOICES = ["black", "blue", "red"]
export const ACQUISITION_LOCATION_CHOICES = ["공공", "민간", "자택"]
