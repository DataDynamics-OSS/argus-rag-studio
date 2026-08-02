// 컬렉션 설정용 표 컴포넌트 — catalog 데이터셋 메타데이터 표 스타일(테두리 셀·키 셀 음영).
// 생성/재인덱싱 다이얼로그에서 공용으로 쓴다. 키 셀에는 ? tooltip(선택) 을 단다.
"use client"

import type { ReactNode } from "react"
import { HelpCircle } from "lucide-react"
import { Label } from "@workspace/ui/components/label"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@workspace/ui/components/tooltip"

// 숫자 입력 필드용 — 숫자가 아닌 문자는 입력 즉시 제거
export const digitsOnly = (v: string) => v.replace(/[^0-9]/g, "")

// 초보자용 옵션 설명(? 아이콘 tooltip). 생성/재인덱싱 공용.
export const COLLECTION_HINTS = {
  name: "이 지식베이스를 알아볼 이름이에요. 예) '제품 매뉴얼', '사내 규정'. 비슷한 문서끼리 하나의 지식베이스로 묶으세요.",
  description: "이 지식베이스가 어떤 자료를 담는지 메모해 두는 칸이에요. 비워둬도 됩니다.",
  provider:
    "질문·문서를 컴퓨터가 이해하는 숫자(벡터)로 바꾸는 엔진이에요. 'OpenAI 호환'은 외부 임베딩 서버를 사용, '로컬'은 서버 없이 이 앱이 직접 모델을 돌려 임베딩(최초 1회 모델 다운로드), 'hash'는 의미 없는 가짜 벡터로 동작 테스트용입니다. 서버가 없다면 '로컬'을 권장합니다.",
  dim: "임베딩 벡터의 길이(숫자 개수)예요. 모델마다 정해져 있어 맞춰야 합니다(보통 1024). 사용자가 정하는 값이 아니라서 로컬은 모델 선택 시 자동, OpenAI 호환은 '차원 감지' 버튼으로만 설정합니다(직접 입력 불가).",
  model: "문서를 벡터로 바꿀 임베딩 모델이에요. '로컬'은 지원 목록에서 고릅니다(한국어엔 multilingual-e5-large·jina-v3 추천). 'OpenAI 호환'은 서버 URL 입력 후 '모델 불러오기'를 누르고 목록에서 선택합니다(직접 입력 불가 — 오타·미지원 모델 방지).",
    serverUrl:
    "OpenAI 호환 임베딩 서버 주소예요(예: http://host:8080/v1). 입력 후 '테스트'를 눌러 연결을 확인하면 모델 목록·차원이 자동으로 채워집니다. URL을 바꾸면 다시 테스트해야 해요.",
  metric:
    "검색할 때 '질문과 문서가 얼마나 비슷한가'를 재는 방법이에요. 대부분 'cosine'이 정답입니다. 잘 모르면 cosine 그대로 두세요.",
  reranker:
    "1차 검색 결과를 한 번 더 정렬해 정확도를 높이는 단계예요. 'none'은 사용 안 함, 'llm'은 AI가 다시 순위를 매김, 'cross_encoder'는 전용 재정렬 서버를 사용. 처음엔 none으로 시작해도 됩니다. (나중에 재인덱싱 없이 바꿀 수 있어요)",
  rerankModel:
    "재정렬에 쓸 cross-encoder 모델이에요. 'local'은 이 앱이 직접 돌리는 FastEmbed 모델 목록에서, 'cross_encoder'는 리랭커 서버가 제공하는 목록에서 고릅니다. 비우면 기본 모델을 씁니다. 한국어는 다국어 리랭커(jina-reranker-v2-multilingual)를 권장합니다.",
  parse:
    "업로드한 파일에서 글자를 뽑아내는 방법이에요. 'auto'(권장)는 파일 유형에 맞춰 자동 선택(PDF→layout, HWP→rhwp, 그 외→text)하므로 여러 형식을 섞어도 됩니다. 직접 고르려면: 'text'는 빠르나 PDF 표·스캔본에 약함, 'layout'은 PDF 표를 Markdown으로, 'docai'는 문서 AI로 레이아웃·표 복원, 'vlm'은 페이지 이미지를 AI가 변환(정확하나 느림·비쌈, PDF 전용), 'rhwp'는 한글 HWP/HWPX 전용. 일부 전략은 추가 설치가 필요해 '(미설치)'로 표시될 수 있어요.",
  strategy:
    "긴 문서를 검색 단위로 잘게 나누는 방법이에요. 'auto'(권장)는 내용에 표·헤딩이 있으면 markdown, 아니면 recursive로 자동 선택합니다. 직접 고르려면: 'recursive'는 구조 보존 범용, 'sentence'는 문장을 끊지 않음(FAQ·한국어 정확), 'paragraph'는 문단(빈 줄)을 끊지 않음(산문·보고서), 'section'은 섹션 헤더(헤딩·번호·장/절)로 자름, 'fixed'는 같은 길이로, 'markdown'은 표·헤딩 보존, 'semantic'은 의미가 바뀌는 지점에서 자름(가장 정교하나 임베딩 비용↑). 잘 모르면 auto를 두세요.",
  chunkUnit:
    "청크 크기·오버랩을 무엇으로 셀지예요. 'char'는 글자 수(기본), 'token'은 임베딩 모델이 실제로 세는 토큰 수입니다. 임베딩 모델은 보통 512토큰 한도가 있어, 한도를 정확히 지키려면 token(예: 크기 512, 오버랩 64)이 더 안전합니다. 한국어·코드는 글자당 토큰 수가 달라 char로는 한도를 넘기기 쉬워요.",
  chunkSize:
    "잘린 조각 하나의 최대 글자 수예요. 작으면 정밀하지만 맥락이 짧고, 크면 맥락은 길지만 덜 정밀합니다. 보통 800~1200자가 무난합니다.",
  chunkOverlap:
    "이웃한 조각끼리 겹치는 글자 수예요. 조각 경계에서 문맥이 끊기는 걸 줄여줍니다. 보통 청크 크기의 10~15%(예: 1000자면 150자)로 둡니다. 청크 크기보다 작아야 합니다.",
} as const

export function HintLabel({ children, hint }: { children: ReactNode; hint: string }) {
  return (
    <Label className="flex items-center gap-1 text-sm">
      {children}
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            tabIndex={-1}
            aria-label="설명 보기"
            className="text-muted-foreground/70 transition-colors hover:text-foreground"
          >
            <HelpCircle className="size-3.5" />
          </button>
        </TooltipTrigger>
        <TooltipContent className="max-w-xs leading-relaxed">{hint}</TooltipContent>
      </Tooltip>
    </Label>
  )
}

export function ConfigTable({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <p className="text-sm font-medium text-muted-foreground">{title}</p>
      <div className="overflow-hidden rounded-md border">
        <table className="w-full table-fixed border-collapse text-sm">
          <colgroup>
            <col className="w-[124px]" />
            <col />
          </colgroup>
          <tbody>{children}</tbody>
        </table>
      </div>
    </div>
  )
}

export function ConfigRow({
  label,
  hint,
  children,
  top,
}: {
  label: string
  hint?: string
  children: ReactNode
  top?: boolean
}) {
  const align = top ? "align-top" : "align-middle"
  return (
    <tr>
      <th className={`border bg-muted/60 px-3 py-1 text-left font-medium ${align}`}>
        {hint ? (
          <HintLabel hint={hint}>{label}</HintLabel>
        ) : (
          <Label className="text-sm">{label}</Label>
        )}
      </th>
      <td className={`border px-2 py-1 ${align}`}>{children}</td>
    </tr>
  )
}
