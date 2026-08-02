"use client"

import ReactMarkdown, { type Components } from "react-markdown"
import remarkGfm from "remark-gfm"

// 어노테이션 작성지침 — 라벨링 지침 + 메타데이터 지침(AI-Hub OCR JSON 구조).
// 라벨링 지침은 단순 항목 배열, 메타데이터 지침은 마크다운 문서로 관리한다.

/** 라벨링(박싱) 지침 — 순서 있는 단순 항목. */
const LABELING_GUIDE: string[] = [
  "글자의 영역을 최대한 여백없이 작성",
  "한글, 영문, 한자, 숫자 및 혼합 텍스트를 라벨링함",
  "기호는 라벨링에서 제외하고, 띄어쓰기는 분리하여 라벨링함",
  "특수 알파벳은 개별 박싱 후 기호로 처리",
  "영문 필기체는 박싱 후 일반 영문으로 입력",
  "글자로 인식할 수 있는 타이포그래피는 박싱 후 원래 글자로 입력",
  "텍스트가 1획 이상 가려져있거나 삭제되어 있을 경우 박싱하지 않음",
  "글자가 겹쳐진 경우 겹친 글자는 더 선명한 글자를 기준으로 박싱, 비슷한 색상, 비슷한 투명도인 경우 박싱하지 않음",
  "가로, 세로 레이아웃은 별도로 박싱함",
  "글자 크기가 다른 경우 개별 단어로 박싱함",
  "원형 간판과 같이 원형으로 기울어진 텍스트는 적당한 구간으로 분리하여 박싱",
]

// 메타데이터 지침 — AI-Hub OCR 데이터셋 JSON 구조/매핑. 백틱(`)·따옴표(")가 많아
// 템플릿 리터럴 충돌을 피하려고 줄 배열로 작성한 뒤 개행으로 합친다.
const METADATA_MARKDOWN = [
  "# AI Hub OCR 데이터셋 JSON 구조 및 매핑 가이드",
  "",
  "## 1. Annotation (주석 정보)",
  "",
  "데이터셋의 전반적인 라벨링 기준을 정의합니다.",
  "",
  "| 항목명 | 의미 | 들어갈 수 있는 값 (예시) |",
  "| :--- | :--- | :--- |",
  "| `object_recognition` | 개체 인식 유형 | `0`: 일반 문자(OCR), `1`: 특정 객체 포함 |",
  "| `text_language` | 라벨링 텍스트 언어 | `0`: 한국어, `1`: 영어, `2`: 다국어 |",
  "",
  "---",
  "",
  "## 2. Dataset (데이터셋 메타데이터)",
  "",
  "데이터셋 전체의 관리 정보 및 경로 정보를 담고 있습니다.",
  "",
  "| 항목명 | 의미 | 들어갈 수 있는 값 (예시) |",
  "| :--- | :--- | :--- |",
  "| `category` | 데이터셋 카테고리 | `0`: 일반 손글씨, `1`: 서식 손글씨 |",
  '| `identifier` | 데이터셋 고유 식별자 | `"IMG_OCR_53"` |',
  '| `label_path` | 라벨링 파일 저장 경로 | `"HW_OCR/4.Validation/..."` |',
  '| `name` | 데이터셋 명칭 | `"대용량 손글씨 데이터셋"` |',
  '| `src_path` | 원본 이미지 저장 경로 | `"HW_OCR/4.Validation/..."` |',
  "| `type` | 데이터셋 용도 | `0`: 학습용, `1`: 검증용, `2`: 시험용 |",
  "",
  "---",
  "",
  "## 3. Images (이미지 및 작성자 정보)",
  "",
  "데이터 수집 환경 및 작성자의 정보를 포함합니다.",
  "",
  "| 항목명 | 의미 | 들어갈 수 있는 값 (예시) |",
  "| :--- | :--- | :--- |",
  '| `acquistion_location` | 수집 장소 | `"공공"`, `"민간"`, `"자택"` |',
  '| `application_field` | 활용 분야 | `"필사본"`, `"신청서"` |',
  "| `background` | 배경 특징 | `0`: 흰색, `1`: 무늬/격자 |",
  '| `data_captured` | 수집 일자 | `"2021.10.05"` |',
  "| `height` / `width` | 이미지 해상도 | `3505`, `2475` (정수) |",
  '| `identifier` | 이미지 고유 ID | `"IMG_OCR_53_4PO_09451"` |',
  "| `media_type` | 기록 매체 유형 | `0`: 종이, `1`: 디지털 기기 |",
  '| `pen_color` | 필기도구 색상 | `"black"`, `"blue"`, `"red"` |',
  "| `pen_type` | 필기도구 종류 | `0`: 볼펜, `1`: 연필, `2`: 수성펜 |",
  '| `type` | 이미지 확장자 | `"png"`, `"jpg"` |',
  "| `writer_age` | 작성자 연령 | `25` (정수) |",
  "| `writer_sex` | 작성자 성별 | `0`: 남성, `1`: 여성 |",
  "| `written_content` | 작성 내용 성격 | `0`: 일반 텍스트, `1`: 숫자 조합 |",
  "",
  "---",
  "",
  "## 4. bbox (바운딩 박스 정보)",
  "",
  "이미지 내 텍스트의 영역(좌표)과 정답 값을 정의합니다.",
  "",
  "| 항목명 | 의미 | 값 설명 |",
  "| :--- | :--- | :--- |",
  '| `data` | 실제 전사 텍스트 | `"09451"` |',
  "| `id` | 바운딩 박스 식별번호 | `1` |",
  "| `x` | X 좌표 배열 | `[1848, 1848, 2019, 2019]` |",
  "| `y` | Y 좌표 배열 | `[199, 275, 199, 275]` |",
  "",
  "> **참고:** `x`, `y` 좌표 배열은 일반적으로 4포인트(좌상, 우상, 우하, 좌하)의 다각형 영역을 나타냅니다.",
].join("\n")

