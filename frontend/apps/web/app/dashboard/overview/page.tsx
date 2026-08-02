"use client"

// RAG 개요 — 처음 사용하는 분이 RAG의 전체 처리 순서를 한눈에 익히도록 돕는 화면.
// 3단계 흐름(준비 → 활용 → 개선)을 다이어그램으로 보여주고, 각 단계가 어느 화면과
// 연결되는지 링크로 안내한다. 설명 문구는 격식체(~하십시오)로 통일한다.

import { UrlTabs } from "@/components/url-tabs"
import { Fragment, useState } from "react"
import Link from "next/link"
import {
  Database,
  Upload,
  ScanText,
  Scissors,
  Boxes,
  Layers,
  Search,
  ListFilter,
  Sparkles,
  ClipboardCheck,
  ThumbsUp,
  ChevronRight,
  ChevronDown,
  RefreshCw,
  Lock,
  RotateCw,
  Languages,
  Gauge,
  Wrench,
  GraduationCap,
  CheckCircle2,
  AlertTriangle,
  FileText,
  GitBranch,
  Ruler,
  BarChart3,
  History,
  MessageSquare,
  HelpCircle,
  type LucideIcon,
} from "lucide-react"
import { TabsContent, TabsList, TabsTrigger } from "@workspace/ui/components/tabs"
import { DashboardHeader } from "@/components/dashboard-header"
import { Mermaid } from "@/components/mermaid"
import {
  Bullets,
  Callout,
  CostBadge,
  Heading,
  StrategyTable,
  Sub,
  TabShell,
  type Cost,
  type StrategyRow,
} from "@/components/doc-blocks"

interface Step {
  n: number
  title: string
  icon: LucideIcon
  desc: string
  href?: string
  cost?: Cost
}

interface Phase {
  id: string
  label: string
  intro: string
  // Tailwind 은 동적 클래스 보간을 못 보므로 완전한 클래스 문자열을 직접 둔다.
  accentBorder: string
  steps: Step[]
}

const PHASES: Phase[] = [
  {
    id: "prepare",
    label: "① 준비 — 인덱싱 파이프라인",
    intro:
      "문서를 검색 가능한 형태로 가공해 저장하는 단계입니다. 이 단계의 임베딩·청킹 설정은 생성 후 바꿀 수 없으니, 문서의 언어와 용도에 맞게 처음부터 정하십시오.",
    accentBorder: "border-amber-500",
    steps: [
      {
        n: 1,
        title: "지식베이스 생성",
        icon: Database,
        desc: "임베딩 모델·청킹 방식을 정해 벡터 공간을 만듭니다. 한국어 문서라면 다국어 모델을 선택하십시오.",
        href: "/dashboard/collections",
        cost: "index",
      },
      {
        n: 2,
        title: "문서 업로드",
        icon: Upload,
        desc: "PDF·DOCX·HWP·마크다운 등 원본을 등록합니다. 업로드 후 추출 결과를 확인하십시오.",
        href: "/dashboard/collections",
      },
      {
        n: 3,
        title: "파싱",
        icon: ScanText,
        desc: "파일에서 글자를 추출합니다. 표·레이아웃이 많으면 파싱 전략을 layout/vlm으로 지정하십시오.",
        cost: "index",
      },
      {
        n: 4,
        title: "청킹",
        icon: Scissors,
        desc: "긴 문서를 검색 단위 조각으로 나눕니다. 경계에서 문맥이 끊기지 않도록 오버랩을 두십시오.",
        cost: "index",
      },
      {
        n: 5,
        title: "임베딩",
        icon: Boxes,
        desc: "각 조각의 의미를 벡터(숫자 목록)로 변환합니다. 단어가 달라도 의미로 검색되게 합니다.",
        cost: "index",
      },
      {
        n: 6,
        title: "색인 저장",
        icon: Layers,
        desc: "벡터와 키워드 인덱스를 저장해 검색을 준비합니다. 여기까지 마치면 질의가 가능합니다.",
        cost: "index",
      },
    ],
  },
  {
    id: "use",
    label: "② 활용 — 질의 파이프라인",
    intro:
      "사용자의 질문을 받아 근거를 찾고 답변을 만드는 단계입니다. 이 단계의 설정은 재인덱싱 없이 언제든 바꿔 비교하실 수 있습니다.",
    accentBorder: "border-sky-500",
    steps: [
      {
        n: 7,
        title: "질문 입력",
        icon: Sparkles,
        desc: "사용자가 질문을 입력하면, 질문도 같은 임베딩 방식으로 벡터로 변환됩니다.",
        href: "/dashboard/playground",
      },
      {
        n: 8,
        title: "검색",
        icon: Search,
        desc: "의미(벡터)와 키워드(렉시컬)로 가장 비슷한 조각을 찾습니다. 확신이 없으면 하이브리드를 쓰십시오.",
        href: "/dashboard/playground",
        cost: "query",
      },
      {
        n: 9,
        title: "리랭크",
        icon: ListFilter,
        desc: "1차 검색 결과를 한 번 더 정밀하게 재정렬해 상위 정확도를 높입니다(선택).",
        cost: "query",
      },
      {
        n: 10,
        title: "답변 생성",
        icon: Sparkles,
        desc: "찾은 근거를 바탕으로 LLM이 답변을 작성합니다. 근거에 충실한 답변이 되도록 합니다.",
        href: "/dashboard/chat",
        cost: "query",
      },
    ],
  },
  {
    id: "improve",
    label: "③ 개선 — 평가·피드백 루프",
    intro:
      "감이 아니라 숫자로 품질을 확인하고 개선하는 단계입니다. 이 루프를 반복해 설정을 다듬으십시오.",
    accentBorder: "border-emerald-500",
    steps: [
      {
        n: 11,
        title: "평가",
        icon: ClipboardCheck,
        desc: "정답을 정해둔 골든셋으로 Hit Rate·MRR을 측정합니다. 설정을 바꿨을 때 좋아졌는지 비교하십시오.",
        href: "/dashboard/evaluation",
      },
      {
        n: 12,
        title: "피드백 → 보강",
        icon: ThumbsUp,
        desc: "사용자의 👍/👎를 모아 나쁜 사례를 골든셋으로 승격합니다. 실제 실패가 다음 평가 문제가 됩니다.",
        href: "/dashboard/feedback",
      },
    ],
  },
]

function StepCard({ step }: { step: Step }) {
  const Icon = step.icon
  const inner = (
    <div className="flex h-full w-[200px] shrink-0 flex-col gap-2 rounded-lg border bg-card p-3 transition-colors hover:border-primary/50 hover:bg-accent/40">
      <div className="flex items-center gap-2">
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary/10 text-sm font-bold text-primary">
          {step.n}
        </span>
        <Icon className="h-4 w-4 text-muted-foreground" />
        <span className="truncate text-sm font-semibold text-foreground">{step.title}</span>
      </div>
      <p className="text-sm leading-relaxed text-muted-foreground">{step.desc}</p>
      <div className="mt-auto flex items-center justify-between pt-1">
        {step.cost ? <CostBadge cost={step.cost} /> : <span />}
        {step.href && <ChevronRight className="h-3.5 w-3.5 text-muted-foreground/60" />}
      </div>
    </div>
  )
  return step.href ? (
    <Link href={step.href} className="block">
      {inner}
    </Link>
  ) : (
    inner
  )
}