const MD_COMPONENTS: Components = {
  h1: ({ node: _node, ...p }) => <h1 className="mb-2 mt-1 text-sm font-bold text-black" {...p} />,
  h2: ({ node: _node, ...p }) => <h2 className="mb-1 mt-4 text-sm font-semibold text-black" {...p} />,
  p: ({ node: _node, ...p }) => <p className="my-1 text-sm leading-relaxed text-black" {...p} />,
  table: ({ node: _node, ...p }) => (
    <div className="my-2 overflow-x-auto">
      <table className="w-full border-collapse text-sm" {...p} />
    </div>
  ),
  th: ({ node: _node, ...p }) => (
    <th className="border border-border bg-muted/60 px-2 py-1 text-left text-sm font-semibold text-black" {...p} />
  ),
  td: ({ node: _node, ...p }) => (
    <td className="border border-border px-2 py-1 align-top text-sm text-black" {...p} />
  ),
  code: ({ node: _node, ...p }) => (
    <code className="rounded bg-muted px-1 py-0.5 text-xs text-black" {...p} />
  ),
  strong: ({ node: _node, ...p }) => <strong className="font-semibold text-black" {...p} />,
  hr: ({ node: _node, ...p }) => <hr className="my-3 border-border" {...p} />,
  blockquote: ({ node: _node, ...p }) => (
    <blockquote className="my-2 border-l-2 border-border pl-3 text-xs text-muted-foreground" {...p} />
  ),
}

function LabelingSection({ title, items }: { title: string; items: string[] }) {
  return (
    <section className="space-y-2">
      <h4 className="text-sm font-semibold text-black">{title}</h4>
      <ol className="list-decimal space-y-1.5 pl-5 text-sm text-black marker:text-muted-foreground">
        {items.map((g, i) => (
          <li key={i} className="leading-relaxed">
            {g}
          </li>
        ))}
      </ol>
    </section>
  )
}

export function AnnotationGuide() {
  return (
    <div className="space-y-5">
      <LabelingSection title="라벨링 지침" items={LABELING_GUIDE} />
      <section>
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={MD_COMPONENTS}>
          {METADATA_MARKDOWN}
        </ReactMarkdown>
      </section>
    </div>
  )
}