function FlowTab() {
  return (
    <div className="flex flex-col gap-6">
        {/* 인트로 */}
        <div className="max-w-3xl">
          <h2 className="text-lg font-semibold">RAG는 어떤 순서로 동작하나요?</h2>
          <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
            RAG(검색 증강 생성)는 문서를 저장 가능한 형태로 가공해 두고, 질문이 오면 가장 관련 있는
            근거를 찾아 답변을 만드는 방식입니다. 아래 순서대로 진행하시면 됩니다. 각 단계를 누르시면
            해당 작업 화면으로 이동합니다.
          </p>
          {/* 범례 */}
          <div className="mt-3 flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
            <span className="inline-flex items-center gap-1">
              <Lock className="h-3 w-3 text-amber-500" /> 재인덱싱 필요 — 생성 후 바꾸면 전체 다시 처리
            </span>
            <span className="inline-flex items-center gap-1">
              <RotateCw className="h-3 w-3 text-emerald-500" /> 실시간 변경 — 언제든 바꿔 비교 가능
            </span>
          </div>
        </div>

        {/* 단계별 흐름 */}
        {PHASES.map((phase, pi) => (
          <div key={phase.id}>
            <div className={`mb-2 border-l-2 ${phase.accentBorder} pl-3`}>
              <h3 className="text-sm font-semibold text-foreground">{phase.label}</h3>
              <p className="mt-0.5 max-w-3xl text-sm leading-relaxed text-muted-foreground">
                {phase.intro}
              </p>
            </div>

            {/* 스텝 카드 가로 흐름 (반응형 줄바꿈) */}
            <div className="flex flex-wrap items-stretch gap-2">
              {phase.steps.map((step, si) => (
                <div key={step.n} className="flex items-stretch gap-2">
                  <StepCard step={step} />
                  {si < phase.steps.length - 1 && (
                    <div className="flex items-center">
                      <ChevronRight className="h-5 w-5 text-muted-foreground/40" />
                    </div>
                  )}
                </div>
              ))}
            </div>

            {/* 단계 사이 연결 화살표 */}
            {pi < PHASES.length - 1 && (
              <div className="flex items-center gap-2 py-3 pl-3 text-sm text-muted-foreground">
                <ChevronDown className="h-5 w-5 text-muted-foreground/50" />
                <span>다음 단계로 진행하십시오</span>
              </div>
            )}
          </div>
        ))}

        {/* 개선 루프 환기 */}
        <div className="flex items-center gap-2 rounded-lg border border-dashed bg-muted/30 p-3 text-sm text-muted-foreground">
          <RefreshCw className="h-4 w-4 shrink-0 text-emerald-500" />
          <span>
            <span className="font-medium text-foreground">개선은 반복입니다.</span> 평가·피드백에서 얻은
            결과로 ① 준비 단계의 설정(임베딩·청킹·파싱)이나 ② 활용 단계의 설정(검색 방식·리랭크)을
            바꿔 다시 측정하십시오. 설정 스윕을 쓰시면 여러 조합을 자동으로 비교하실 수 있습니다.
          </span>
        </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// 두 번째 탭 — "임베딩 모델이란?"
// ---------------------------------------------------------------------------

interface LadderRow {
  step: number
  method: string
  cost: Cost
  effect: string
}

const LADDER: LadderRow[] = [
  { step: 1, method: "더 맞는 기성 모델 선택 (언어·도메인)", cost: "index", effect: "큼 — 한글 문서에 다국어 모델만 써도 정확도가 크게 오릅니다." },
  { step: 2, method: "청킹·파싱 설정 튜닝", cost: "index", effect: "중 — 조각 크기·파싱 전략을 데이터에 맞춥니다." },
  { step: 3, method: "하이브리드 검색 + 리랭커 추가", cost: "query", effect: "중~큼 — 재인덱싱 없이 정확도를 올립니다." },
  { step: 4, method: "쿼리 재작성·메타데이터 필터", cost: "query", effect: "중 — 질문을 다듬고 검색 범위를 좁힙니다." },
  { step: 5, method: "검색 모델 파인튜닝 (직접 개발)", cost: null, effect: "도메인에 따라 큼 — 단, 비용·전문성이 매우 큽니다." },
]

const SIGNALS: string[] = [
  "전문 도메인 용어를 기성 모델이 이해하지 못합니다 (법률·의료·바이오·반도체·사내 약어 등).",
  "좋은 모델과 리랭커까지 적용했는데도 골든셋의 Hit Rate·MRR이 목표에 한참 못 미칩니다 (감이 아니라 평가 숫자로 확인).",
  "질문↔정답문서 라벨 데이터를 충분히(보통 수천 건 이상) 모을 수 있습니다.",
  "같은 도메인 질의가 대량으로 반복되어, 학습 투자 대비 효과가 분명합니다.",
]

const PREREQS: string[] = [
  "학습 데이터: (질의, 정답 청크, 오답 청크) 쌍 — 없으면 시작할 수 없는 가장 큰 장벽입니다.",
  "평가 체계: 파인튜닝 전·후를 비교할 골든셋 (평가 화면 활용). 측정 없는 파인튜닝은 도박입니다.",
  "GPU·MLOps: 학습 인프라와 모델 버전 관리 체계.",
  "운영 부담: 모델을 바꾸면 기존 문서를 전부 다시 임베딩(전체 재인덱싱)해야 합니다.",
]

function EmbeddingTab() {
  return (
    <div className="flex max-w-3xl flex-col gap-6 text-sm leading-relaxed">
      {/* 임베딩이란 */}
      <section>
        <div className="mb-1 flex items-center gap-2">
          <Boxes className="h-4 w-4 text-primary" />
          <h2 className="text-base font-semibold">임베딩 모델이란?</h2>
        </div>
        <p className="text-muted-foreground">
          임베딩 모델은 문장을 <span className="font-medium text-foreground">의미를 담은 숫자 목록(벡터)</span>으로
          바꾸는 모델입니다. 의미가 비슷하면 숫자도 비슷해지기 때문에, 단어가 달라도(&lsquo;환불&rsquo;↔&lsquo;반품&rsquo;)
          뜻으로 검색할 수 있습니다. RAG에서 검색 품질을 좌우하는 <span className="font-medium text-foreground">1차 결정
          요인</span>이에요.
        </p>
      </section>

      {/* 왜 언어가 중요한가 */}
      <section className="rounded-lg border bg-card p-3">
        <div className="mb-1 flex items-center gap-2">
          <Languages className="h-4 w-4 text-sky-500" />
          <h3 className="text-sm font-semibold">문서의 언어에 맞는 모델을 쓰십시오</h3>
        </div>
        <p className="text-muted-foreground">
          한국어 문서에 영어 전용 모델을 쓰면 의미를 제대로 잡지 못해 정확도가 크게 떨어집니다. 한국어·다국어
          문서라면 <span className="font-mono text-sm text-foreground">multilingual-e5-large</span> 같은 다국어
          모델을 선택하십시오. 실제로 같은 문서·질의로 측정했을 때 영어 모델의 MRR 0.52가 다국어 모델에서는 1.00으로
          올랐습니다.
        </p>
      </section>

      {/* 핵심 구분 */}
      <section>
        <div className="mb-2 flex items-center gap-2">
          <Gauge className="h-4 w-4 text-primary" />
          <h3 className="text-sm font-semibold">대부분은 &lsquo;개발&rsquo;이 아니라 &lsquo;선택&rsquo;으로 끝납니다</h3>
        </div>
        <div className="grid gap-2 sm:grid-cols-2">
          <div className="rounded-lg border border-emerald-500/40 bg-emerald-500/5 p-3">
            <p className="font-medium text-emerald-700 dark:text-emerald-400">선택 (기성 모델 사용)</p>
            <p className="mt-1 text-sm text-muted-foreground">
              이미 학습된 모델(multilingual-e5, bge-m3 등)을 골라 씁니다. 거의 모든 경우 여기서 끝납니다.
            </p>
          </div>
          <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-3">
            <p className="font-medium text-amber-700 dark:text-amber-400">개발 (파인튜닝·학습)</p>
            <p className="mt-1 text-sm text-muted-foreground">
              내 데이터로 모델을 추가 학습합니다. 비용·전문성이 크고, 아래 조건이 모두 맞을 때의 최후 수단입니다.
            </p>
          </div>
        </div>
      </section>

      {/* 개선 단계 */}
      <section>
        <div className="mb-2 flex items-center gap-2">
          <Wrench className="h-4 w-4 text-primary" />
          <h3 className="text-sm font-semibold">개선 단계 — 위에서부터, 막힐 때만 내려가십시오</h3>
        </div>
        <div className="overflow-hidden rounded-lg border">
          <table className="w-full text-left text-sm">
            <thead className="bg-muted/50 text-muted-foreground">
              <tr>
                <th className="w-8 p-2 text-center">#</th>
                <th className="p-2">방법</th>
                <th className="w-28 p-2">비용</th>
                <th className="p-2">효과</th>
              </tr>
            </thead>
            <tbody>
              {LADDER.map((r) => (
                <tr key={r.step} className="border-t">
                  <td className="p-2 text-center font-semibold text-foreground">{r.step}</td>
                  <td className="p-2 text-foreground">{r.method}</td>
                  <td className="p-2">{r.cost ? <CostBadge cost={r.cost} /> : <span className="text-muted-foreground">학습 비용 큼</span>}</td>
                  <td className="p-2 text-muted-foreground">{r.effect}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-sm text-muted-foreground">
          대부분 1~3단계에서 해결됩니다. 5단계(직접 개발)는 1~4를 모두 했는데도 부족할 때만 검토하십시오.
        </p>
      </section>

      {/* 개발 신호 */}
      <section>
        <div className="mb-2 flex items-center gap-2">
          <AlertTriangle className="h-4 w-4 text-amber-500" />
          <h3 className="text-sm font-semibold">직접 개발(파인튜닝)이 정당화되는 신호</h3>
        </div>
        <p className="mb-2 text-sm text-muted-foreground">아래가 여러 개 동시에 해당할 때만 검토하십시오.</p>
        <ul className="flex flex-col gap-1.5">
          {SIGNALS.map((s, i) => (
            <li key={i} className="flex gap-2 text-sm text-muted-foreground">
              <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-500" />
              <span>{s}</span>
            </li>
          ))}
        </ul>
      </section>

      {/* 개발 전 준비물 */}
      <section>
        <div className="mb-2 flex items-center gap-2">
          <GraduationCap className="h-4 w-4 text-primary" />
          <h3 className="text-sm font-semibold">개발을 택하기 전 갖춰야 할 것</h3>
        </div>
        <ul className="flex flex-col gap-1.5">
          {PREREQS.map((s, i) => (
            <li key={i} className="flex gap-2 text-sm text-muted-foreground">
              <ChevronRight className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground/60" />
              <span>{s}</span>
            </li>
          ))}
        </ul>
      </section>

      {/* 한 줄 요약 */}
      <div className="flex items-start gap-2 rounded-lg border border-dashed bg-muted/30 p-3 text-sm text-muted-foreground">
        <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
        <span>
          <span className="font-medium text-foreground">한 줄 요약.</span> 임베딩 모델 개발은 <em>기성 모델·설정·리랭커로도
          평가 숫자가 천장에 막혔고, 라벨 데이터가 충분하며, 전문 도메인일 때</em> 그때만 검토하십시오. 그전까지는
          <span className="font-medium text-foreground"> 고르고 · 측정하고 · 튜닝</span>하는 것이 정답입니다.
        </span>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// 파싱
// ---------------------------------------------------------------------------

const PARSE_ROWS: StrategyRow[] = [
  { name: "auto", desc: "파일 형식을 보고 자동으로 적절한 방식을 고릅니다. 잘 모르겠으면 이것을 쓰십시오.", cost: "index" },
  { name: "text", desc: "평문 텍스트만 빠르게 추출합니다. 표·레이아웃은 손실됩니다. 일반 문서에 적합합니다.", cost: "index" },
  { name: "layout", desc: "표를 마크다운으로 보존하며 추출합니다(pdfplumber). 표가 많은 PDF에 쓰십시오.", cost: "index" },
  { name: "docai", desc: "문서 AI로 레이아웃·읽기 순서를 복원합니다. 단 추가 의존성이 필요합니다.", cost: "index" },
  { name: "vlm", desc: "페이지를 이미지로 렌더링해 비전 LLM이 변환합니다. 스캔본·복잡 레이아웃에 강하나 고비용입니다.", cost: "index" },
  { name: "rhwp", desc: "HWP/HWPX 문서의 표를 보존해 추출합니다(한컴 전용 파서).", cost: "index" },
]

// 상황·파일 형식 → 권장 파싱 전략.
const PARSE_PICK: { when: string; strategy: string; why: string }[] = [
  { when: "잘 모르겠을 때", strategy: "auto", why: "파일 형식별 자동 선택(PDF→layout, HWP→rhwp, 그 외→text)." },
  { when: "글자 위주 일반 문서 (txt·md·html·DOCX 등)", strategy: "text", why: "빠르고 충분합니다. 표·레이아웃은 손실될 수 있습니다." },
  { when: "표·서식이 많은 PDF", strategy: "layout", why: "표를 마크다운으로 보존합니다(pdfplumber)." },
  { when: "레이아웃·읽기 순서가 복잡한 PDF", strategy: "docai", why: "Docling이 레이아웃·읽기 순서를 복원합니다." },
  { when: "스캔본·이미지 PDF (글자 선택 불가)", strategy: "vlm", why: "페이지 이미지를 비전 LLM이 읽어 변환합니다(고비용)." },
  { when: "한컴 HWP·HWPX", strategy: "rhwp", why: "표 구조를 보존해 추출합니다." },
]

// 지원 파일 형식(backend loaders 기준).
const FORMAT_ROWS: { kind: string; exts: string }[] = [
  { kind: "PDF", exts: ".pdf" },
  { kind: "한컴", exts: ".hwp · .hwpx" },
  { kind: "오피스 (Word·PowerPoint·Excel)", exts: ".docx · .pptx · .xlsx · .doc · .ppt · .xls(구형은 LibreOffice 변환)" },
  { kind: "웹·마크업", exts: ".html · .htm · .xml" },
  { kind: "텍스트·표·로그", exts: ".txt · .md · .markdown · .csv · .tsv · .json · .log · .rst" },
]

function ParsePickTable() {
  return (
    <div className="overflow-hidden rounded-lg border">
      <table className="w-full text-left text-sm">
        <thead className="bg-muted/50 text-muted-foreground">
          <tr>
            <th className="p-2">이런 경우 (파일 형식·상황)</th>
            <th className="w-28 p-2">권장 전략</th>
            <th className="p-2">이유</th>
          </tr>
        </thead>
        <tbody>
          {PARSE_PICK.map((r) => (
            <tr key={r.when} className="border-t align-top">
              <td className="p-2 text-muted-foreground">{r.when}</td>
              <td className="p-2 font-mono text-foreground">{r.strategy}</td>
              <td className="p-2 text-muted-foreground">{r.why}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function FormatTable() {
  return (
    <div className="overflow-hidden rounded-lg border">
      <table className="w-full text-left text-sm">
        <thead className="bg-muted/50 text-muted-foreground">
          <tr>
            <th className="w-56 p-2">종류</th>
            <th className="p-2">확장자</th>
          </tr>
        </thead>
        <tbody>
          {FORMAT_ROWS.map((r) => (
            <tr key={r.kind} className="border-t align-top">
              <td className="p-2 text-foreground">{r.kind}</td>
              <td className="p-2 font-mono text-muted-foreground">{r.exts}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ParsingTab() {
  return (
    <TabShell>
      <section>
        <Heading icon={ScanText}>파싱 — 파일에서 글자 꺼내기</Heading>
        <p className="text-muted-foreground">
          파싱은 PDF·HWP·DOCX 같은 원본 파일에서 <span className="font-medium text-foreground">텍스트를 추출</span>하는
          단계입니다. RAG 품질의 출발점이라, 여기서 글자를 제대로 못 뽑으면 이후 청킹·임베딩·검색이 모두 헛돌게 됩니다
          (&ldquo;쓰레기가 들어가면 쓰레기가 나옵니다&rdquo;).
        </p>
      </section>

      <section>
        <Sub icon={FileText}>파싱 전략</Sub>
        <StrategyTable rows={PARSE_ROWS} />
      </section>

      <section>
        <Sub icon={FileText}>지원 파일 형식</Sub>
        <FormatTable />
      </section>

      <section>
        <Sub icon={AlertTriangle} color="text-amber-500">어떤 전략을 고를까요</Sub>
        <ParsePickTable />
      </section>

      <Callout>
        업로드 후 <span className="font-medium text-foreground">추출된 글자 수</span>를 확인하십시오. 분량에 비해
        글자가 비정상적으로 적다면 스캔본이거나 표 위주 문서일 수 있으니, 파싱 전략을 <span className="font-mono text-sm">layout</span>/
        <span className="font-mono text-sm">vlm</span>으로 바꿔 다시 색인하십시오. 파싱 전략은 변경 시 재인덱싱이 필요합니다.
      </Callout>
    </TabShell>
  )
}

// ---------------------------------------------------------------------------
// 청킹
// ---------------------------------------------------------------------------

const CHUNK_ROWS: StrategyRow[] = [
  { name: "auto", desc: "문서 형식을 보고 자동으로 분할 방식을 고릅니다(헤딩·표가 있으면 markdown, 없으면 recursive). 기본 선택으로 무난합니다.", cost: "index" },
  { name: "recursive", desc: "문단 → 줄 → 문장 → 공백 순으로 가능한 큰 경계에서 크기에 맞춰 나눕니다. 범용 기본 전략입니다.", cost: "index" },
  { name: "sentence", desc: "문장 경계를 보존해(한 문장이 안 잘림) 크기까지 문장을 묶습니다. FAQ·QA처럼 짧은 단위 자료에 적합합니다.", cost: "index" },
  { name: "paragraph", desc: "빈 줄(문단) 경계로 나눕니다. 문단이 뚜렷한 산문·보고서에 적합합니다(긴 문단은 recursive로 폴백).", cost: "index" },
  { name: "section", desc: "헤딩(제목·장·절 등) 경계로 나누고 각 청크에 제목 경로를 붙입니다. 장·절 구조가 뚜렷한 문서에 적합합니다.", cost: "index" },
  { name: "fixed", desc: "의미와 무관하게 글자 수로 균일하게 자릅니다. 단어·문장 중간이 잘릴 수 있어 특수 용도에만 권장합니다.", cost: "index" },
  { name: "markdown", desc: "표·코드블록을 원자 단위로 보존(중간에서 안 자름)하고 헤딩을 유지합니다. layout/docai/vlm 파싱과 함께 쓰십시오.", cost: "index" },
  { name: "semantic", desc: "의미 경계로 나눕니다(문장 임베딩 사용 → 주제 전환 지점에서 끊음). 품질이 좋지만 비용이 큽니다.", cost: "index" },
]

// 같은 파싱 결과를 전략별로 어떻게 자르는지 보여주는 개념 예시(가정: 청크 크기 작게).
type ExChunk = { text: string; tag?: string }
const CHUNK_DEMO_SAMPLE = `# 반품·환불 정책

## 배송 전 취소
주문 후 24시간 이내에는 무료로 취소됩니다. 고객센터로 문의하면 즉시 처리됩니다.

## 배송 후 반품
상품 수령 후 7일 이내 반품이 가능합니다. 단순 변심은 왕복 배송비가 부과됩니다.

| 사유 | 배송비 |
| --- | --- |
| 불량 | 무료 |
| 변심 | 유료 |`

const CHUNK_DEMO: { name: ChunkStrategyName; note: string; chunks: ExChunk[] }[] = [
  {
    name: "recursive",
    note: "가능한 큰 자연 경계(문단→문장)에서 크기에 맞춰 자릅니다. 표는 일반 텍스트(줄)로 취급됩니다.",
    chunks: [
      { text: "# 반품·환불 정책\n\n## 배송 전 취소\n주문 후 24시간 이내에는 무료로 취소됩니다. 고객센터로 문의하면 즉시 처리됩니다." },
      { text: "## 배송 후 반품\n상품 수령 후 7일 이내 반품이 가능합니다. 단순 변심은 왕복 배송비가 부과됩니다." },
      { text: "| 사유 | 배송비 |\n| --- | --- |\n| 불량 | 무료 |\n| 변심 | 유료 |" },
    ],
  },
  {
    name: "sentence",
    note: "문장 경계를 절대 안 자릅니다. 크기가 되면 인접 문장을 묶습니다.",
    chunks: [
      { text: "# 반품·환불 정책\n## 배송 전 취소" },
      { text: "주문 후 24시간 이내에는 무료로 취소됩니다. 고객센터로 문의하면 즉시 처리됩니다." },
      { text: "## 배송 후 반품" },
      { text: "상품 수령 후 7일 이내 반품이 가능합니다. 단순 변심은 왕복 배송비가 부과됩니다." },
    ],
  },
  {
    name: "paragraph",
    note: "빈 줄(문단) 경계로 나눕니다. 문단이 통째로 한 청크가 됩니다.",
    chunks: [
      { text: "# 반품·환불 정책" },
      { text: "## 배송 전 취소\n주문 후 24시간 이내에는 무료로 취소됩니다. 고객센터로 문의하면 즉시 처리됩니다." },
      { text: "## 배송 후 반품\n상품 수령 후 7일 이내 반품이 가능합니다. 단순 변심은 왕복 배송비가 부과됩니다." },
      { text: "| 사유 | 배송비 |\n| --- | --- |\n| 불량 | 무료 |\n| 변심 | 유료 |" },
    ],
  },
  {
    name: "section",
    note: "헤딩을 경계로 나누고 각 청크에 제목 경로(section_path)를 붙입니다. 표는 소속 섹션에 포함됩니다.",
    chunks: [
      {
        tag: "반품·환불 정책 › 배송 전 취소",
        text: "## 배송 전 취소\n주문 후 24시간 이내에는 무료로 취소됩니다. 고객센터로 문의하면 즉시 처리됩니다.",
      },
      {
        tag: "반품·환불 정책 › 배송 후 반품",
        text: "## 배송 후 반품\n상품 수령 후 7일 이내 반품이 가능합니다. 단순 변심은 왕복 배송비가 부과됩니다.\n\n| 사유 | 배송비 |\n| --- | --- |\n| 불량 | 무료 |\n| 변심 | 유료 |",
      },
    ],
  },
  {
    name: "fixed",
    note: "의미·문장 무시하고 글자 수만 맞춰 자릅니다. 단어·문장 중간이 잘려 문맥이 끊깁니다(특수 용도).",
    chunks: [
      { text: "# 반품·환불 정책\n\n## 배송 전 취소\n주문 후 24시간 이" },
      { text: "내에는 무료로 취소됩니다. 고객센터로 문의하면 즉시 처" },
      { text: "리됩니다.\n\n## 배송 후 반품\n상품 수령 후 7일 이내 반" },
      { text: "품이 가능합니다. 단순 변심은 왕복 배송비가 부과됩니다." },
    ],
  },
  {
    name: "markdown",
    note: "표·코드블록을 원자 단위로 보존(중간에서 안 자름)하고 헤딩 맥락을 유지합니다.",
    chunks: [
      { text: "# 반품·환불 정책\n\n## 배송 전 취소\n주문 후 24시간 이내에는 무료로 취소됩니다. 고객센터로 문의하면 즉시 처리됩니다." },
      { text: "## 배송 후 반품\n상품 수령 후 7일 이내 반품이 가능합니다. 단순 변심은 왕복 배송비가 부과됩니다." },
      { tag: "표 — 원자 보존", text: "| 사유 | 배송비 |\n| --- | --- |\n| 불량 | 무료 |\n| 변심 | 유료 |" },
    ],
  },
  {
    name: "semantic",
    note: "문장 임베딩으로 주제가 바뀌는 지점(취소 → 반품)에서 끊습니다. 크기보다 '의미 묶음'을 우선합니다.",
    chunks: [
      { text: "# 반품·환불 정책\n## 배송 전 취소\n주문 후 24시간 이내에는 무료로 취소됩니다. 고객센터로 문의하면 즉시 처리됩니다." },
      { text: "## 배송 후 반품\n상품 수령 후 7일 이내 반품이 가능합니다. 단순 변심은 왕복 배송비가 부과됩니다.\n\n| 사유 | 배송비 |\n| --- | --- |\n| 불량 | 무료 |\n| 변심 | 유료 |" },
    ],
  },
  {
    name: "auto",
    note: "내용을 보고 자동 선택합니다. 이 문서는 헤딩+표가 있어 markdown으로 처리됩니다(아래는 그 결과).",
    chunks: [
      { text: "# 반품·환불 정책\n\n## 배송 전 취소\n주문 후 24시간 이내에는 무료로 취소됩니다. 고객센터로 문의하면 즉시 처리됩니다." },
      { text: "## 배송 후 반품\n상품 수령 후 7일 이내 반품이 가능합니다. 단순 변심은 왕복 배송비가 부과됩니다." },
      { tag: "표 — 원자 보존", text: "| 사유 | 배송비 |\n| --- | --- |\n| 불량 | 무료 |\n| 변심 | 유료 |" },
    ],
  },
]

type ChunkStrategyName =
  | "auto" | "recursive" | "sentence" | "paragraph" | "section" | "fixed" | "markdown" | "semantic"

function ChunkStrategyDemo() {
  const [sel, setSel] = useState<ChunkStrategyName>("recursive")
  const ex = CHUNK_DEMO.find((e) => e.name === sel) ?? CHUNK_DEMO[0]!
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap gap-1.5">
        {CHUNK_DEMO.map((e) => (
          <button
            key={e.name}
            type="button"
            onClick={() => setSel(e.name)}
            className={`rounded-md border px-2 py-1 font-mono text-sm transition-colors ${
              sel === e.name
                ? "border-primary bg-primary/10 text-primary"
                : "text-muted-foreground hover:bg-muted/60"
            }`}
          >
            {e.name}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {/* 청킹 전 */}
        <div className="overflow-hidden rounded-lg border">
          <div className="border-b bg-muted/50 px-3 py-1.5 text-xs font-medium text-muted-foreground">
            청킹 전 (파싱 결과)
          </div>
          <pre className="whitespace-pre-wrap break-words p-3 font-sans text-xs leading-relaxed text-foreground">
            {CHUNK_DEMO_SAMPLE}
          </pre>
        </div>

        {/* 청킹 후 */}
        <div className="overflow-hidden rounded-lg border">
          <div className="border-b bg-muted/50 px-3 py-1.5 text-xs font-medium text-muted-foreground">
            청킹 후 — <span className="font-mono text-foreground">{ex.name}</span> · {ex.chunks.length}개
          </div>
          <div className="space-y-2 p-2">
            {ex.chunks.map((c, i) => (
              <div key={i} className="rounded-md border bg-background p-2">
                <div className="mb-1 flex items-center gap-1.5 text-[11px] text-muted-foreground">
                  <span className="rounded bg-muted px-1 font-mono">#{i + 1}</span>
                  {c.tag && <span className="truncate text-primary/80">{c.tag}</span>}
                </div>
                <pre className="whitespace-pre-wrap break-words font-sans text-xs leading-relaxed text-foreground">
                  {c.text}
                </pre>
              </div>
            ))}
          </div>
        </div>
      </div>
      <p className="text-xs text-muted-foreground">{ex.note}</p>
    </div>
  )
}

function ChunkingTab() {
  return (
    <TabShell>
      <section>
        <Heading icon={Scissors}>청킹 — 검색 단위로 나누기</Heading>
        <p className="text-muted-foreground">
          청킹은 긴 문서를 <span className="font-medium text-foreground">검색 단위 조각(청크)</span>으로 자르는
          단계입니다. 검색은 문서 전체가 아니라 이 조각을 단위로 이뤄지므로, 조각을 어떻게 자르느냐가 검색 정밀도와
          답변 품질에 직접 영향을 줍니다.
        </p>
      </section>

      <section>
        <Sub icon={Ruler}>크기와 오버랩</Sub>
        <Bullets
          items={[
            <>
              <span className="font-medium text-foreground">너무 크면</span> 한 조각에 관련 없는 내용이 섞여 검색
              정밀도가 떨어집니다. <span className="font-medium text-foreground">너무 작으면</span> 문맥이 끊겨 의미를
              잃습니다. 글자 기준 <span className="font-medium text-foreground">800~1,200자</span>를 권장합니다.
            </>,
            <>
              <span className="font-medium text-foreground">오버랩</span>은 조각 경계에서 겹치는 양입니다. 경계에서
              문장이 잘려 문맥이 끊기지 않도록, 크기의 <span className="font-medium text-foreground">10~20%</span>(예:
              1,000자 → 150자)를 두십시오.
            </>,
            <>
              <span className="font-medium text-foreground">단위</span>는 글자(char)가 직관적이고, LLM 입력 길이와
              정확히 맞추려면 토큰(token)을 쓰십시오.
            </>,
          ]}
        />
      </section>

      <section>
        <Sub icon={Scissors}>청크 전략</Sub>
        <StrategyTable rows={CHUNK_ROWS} />
      </section>

      <section>
        <Sub icon={Scissors}>예시 — 같은 문서, 전략별 청킹 결과</Sub>
        <p className="mb-2 text-muted-foreground">
          아래는 같은 파싱 결과를 전략별로 어떻게 자르는지 보여주는 <span className="font-medium text-foreground">개념 예시</span>입니다(청크 크기를 작게 가정).
          전략 버튼을 눌러 <span className="font-medium text-foreground">청킹 전(왼쪽)</span>과{" "}
          <span className="font-medium text-foreground">청킹 후(오른쪽)</span>를 비교해 보십시오. 실제 문서로 비교하려면 컬렉션 상세의
          &lsquo;청킹 전·후 비교&rsquo;를 사용하십시오.
        </p>
        <ChunkStrategyDemo />
      </section>

      <Callout>
        청킹 설정도 변경 시 재인덱싱이 필요합니다. 검색이 자꾸 엉뚱한 조각을 가져온다면, 모델을 바꾸기 전에 먼저
        <span className="font-medium text-foreground"> 청크 크기·오버랩·전략</span>을 조정해 평가로 비교하십시오.
      </Callout>
    </TabShell>
  )
}

// ---------------------------------------------------------------------------
// 파이프라인
// ---------------------------------------------------------------------------

function PipelineTab() {
  return (
    <TabShell>
      <section>
        <Heading icon={GitBranch}>파이프라인 — 설정을 버전으로 저장</Heading>
        <p className="text-muted-foreground">
          파이프라인은 검색·리랭크·생성 설정을 <span className="font-medium text-foreground">하나의 묶음으로, 버전을
          매겨 저장</span>해 두는 곳입니다. 좋은 설정을 이름 붙여 보관하고, 평가·운영에서 불러 쓰며, 문제가 생기면
          이전 버전으로 되돌릴 수 있습니다.
        </p>
      </section>

      <section>
        <Sub icon={History}>버전과 단계</Sub>
        <Bullets
          items={[
            <><span className="font-medium text-foreground">버전</span> — 설정을 바꿀 때마다 새 버전으로 남습니다. 언제든 이전 설정으로 되돌리거나 비교할 수 있습니다.</>,
            <><span className="font-medium text-foreground">단계(stage)</span> — 실험 중인 설정(dev)과 검증된 운영 설정을 구분합니다. 검증 전 설정이 운영에 섞이지 않게 하십시오.</>,
            <><span className="font-medium text-foreground">활성 버전</span> — 실제로 사용할 버전을 지정합니다.</>,
          ]}
        />
      </section>

      <Callout icon={RotateCw}>
        파이프라인의 검색·리랭크·생성 설정은 <span className="font-medium text-foreground">질의 시점</span> 설정이라
        재인덱싱이 필요 없습니다. 여러 버전을 만들어 <Link href="/dashboard/evaluation" className="text-primary hover:underline">평가</Link>로
        점수를 비교한 뒤, 가장 좋은 버전을 운영으로 승격하십시오.
      </Callout>
    </TabShell>
  )
}

// ---------------------------------------------------------------------------
// 평가
// ---------------------------------------------------------------------------

const METRIC_ROWS: { metric: string; meaning: string }[] = [
  { metric: "Hit Rate", meaning: "기대 출처 문서가 상위 결과(top-k) 안에 들어온 비율입니다. \"맞는 문서를 가져오기는 하나?\"" },
  { metric: "MRR", meaning: "기대 문서가 몇 번째로 나왔는지의 평균입니다(1등=1.0, 2등=0.5…). \"얼마나 위에 올리나?\"" },
  { metric: "Faithfulness", meaning: "(judge) 답변이 근거에 충실한지, 없는 말을 지어내지 않는지 0~1로 채점합니다." },
  { metric: "Answer Relevance", meaning: "(judge) 답변이 질문에 실제로 답하는지 0~1로 채점합니다." },
  { metric: "Correctness", meaning: "(judge) 답변이 기대 정답과 일치하는지 0~1로 채점합니다." },
]

function EvaluationTab() {
  return (
    <TabShell>
      <section>
        <Heading icon={ClipboardCheck}>평가 — 품질을 숫자로 확인</Heading>
        <p className="text-muted-foreground">
          평가는 정답을 미리 정해 둔 <span className="font-medium text-foreground">질문 모음(골든셋)</span>으로 검색·답변이
          실제로 잘 맞는지 <span className="font-medium text-foreground">점수로 측정</span>하는 곳입니다. &ldquo;좋아진 것
          같다&rdquo;가 아니라, 설정을 바꿨을 때 숫자가 올랐는지 비교할 수 있습니다.
        </p>
      </section>

      <section>
        <Sub icon={ClipboardCheck}>골든셋 만들기</Sub>
        <Bullets
          items={[
            <><span className="font-medium text-foreground">질문</span> — 사용자가 실제로 물어볼 법한 질문을 표현을 다양하게(동의어·구어체) 넣으십시오.</>,
            <><span className="font-medium text-foreground">기대 정답</span> — 모범 답안. judge(LLM 채점)를 켤 때 비교 기준이 됩니다(선택).</>,
            <><span className="font-medium text-foreground">기대 출처</span> — 정답이 들어 있는 문서 이름. Hit Rate·MRR 계산의 핵심입니다.</>,
          ]}
        />
      </section>

      <section>
        <Sub icon={BarChart3}>지표 읽는 법</Sub>
        <div className="overflow-hidden rounded-lg border">
          <table className="w-full text-left text-sm">
            <thead className="bg-muted/50 text-muted-foreground">
              <tr>
                <th className="w-32 p-2">지표</th>
                <th className="p-2">의미</th>
              </tr>
            </thead>
            <tbody>
              {METRIC_ROWS.map((r) => (
                <tr key={r.metric} className="border-t align-top">
                  <td className="p-2 font-medium text-foreground">{r.metric}</td>
                  <td className="p-2 text-muted-foreground">{r.meaning}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <Sub icon={AlertTriangle} color="text-amber-500">평가를 의미 있게 하려면</Sub>
        <Bullets
          items={[
            "임베딩 모델만 비교하려면 검색 방식을 '벡터'로 격리하십시오(하이브리드는 키워드 검색이 섞여 차이가 가려집니다).",
            "지식베이스에 문서가 1개뿐이면 무엇을 검색해도 1등이라 Hit Rate가 항상 1.0이 됩니다. 다른 주제의 문서를 함께 넣으십시오.",
            "여러 설정 조합을 한 번에 비교하려면 설정 스윕을 쓰십시오. 결과가 리더보드로 정리됩니다.",
          ]}
          icon={CheckCircle2}
          color="text-amber-500"
        />
      </section>

      <Callout>
        평가는 RAG의 나침반입니다. 모델·청킹·리랭커 등 무엇을 바꾸든, 바꾸기 전·후를 같은 골든셋으로 측정해
        <span className="font-medium text-foreground"> 숫자로 확인</span>하는 습관을 들이십시오.
      </Callout>
    </TabShell>
  )
}

// ---------------------------------------------------------------------------
// 피드백
// ---------------------------------------------------------------------------

function FeedbackTab() {
  return (
    <TabShell>
      <section>
        <Heading icon={ThumbsUp}>피드백 — 실제 사용에서 배우기</Heading>
        <p className="text-muted-foreground">
          피드백은 사용자가 답변에 남긴 <span className="font-medium text-foreground">👍/👎를 모아</span>, 나쁜 답변을
          평가용 질문으로 승격해 품질을 개선하는 곳입니다. <span className="font-medium text-foreground">실제 실패 사례가
          곧 다음 평가 문제</span>가 되는, 사용 → 평가 → 개선의 선순환을 만듭니다.
        </p>
      </section>

      <section>
        <Sub icon={MessageSquare}>무엇을 수집하나</Sub>
        <Bullets
          items={[
            <><span className="font-medium text-foreground">평점</span> — 👍 좋아요 / 👎 별로예요.</>,
            <><span className="font-medium text-foreground">수정 답변 · 기대 출처</span> — 사용자가 제시한 더 나은 답과 근거(선택). 골든셋으로 승격할 때 정답으로 활용됩니다.</>,
            <><span className="font-medium text-foreground">상태</span> — 신규(new) → 승격(promoted) / 무시(dismissed)로 처리 흐름을 관리합니다.</>,
          ]}
        />
      </section>

      <section>
        <Sub icon={RefreshCw} color="text-emerald-500">개선 루프</Sub>
        <p className="text-sm text-muted-foreground">
          답변 평점 수집 → 👎 사례 검토 → <span className="font-medium text-foreground">골든셋 항목으로 승격(promote)</span>
          {" "}→ 다음 평가에 반영 → 설정 개선. 이 과정을 반복할수록 평가셋이 현실에 가까워집니다.
        </p>
      </section>

      <Callout>
        👎 피드백에는 <span className="font-medium text-foreground">수정 답변과 기대 출처</span>를 함께 받도록 유도하십시오.
        승격 시 곧바로 양질의 골든셋 항목이 되어, <Link href="/dashboard/evaluation" className="text-primary hover:underline">평가</Link>의
        정확도가 올라갑니다.
      </Callout>
    </TabShell>
  )
}

// ---------------------------------------------------------------------------
// 검색 모델 파인튜닝
// ---------------------------------------------------------------------------

const FT_TARGETS: { target: string; effect: string; data: string; note: string }[] = [
  {
    target: "임베딩 모델",
    effect: "검색 정확도↑ (도메인 용어 이해)",
    data: "(질의, 정답 청크, 오답 청크) 트리플 수천~수만 건",
    note: "바꾸면 전체 재인덱싱 필요",
  },
  {
    target: "리랭커 (cross-encoder)",
    effect: "1차 검색 결과 재정렬 정밀화",
    data: "임베딩보다 적은 라벨로도 효과",
    note: "재인덱싱 불필요 — 먼저 검토 권장",
  },
  {
    target: "생성 LLM",
    effect: "답변 문체·형식·도메인 지식",
    data: "지시-응답 예시 데이터",
    note: "환각 감소는 RAG 자체가 더 효과적일 때 많음",
  },
]

function FineTuningTab() {
  return (
    <TabShell>
      <section>
        <Heading icon={GraduationCap}>검색 모델 파인튜닝 — 내 데이터로 길들이기</Heading>
        <p className="text-muted-foreground">
          여기서는 검색에 쓰는 모델, 즉 <span className="font-medium text-foreground">임베딩 모델과 리랭커</span>를
          <span className="font-medium text-foreground"> 내 도메인 데이터로 추가 학습</span>해 성능을 끌어올립니다(생성 LLM
          파인튜닝은 다루지 않습니다). 비용·전문성이 크므로, <span className="font-medium text-foreground">기성 모델 선택 · 설정
          튜닝 · 리랭커</span>를 모두 시도해 평가로 천장을 확인한 <em>뒤에</em> 검토하십시오.
        </p>
      </section>

      <section>
        <Sub icon={Wrench}>무엇을 파인튜닝할 수 있나</Sub>
        <div className="overflow-hidden rounded-lg border">
          <table className="w-full text-left text-sm">
            <thead className="bg-muted/50 text-muted-foreground">
              <tr>
                <th className="w-28 p-2">대상</th>
                <th className="p-2">효과</th>
                <th className="p-2">필요 데이터</th>
                <th className="p-2">주의</th>
              </tr>
            </thead>
            <tbody>
              {FT_TARGETS.map((r) => (
                <tr key={r.target} className="border-t align-top">
                  <td className="p-2 font-medium text-foreground">{r.target}</td>
                  <td className="p-2 text-muted-foreground">{r.effect}</td>
                  <td className="p-2 text-muted-foreground">{r.data}</td>
                  <td className="p-2 text-muted-foreground">{r.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-sm text-muted-foreground">
          임베딩보다 <span className="font-medium text-foreground">리랭커 파인튜닝</span>이 데이터가 적게 들고 재인덱싱도
          필요 없어, 보통 먼저 시도할 가치가 큽니다.
        </p>
      </section>

      <section>
        <Sub icon={Database}>데이터 준비 — 가장 큰 장벽</Sub>
        <Bullets
          items={[
            "임베딩 파인튜닝은 (질의, 정답 청크, 오답 청크) 형태의 라벨이 필요합니다. 이것을 모으지 못하면 시작할 수 없습니다.",
            "데이터 출처: 피드백 루프의 👍/👎, 검색 로그, 골든셋 확장, LLM으로 만든 합성 질의 등.",
            "오답(negative)을 잘 고르는 것이 품질을 좌우합니다 — 정답과 헷갈리기 쉬운 조각을 오답으로 쓰십시오.",
          ]}
        />
      </section>

      <section>
        <Sub icon={BarChart3}>절차</Sub>
        <p className="text-sm text-muted-foreground">
          베이스 모델 선정 → 데이터 수집·정제 → 학습(GPU) →{" "}
          <span className="font-medium text-foreground">평가로 전·후 비교</span> → 배포(임베딩이면 전체 재임베딩) →
          모니터링. 측정 없는 파인튜닝은 도박이니, 골든셋을 먼저 갖추십시오.
        </p>
      </section>

      <section>
        <Sub icon={GitBranch}>Argus ↔ 트레이너 연동 (retrieval-fine-tuning)</Sub>
        <p className="text-sm text-muted-foreground">
          실제 학습은 Argus가 직접 하지 않고 외부 트레이너{" "}
          <span className="font-mono text-sm">extensions/retrieval-fine-tuning</span>(sentence-transformers 기반)에
          위임합니다. <span className="font-medium text-foreground">데이터·평가 주도권은 Argus</span>가 쥐고{" "}
          <span className="font-medium text-foreground">학습 연산만 고객 GPU</span>에서 돌리는, 파일만 주고받는 느슨한 결합입니다.
        </p>

        <div className="mt-2 overflow-hidden rounded-lg border">
          <table className="w-full text-left text-sm">
            <thead className="bg-muted/50 text-muted-foreground">
              <tr>
                <th className="w-40 p-2">방향</th>
                <th className="p-2">주고받는 것 (파일 계약)</th>
              </tr>
            </thead>
            <tbody>
              <tr className="border-t align-top">
                <td className="p-2 font-medium text-foreground">Argus → 트레이너</td>
                <td className="p-2 text-muted-foreground">
                  데이터셋 디렉터리 — <span className="font-mono text-sm">manifest.json</span> +{" "}
                  <span className="font-mono text-sm">train.jsonl</span> /{" "}
                  <span className="font-mono text-sm">valid.jsonl</span> (질의·정답·오답).{" "}
                  <span className="font-medium text-foreground">test(홀드아웃)는 보내지 않아</span> 누수를 막습니다.
                </td>
              </tr>
              <tr className="border-t align-top">
                <td className="p-2 font-medium text-foreground">트레이너 → Argus</td>
                <td className="p-2 text-muted-foreground">
                  <span className="font-mono text-sm">model/</span> (학습된 모델) +{" "}
                  <span className="font-mono text-sm">metadata.json</span> (base_model·차원·task·valid 지표).
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <p className="mb-1 mt-3 text-sm font-medium text-foreground">연동 순서</p>
        <Bullets
          items={[
            <>
              <span className="font-medium text-foreground">① 데이터 내보내기</span> — 라벨링·피드백으로 모은 (질의·정답·오답)을 학습 데이터셋(JSONL)으로 내보냅니다.
            </>,
            <>
              <span className="font-medium text-foreground">② 학습(외부 GPU)</span> —{" "}
              <span className="font-mono text-sm">python -m finetune train --task embedding|reranker …</span>. 같은 데이터셋으로 임베딩·리랭커를 모두 학습할 수 있습니다.
            </>,
            <>
              <span className="font-medium text-foreground">③ 서빙</span> — 임베딩은{" "}
              <span className="font-mono text-sm">embedding_server</span>(TEI 호환), 리랭커는{" "}
              <span className="font-mono text-sm">reranker_server</span>로 띄웁니다(같은 extensions 폴더).
            </>,
            <>
              <span className="font-medium text-foreground">④ 컬렉션 연결</span> — 임베딩: 프로바이더 OpenAI호환 + 서버 URL(차원 일치). 리랭커: 리랭커 설정을 cross_encoder + 서버 URL로.
            </>,
            <>
              <span className="font-medium text-foreground">⑤ 평가·판정</span> — Argus 홀드아웃 골든셋으로 base와 fine-tuned를 평가/스윕해 Hit Rate·MRR로 비교합니다(합격 판정은 Argus).
            </>,
          ]}
        />

        <p className="mt-2 text-sm text-muted-foreground">
          임베딩 모델을 교체하면 <span className="font-medium text-foreground">전체 재인덱싱</span>이 필요하지만, 리랭커는 질의 시점 재정렬이라{" "}
          <span className="font-medium text-foreground">재인덱싱이 필요 없습니다</span>.
        </p>
      </section>

      <Callout>
        파인튜닝 전에 더 싼 대안을 먼저 소진하십시오 — <span className="font-medium text-foreground">더 맞는 기성
        모델 · 하이브리드 검색 · 리랭커 · 쿼리 재작성</span>. 자세한 순서는 <span className="font-medium text-foreground">&lsquo;임베딩
        모델이란?&rsquo;</span> 탭의 개선 단계를 참고하십시오.
      </Callout>
    </TabShell>
  )
}

// ---------------------------------------------------------------------------
// FAQ
// ---------------------------------------------------------------------------

const FAQS: { q: string; a: React.ReactNode }[] = [
  {
    q: "임베딩 모델을 직접 만들어야 하나요?",
    a: <>대부분은 아닙니다. 기성 모델 선택 + 설정 튜닝 + 리랭커로 충분합니다. 평가 숫자가 천장에 막혔고 라벨 데이터가 충분한 전문 도메인일 때만 파인튜닝을 검토하십시오.</>,
  },
  {
    q: "한글 문서에는 어떤 임베딩 모델을 쓰나요?",
    a: <>다국어 모델(<span className="font-mono text-sm">multilingual-e5-large</span> 등)을 쓰십시오. 영어 전용 모델은 한글 의미를 제대로 잡지 못해 검색 정확도가 크게 떨어집니다.</>,
  },
  {
    q: "검색 결과가 부정확합니다. 무엇부터 봐야 하나요?",
    a: <>① 임베딩 모델이 문서 언어와 맞는지 → ② 청크 크기·전략 → ③ 하이브리드 검색 + 리랭커 → ④ 평가로 측정, 순으로 점검하십시오. 모델을 바꾸기 전에 설정부터 조정하는 것이 쌉니다.</>,
  },
  {
    q: "청크 크기는 얼마가 좋나요?",
    a: <>글자 기준 800~1,200자, 오버랩은 크기의 10~20%를 권장합니다. 문서 성격에 따라 조정한 뒤 평가로 비교하십시오.</>,
  },
  {
    q: "스캔한 PDF인데 글자가 안 잡힙니다.",
    a: <>텍스트 레이어가 없는 이미지 PDF일 수 있습니다. 파싱 전략을 <span className="font-mono text-sm">vlm</span>으로 바꿔, 페이지 이미지를 읽어 변환하도록 하십시오.</>,
  },
  {
    q: "임베딩 모델을 나중에 바꿀 수 있나요?",
    a: <>가능하지만 벡터 공간이 바뀌므로 기존 문서를 전부 다시 임베딩(전체 재인덱싱)해야 합니다. 새 지식베이스로 만들어 평가로 비교한 뒤 전환하시길 권합니다.</>,
  },
  {
    q: "평가는 꼭 해야 하나요?",
    a: <>예. 설정 변경이 실제로 품질을 올렸는지 확인하는 유일한 방법입니다. 단, 변별력을 위해 문서를 여러 개 넣고 골든셋을 갖추십시오.</>,
  },
  {
    q: "리랭커는 언제 켜나요?",
    a: <>정확도를 더 높이고 싶을 때 켜십시오. 재인덱싱이 필요 없으니, 평가로 켜고/끈 점수를 비교해 효과를 확인한 뒤 결정하면 됩니다.</>,
  },
  {
    q: "외부 임베딩 서버가 꼭 필요한가요?",
    a: <>아닙니다. &lsquo;로컬&rsquo;(FastEmbed) 프로바이더로 서버 없이 쓸 수 있습니다. bge-m3 등 일부 모델만 외부 임베딩 서버가 필요합니다.</>,
  },
  {
    q: "하이브리드 검색이 뭔가요?",
    a: <>의미 기반 벡터 검색과 키워드(렉시컬) 검색을 함께 써 결과를 합치는 방식입니다. 고유명사·코드·숫자처럼 벡터가 놓치는 정확 일치를 렉시컬이 보완해, 한쪽만 쓸 때보다 대체로 안정적입니다.</>,
  },
  {
    q: "문서를 수정·삭제하면 검색에 바로 반영되나요?",
    a: <>수정한 문서는 다시 인제스천(파싱→청킹→임베딩→색인)해야 반영됩니다. 삭제하면 해당 청크도 함께 제거됩니다. 원본만 바꾸고 재인덱싱하지 않으면 옛 내용이 계속 검색되니 주의하십시오.</>,
  },
  {
    q: "검색은 맞는데 LLM 답변이 이상합니다.",
    a: <>검색 단계와 생성 단계를 분리해 보십시오. 상위 청크에 정답 근거가 있는데 답이 틀리면 생성(LLM·프롬프트) 문제, 근거 자체가 안 올라오면 검색 문제입니다. 평가의 검색 지표(Hit·MRR)로 어느 쪽인지 먼저 가르십시오.</>,
  },
  {
    q: "외부 앱에서 로그인 없이 검색·질의를 호출할 수 있나요?",
    a: <>예. 관리 &gt; API 키에서 서비스 계정 키(<span className="font-mono text-sm">argus_sk_…</span>)를 발급해 <span className="font-mono text-sm">X-API-Key</span> 헤더 또는 <span className="font-mono text-sm">Authorization: Bearer</span>로 호출하면 됩니다. 평문 키는 발급 시 1회만 노출되니 즉시 보관하고, 역할(role)로 권한을 제한하며, 유출 시 해당 키만 폐기하십시오.</>,
  },
  {
    q: "어떤 파일 형식을 지원하나요?",
    a: <>PDF·오피스(워드·PPT·엑셀, 구형 <span className="font-mono text-sm">.doc/.ppt/.xls</span> 포함)·텍스트/마크다운 등을 지원합니다. 스캔 이미지 PDF처럼 텍스트 레이어가 없는 파일은 파싱 전략을 <span className="font-mono text-sm">vlm</span>으로 두어 페이지 이미지를 읽도록 하십시오.</>,
  },
]

// ---------------------------------------------------------------------------
// 확장(Extensions)
// ---------------------------------------------------------------------------

// Argus ↔ 확장 연동 흐름(다이어그램용).
const EXT_FLOW: { dir: string; proto: string; sub: string; name: string; desc: string }[] = [
  { dir: "→", proto: "HTTP /v1/embeddings", sub: "OpenAI 호환", name: "embedding_server", desc: "임베딩 추론 (FastEmbed·ONNX)" },
  { dir: "→", proto: "HTTP /rerank", sub: "cross_encoder", name: "reranker_server", desc: "리랭크 추론 (cross-encoder)" },
  { dir: "↔", proto: "파일 dataset/ ↔ model/", sub: "오프라인 · GPU", name: "retrieval-fine-tuning", desc: "임베딩·리랭커 모델 학습" },
]

// 확장별 용도·연동·필요성.
const EXT_ROWS: { name: string; use: string; link: string; need: string }[] = [
  {
    name: "embedding_server",
    use: "커스텀·파인튜닝 임베딩 모델 서빙(인덱싱·질의 시 임베딩 추론).",
    link: "HTTP — OpenAI 호환 /v1/embeddings. 컬렉션 프로바이더를 'OpenAI 호환'으로 두고 URL을 가리킴(차원 일치).",
    need: "선택 — 기본은 로컬 FastEmbed/내장 임베딩으로 충분. 파인튜닝·특정 모델을 서빙할 때 필요.",
  },
  {
    name: "reranker_server",
    use: "cross-encoder 리랭커 서빙(1차 검색 top-N을 질의 관련도로 재정렬).",
    link: "HTTP — /rerank(TEI 호환). 컬렉션 rerank.provider=cross_encoder + 서버 URL.",
    need: "선택 — 리랭크 미사용/local·llm 리랭커면 불필요. cross_encoder(특히 파인튜닝)를 쓸 때 필요.",
  },
  {
    name: "retrieval-fine-tuning",
    use: "임베딩·리랭커 모델을 도메인 데이터로 학습(오프라인, GPU).",
    link: "파일 — Argus가 데이터셋(dataset/) 내보내고 트레이너가 모델(model/) 반환. HTTP 호출 아님.",
    need: "선택(고급) — 기성 모델로 천장에 막히고 라벨이 충분한 전문 도메인일 때만.",
  },
]

function ExtensionsDiagram() {
  return (
    <div className="overflow-x-auto">
      <div className="grid min-w-[520px] grid-cols-[minmax(130px,1fr)_minmax(150px,auto)_minmax(170px,1.3fr)] items-stretch gap-3 rounded-lg border bg-muted/20 p-3 text-xs">
        <div className="row-span-3 flex flex-col justify-center rounded-md border bg-background p-3">
          <div className="text-sm font-semibold text-foreground">Argus RAG Studio</div>
          <div className="mt-1 text-muted-foreground">app/ · PostgreSQL · pgvector</div>
          <div className="mt-2 text-[11px] text-muted-foreground">인덱싱 · 질의 · 평가</div>
        </div>
        {EXT_FLOW.map((f) => (
          <Fragment key={f.name}>
            <div className="flex flex-col items-center justify-center text-center text-muted-foreground">
              <span className="font-mono text-sm text-foreground">{f.proto}</span>
              <span className="text-lg leading-none">{f.dir}</span>
              <span className="text-[10px]">{f.sub}</span>
            </div>
            <div className="flex flex-col justify-center rounded-md border bg-background p-2.5">
              <div className="font-mono text-sm font-medium text-foreground">{f.name}</div>
              <div className="mt-0.5 text-[11px] text-muted-foreground">{f.desc}</div>
            </div>
          </Fragment>
        ))}
      </div>
      <p className="mt-1 text-[11px] text-muted-foreground">
        화살표 = 연동 방식(HTTP 추론 호출 / 파일 교환). 모든 확장은 독립 배포이며 선택 사항입니다.
      </p>
    </div>
  )
}

function ExtensionsTab() {
  return (
    <TabShell>
      <section>
        <Heading icon={Boxes}>확장(Extensions) — 외부 서버·트레이너 연동</Heading>
        <p className="text-muted-foreground">
          <span className="font-mono text-sm">extensions/</span> 폴더에는 RAG Studio와{" "}
          <span className="font-medium text-foreground">독립적으로 배포</span>되는 선택적 구성요소가 있습니다. 모두{" "}
          <span className="font-medium text-foreground">옵션</span>이라 기본 RAG는 이것들 없이도 동작하며, 커스텀·파인튜닝
          모델을 쓰거나 추론을 분리·확장할 때 붙입니다.
        </p>
      </section>

      <section>
        <Sub icon={GitBranch}>연동 그림</Sub>
        <ExtensionsDiagram />
      </section>

      <section>
        <Sub icon={Wrench}>무엇에 쓰나 · 꼭 필요한가</Sub>
        <div className="overflow-hidden rounded-lg border">
          <table className="w-full text-left text-sm">
            <thead className="bg-muted/50 text-muted-foreground">
              <tr>
                <th className="w-40 p-2">확장</th>
                <th className="p-2">용도</th>
                <th className="p-2">연동 방식</th>
                <th className="p-2">꼭 필요한가</th>
              </tr>
            </thead>
            <tbody>
              {EXT_ROWS.map((r) => (
                <tr key={r.name} className="border-t align-top">
                  <td className="p-2 font-mono text-sm text-foreground">{r.name}</td>
                  <td className="p-2 text-muted-foreground">{r.use}</td>
                  <td className="p-2 text-muted-foreground">{r.link}</td>
                  <td className="p-2 text-muted-foreground">{r.need}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <Callout>
        세 가지 모두 <span className="font-medium text-foreground">선택</span>입니다. 기본값(로컬 FastEmbed 임베딩, 리랭크
        off 또는 local/llm)으로 시작하고, 평가가 천장에 막히거나 도메인 특화가 필요할 때{" "}
        <span className="font-medium text-foreground">임베딩 서버 → 리랭커 서버 → 파인튜닝</span> 순으로 단계적으로 도입하십시오.
        (같은 폴더의 <span className="font-mono text-sm">detection_server</span>·
        <span className="font-mono text-sm">nifi-cluster-deploy</span>는 각각 자동 bbox 검출·수집 파이프라인용으로, 검색 품질과는 별개입니다.)
      </Callout>
    </TabShell>
  )
}

// ---------------------------------------------------------------------------
// 대량 처리
// ---------------------------------------------------------------------------

// 단일 GPU 기준 시작값.
const BULK_GPU_ROWS: { item: string; val: string; note: string }[] = [
  { item: "embedding.batch_size", val: "64", note: "설정>임베딩. A100-80GB면 96~128" },
  { item: "워커 레플리카 수", val: "6~8", note: "동시 처리 문서 수 = 레플리카 수" },
  { item: "TEI --max-client-batch-size", val: "≥ batch (예 128)", note: "이보다 작으면 요청 거부" },
  { item: "TEI --max-concurrent-requests", val: "12~16", note: "워커수 ×1.5" },
  { item: "TEI --max-batch-tokens", val: "24GB ~16384 / 80GB 32768+", note: "VRAM 따라" },
]

const BULK_MODEL_ROWS: { model: string; batch: string; worker: string }[] = [
  { model: "bge-m3 (다국어·무거움, 1024)", batch: "64 (~128)", worker: "6~8 / GPU" },
  { model: "e5-base / small (가벼움)", batch: "128~256", worker: "6~8 / GPU" },
  { model: "MiniLM 류 (매우 가벼움)", batch: "256+", worker: "6~8 / GPU" },
]

// 파싱(인제스천)을 트리거하는 API. 별도 '파싱 API'는 없고, ingest/register 가 잡을 큐에 넣으면
// 워커가 파싱→청킹→임베딩→색인까지 수행한다.
const BULK_API_ROWS: { method: string; path: string; use: string }[] = [
  {
    method: "POST",
    path: "/api/v1/collections/{id}/ingest",
    use: "파일 업로드(multipart, 사용자 JWT) → 잡 enqueue. 응답의 job_id 로 진행률 폴링.",
  },
  {
    method: "POST",
    path: "/api/v1/ingestion/register",
    use: "외부(NiFi 등)용 — 이미 S3 에 올린 원본의 위치(source_uri)만 전송(서비스 토큰). 대량 인입 권장.",
  },
  {
    method: "GET",
    path: "/api/v1/ingestion/jobs/{job_id}",
    use: "잡 상태·진행률 폴링(status · stage(parse/chunk/embed/index) · progress).",
  },
  {
    method: "GET",
    path: "/api/v1/documents/{uuid}/parse-preview",
    use: "(검증) 저장·임베딩 없이 파싱 결과만 미리보기.",
  },
]

// 대량 처리 flow — mermaid 다이어그램(클라이언트 렌더).
const BULK_FLOW_CHART = `flowchart TB
  IN["수집<br/>NiFi · register API · 업로드"] -->|"잡 enqueue"| Q["잡 큐<br/>rag_ingestion_jobs (DB)"]
  Q -->|"claim · SKIP LOCKED"| W["워커 ×N (레플리카)<br/>파싱 → 청킹 → 임베딩 → 색인"]
  W -->|"완료"| EV["평가<br/>골든셋 Hit · MRR"]
  W <-->|"HTTP /v1/embeddings (배치)"| GPU["GPU 임베딩 서버<br/>TEI · vLLM"]
  UI["UI (웹 화면)"] -.->|"잡 넣는 입구"| Q
  classDef hot fill:#eef2ff,stroke:#6366f1,color:#1e1b4b;
  classDef gpu fill:#ecfdf5,stroke:#10b981,color:#064e3b;
  classDef ui fill:#f8fafc,stroke:#cbd5e1,color:#64748b;
  class W hot
  class GPU gpu
  class UI ui
`

function BulkProcessingTab() {
  return (
    <TabShell>
      <section>
        <Heading icon={Gauge}>대량 처리 — 초기·대량 인덱싱을 빠르게</Heading>
        <p className="text-muted-foreground">
          수만~수십만 청크를 처음 인덱싱하거나, 모델 교체로 전체를 다시 임베딩할 때의 권장 구성입니다.
          대량 인덱싱의 병목은 보통 <span className="font-medium text-foreground">임베딩</span>이며(파싱이 vlm/docai면 파싱),
          핵심은 <span className="font-medium text-foreground">GPU 임베딩 서버 + 워커 수평 확장 + 큰 배치</span>입니다.
        </p>
      </section>

      <section>
        <Sub icon={Layers}>전체 흐름</Sub>
        <p className="mb-3 text-sm text-muted-foreground">
          수집(NiFi·폴더 업로드) → 파싱 → 청킹 → <span className="font-medium text-foreground">임베딩(GPU)</span> → 색인 → 평가.
          각 단계는 비동기 워커가 처리하고, 문서 단위로 병렬화됩니다.
        </p>
        <Mermaid chart={BULK_FLOW_CHART} />
        <p className="mt-1 text-xs text-muted-foreground">
          UI(웹 화면)는 큐에 잡을 넣는 입구일 뿐이며, 실제 파싱·임베딩·색인은 워커가 비동기로 처리합니다(처리 루프 밖).
        </p>
      </section>

      <section>
        <Sub icon={GitBranch}>RAG Studio를 통한 배치 처리 (우회하지 않기)</Sub>
        <p className="text-sm text-muted-foreground">
          대량 처리도 RAG Studio를 <span className="font-medium text-foreground">우회하지 않습니다.</span> 인제스천은 이미
          <span className="font-medium text-foreground"> 큐 기반 비동기 배치</span>라, UI는 잡을 넣는 입구일 뿐 실제 파싱·청킹·임베딩·색인은
          백엔드 워커가 처리합니다. 따라서 대량은 <span className="font-medium text-foreground">&lsquo;UI 클릭&rsquo;이 아니라
          register API/NiFi로 인입</span>하고 <span className="font-medium text-foreground">워커(레플리카)를 늘려 병렬화</span>하면 됩니다 —
          무거운 임베딩 연산만 외부 GPU 서버로 오프로드합니다.
        </p>
        <Callout>
          청크 메타데이터 · tsvector(BM25) · 컬렉션의 고정 임베딩 모델/차원 · 평가 일관성은 스튜디오의 인제스천 파이프라인이
          보장합니다. 그래서 <span className="font-medium text-foreground">벡터를 외부에서 직접 적재해 파이프라인을 우회하는 방식은
          비권장</span>입니다(위 항목을 직접 재현해야 하고 일관성이 깨집니다). &ldquo;배치처럼&rdquo;은 맞지만,
          <span className="font-medium text-foreground"> 그 배치가 스튜디오 백엔드를 통해</span> 돌게 하십시오.
        </Callout>
      </section>

      <section>
        <Sub icon={Boxes}>1) GPU 임베딩 서버 (핵심)</Sub>
        <Bullets
          items={[
            <>
              임베딩을 로컬 FastEmbed(CPU)가 아니라 <span className="font-medium text-foreground">GPU 서버(TEI 또는 vLLM)</span>로 돌립니다.
              컬렉션 프로바이더를 <span className="font-mono text-sm">openai_compatible</span>로 두고 서버 URL을 가리킵니다.
            </>,
            <>
              ⚠️ <span className="font-medium text-foreground">색인에 쓴 모델 = 질의에 쓰는 모델</span>이어야 합니다. 나중에 모델을 바꾸면
              전체 재임베딩이므로 <span className="font-medium text-foreground">처음부터 최종(운영) 모델</span>로 시작하십시오.
            </>,
            <>
              같은 폴더의 <span className="font-mono text-sm">embedding_server</span>는 CPU(FastEmbed)라 GPU 가속은 안 됩니다 —
              GPU 대량엔 TEI/vLLM, CPU만 가능하면 <span className="font-mono text-sm">embedding_server</span>를 여러 레플리카로.
            </>,
          ]}
        />
        <div className="mt-2 overflow-hidden rounded-lg border">
          <table className="w-full text-left text-sm">
            <thead className="bg-muted/50 text-muted-foreground">
              <tr>
                <th className="w-64 p-2">항목 (단일 GPU 기준)</th>
                <th className="w-40 p-2">시작값</th>
                <th className="p-2">비고</th>
              </tr>
            </thead>
            <tbody>
              {BULK_GPU_ROWS.map((r) => (
                <tr key={r.item} className="border-t align-top">
                  <td className="p-2 font-mono text-sm text-foreground">{r.item}</td>
                  <td className="p-2 font-medium text-foreground">{r.val}</td>
                  <td className="p-2 text-muted-foreground">{r.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <Sub icon={RefreshCw}>2) 워커 병렬화 (수평 확장)</Sub>
        <Bullets
          items={[
            <>
              인제스천 워커는 <span className="font-medium text-foreground">백엔드 프로세스당 1개</span>이며 문서를 1건씩 순차 처리합니다.
              따라서 <span className="font-medium text-foreground">"워커 수 = 백엔드(워커) 레플리카 수"</span>입니다.
            </>,
            <>
              여러 레플리카를 띄우면 <span className="font-mono text-sm">FOR UPDATE SKIP LOCKED</span>로 충돌 없이 문서 단위 병렬 처리됩니다
              (잡 중복 없음).
            </>,
            <>
              <span className="font-medium text-foreground">DB 커넥션 풀</span>을 워커 수에 맞춰 키우십시오(워커마다 세션 사용) —
              <span className="font-mono text-sm"> pool ≥ 워커수 + API 여유분</span>. 안 그러면 풀 고갈로 병목.
            </>,
          ]}
        />
      </section>

      <section>
        <Sub icon={Boxes}>3) 멀티 GPU</Sub>
        <p className="text-sm text-muted-foreground">
          <span className="font-medium text-foreground">GPU당 TEI 1개</span>를 띄워 로드밸런서(nginx 등) 뒤에 두고 백엔드가 LB URL을 가리킵니다.
          <span className="font-medium text-foreground"> 워커 레플리카 = 6~8 × GPU 수</span>(4 GPU → 24~32), 배치 64~128. 처리량은 GPU 수에 거의 선형으로 증가합니다.
        </p>
      </section>

      <section>
        <Sub icon={Upload}>4) 수집(인입) 대량화</Sub>
        <Bullets
          items={[
            <>
              <span className="font-medium text-foreground">NiFi</span>(<span className="font-mono text-sm">nifi-cluster-deploy</span>)로 외부 소스를 모아
              <span className="font-mono text-sm"> /ingestion/register</span>(서비스 토큰)로 인입 — 대규모 파이프라인에 적합.
            </>,
            <>소규모·수동이면 컬렉션 화면의 폴더 업로드로 충분합니다.</>,
          ]}
        />
      </section>

      <section>
        <Sub icon={Upload}>파싱(인제스천) 트리거 API</Sub>
        <p className="mb-2 text-sm text-muted-foreground">
          <span className="font-medium text-foreground">별도 &lsquo;파싱 API&rsquo;는 없습니다.</span> 아래 인입 API가 잡을 큐에 넣으면,
          워커가 <span className="font-medium text-foreground">파싱 → 청킹 → 임베딩 → 색인</span>까지 한 번에 수행합니다.
        </p>
        <div className="overflow-hidden rounded-lg border">
          <table className="w-full text-left text-sm">
            <thead className="bg-muted/50 text-muted-foreground">
              <tr>
                <th className="w-16 p-2">메서드</th>
                <th className="p-2">엔드포인트</th>
                <th className="p-2">용도</th>
              </tr>
            </thead>
            <tbody>
              {BULK_API_ROWS.map((r) => (
                <tr key={r.path} className="border-t align-top">
                  <td className="p-2 font-mono text-sm text-foreground">{r.method}</td>
                  <td className="p-2 font-mono text-sm text-foreground">{r.path}</td>
                  <td className="p-2 text-muted-foreground">{r.use}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <Sub icon={Layers}>큐잉은 어떻게 동작하나</Sub>
        <Bullets
          items={[
            <>
              인입 API가 <span className="font-mono text-sm">rag_ingestion_jobs</span> 에 잡을 생성합니다
              (<span className="font-mono text-sm">status=queued</span>, progress=0).
            </>,
            <>
              워커 루프가 주기적으로 폴링하며 잡을 <span className="font-medium text-foreground">원자적으로 집습니다</span> —
              <span className="font-mono text-sm"> SELECT … WHERE status=&apos;queued&apos; ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED</span> →
              <span className="font-mono text-sm"> running</span> 으로 표시.
            </>,
            <>
              집은 잡을 처리: <span className="font-medium text-foreground">parse → chunk → embed → index</span>,{" "}
              <span className="font-mono text-sm">stage</span>·<span className="font-mono text-sm">progress(0~100)</span> 갱신 →{" "}
              <span className="font-mono text-sm">succeeded</span> / <span className="font-mono text-sm">failed</span>.
            </>,
            <>
              <span className="font-medium text-foreground">SKIP LOCKED</span> 덕분에 여러 워커(레플리카)가 동시에 폴링해도 같은 잡을
              중복으로 집지 않습니다 → 레플리카만 늘리면 <span className="font-medium text-foreground">안전하게 수평 확장</span>(문서 단위 병렬).
            </>,
            <>
              실패 잡은 <span className="font-mono text-sm">error</span> 가 기록되며,{" "}
              <span className="font-mono text-sm">POST /api/v1/documents/{"{uuid}"}/reindex</span> 로 재처리합니다.
            </>,
          ]}
        />
      </section>

      <section>
        <Sub icon={Gauge}>모델별 배치 가이드</Sub>
        <div className="overflow-hidden rounded-lg border">
          <table className="w-full text-left text-sm">
            <thead className="bg-muted/50 text-muted-foreground">
              <tr>
                <th className="p-2">임베딩 모델</th>
                <th className="w-32 p-2">batch_size</th>
                <th className="w-32 p-2">워커</th>
              </tr>
            </thead>
            <tbody>
              {BULK_MODEL_ROWS.map((r) => (
                <tr key={r.model} className="border-t align-top">
                  <td className="p-2 text-muted-foreground">{r.model}</td>
                  <td className="p-2 font-medium text-foreground">{r.batch}</td>
                  <td className="p-2 text-muted-foreground">{r.worker}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <Sub icon={ClipboardCheck}>튜닝 루프</Sub>
        <Bullets
          items={[
            <>batch 64 / 워커 6으로 시작합니다.</>,
            <>
              <span className="font-mono text-sm">nvidia-smi</span> 로 GPU 사용률 확인 →{" "}
              <span className="font-medium text-foreground">{"<"} 80%</span>면 워커 +2씩(또는 batch↑),{" "}
              <span className="font-medium text-foreground">OOM</span>이면 batch 또는 max-batch-tokens↓.
            </>,
            <>파싱이 무거우면(layout/docai/vlm) GPU가 노므로 워커를 더 — CPU 파싱과 GPU 임베딩이 겹쳐 처리량↑.</>,
          ]}
        />
      </section>

      <Callout>
        대량 처리 전 반드시 <span className="font-medium text-foreground">최종 임베딩 모델을 확정</span>하십시오(중간 변경 = 전체 재임베딩).
        그리고 소량으로 <span className="font-medium text-foreground">평가(골든셋)</span>를 먼저 돌려 설정이 맞는지 확인한 뒤 전체를 인덱싱하면
        대량 재작업을 피할 수 있습니다.
      </Callout>
    </TabShell>
  )
}

function FaqTab() {
  return (
    <TabShell>
      <section>
        <Heading icon={HelpCircle}>자주 묻는 질문 (FAQ)</Heading>
        <p className="text-muted-foreground">RAG를 처음 다룰 때 자주 막히는 지점을 모았습니다.</p>
      </section>

      <div className="flex flex-col divide-y rounded-lg border">
        {FAQS.map((f, i) => (
          <div key={i} className="flex flex-col gap-1 p-3">
            <p className="flex items-start gap-2 text-sm font-medium text-foreground">
              <HelpCircle className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
              {f.q}
            </p>
            <p className="pl-6 text-sm leading-relaxed text-muted-foreground">{f.a}</p>
          </div>
        ))}
      </div>
    </TabShell>
  )
}

export default function RagOverviewPage() {
  return (
    <>
      <DashboardHeader title="RAG 개요" />
      <div className="flex flex-1 flex-col p-4">
        <UrlTabs defaultValue="flow" className="gap-4">
          <TabsList>
            <TabsTrigger value="flow">처리 순서</TabsTrigger>
            <TabsTrigger value="embedding">임베딩 모델이란?</TabsTrigger>
            <TabsTrigger value="parsing">파싱</TabsTrigger>
            <TabsTrigger value="chunking">청킹</TabsTrigger>
            <TabsTrigger value="pipeline">파이프라인</TabsTrigger>
            <TabsTrigger value="evaluation">평가</TabsTrigger>
            <TabsTrigger value="feedback">피드백</TabsTrigger>
            <TabsTrigger value="finetuning">검색 모델 파인튜닝</TabsTrigger>
            <TabsTrigger value="extensions">확장(Extensions)</TabsTrigger>
            <TabsTrigger value="bulk">대량 처리</TabsTrigger>
            <TabsTrigger value="faq">FAQ</TabsTrigger>
          </TabsList>
          <TabsContent value="flow">
            <FlowTab />
          </TabsContent>
          <TabsContent value="embedding">
            <EmbeddingTab />
          </TabsContent>
          <TabsContent value="parsing">
            <ParsingTab />
          </TabsContent>
          <TabsContent value="chunking">
            <ChunkingTab />
          </TabsContent>
          <TabsContent value="pipeline">
            <PipelineTab />
          </TabsContent>
          <TabsContent value="evaluation">
            <EvaluationTab />
          </TabsContent>
          <TabsContent value="feedback">
            <FeedbackTab />
          </TabsContent>
          <TabsContent value="finetuning">
            <FineTuningTab />
          </TabsContent>
          <TabsContent value="extensions">
            <ExtensionsTab />
          </TabsContent>
          <TabsContent value="bulk">
            <BulkProcessingTab />
          </TabsContent>
          <TabsContent value="faq">
            <FaqTab />
          </TabsContent>
        </UrlTabs>
      </div>
    </>
  )
}
