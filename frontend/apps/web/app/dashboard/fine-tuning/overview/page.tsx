"use client"

// 파인 튜닝 개요 — 처음 사용하는 분이 파인튜닝의 전체 절차를 익히도록 돕는 화면.
// 절차(데이터 준비 → 학습 → 검증·적용)를 다이어그램으로 보여주고, 언제/입력데이터/
// 임베딩vs리랭커/역할분리/FAQ 를 탭으로 제공한다. 설명은 격식체(~하십시오)로 통일한다.
// 설계 배경: design/fine-tuning.md

import Link from "next/link"
import {
  BookA,
  ClipboardCheck,
  Database,
  Upload,
  Cpu,
  Server,
  RefreshCw,
  ChevronRight,
  ChevronDown,
  Gauge,
  Wrench,
  GraduationCap,
  CheckCircle2,
  AlertTriangle,
  Languages,
  Boxes,
  ListFilter,
  BarChart3,
  HelpCircle,
  Lock,
  RotateCw,
  Sparkles,
  Scale,
  type LucideIcon,
} from "lucide-react"
import { TabsContent, TabsList, TabsTrigger } from "@workspace/ui/components/tabs"
import { DashboardHeader } from "@/components/dashboard-header"
import { UrlTabs } from "@/components/url-tabs"

// ---------------------------------------------------------------------------
// 공용 빌딩 블록
// ---------------------------------------------------------------------------

type Owner = "argus" | "external" | null
type Cost = "index" | "query" | null

interface Step {
  n: number
  title: string
  icon: LucideIcon
  desc: string
  owner: Owner
  href?: string
}

interface Phase {
  id: string
  label: string
  intro: string
  accentBorder: string
  steps: Step[]
}

const PHASES: Phase[] = [
  {
    id: "prepare",
    label: "① 데이터 준비 (Argus)",
    intro:
      "학습에 쓸 데이터를 정의·정제·내보내는 단계입니다. Argus 가 담당하며, 제품을 잘 쓰면 피드백 루프로 데이터가 자연히 쌓입니다.",
    accentBorder: "border-sky-500",
    steps: [
      { n: 1, title: "용어 사전 정의", icon: BookA, owner: "argus", desc: "전문용어·동의어·약어를 등록합니다. 합성 질의 생성과 하드네거티브 마이닝에 활용됩니다.", href: "/dashboard/fine-tuning/glossary" },
      { n: 2, title: "라벨링(정답지)", icon: ClipboardCheck, owner: "argus", desc: "질의에 대한 정답·오답 청크를 전문가가 검수해 확정합니다. 도메인 품질의 핵심입니다.", href: "/dashboard/fine-tuning/labeling" },
      { n: 3, title: "학습 데이터셋 구성", icon: Database, owner: "argus", desc: "피드백·골든셋·트레이스를 (질의, 정답, 오답) 트리플로 조립하고 하드네거티브를 마이닝합니다.", href: "/dashboard/fine-tuning/datasets" },
      { n: 4, title: "데이터셋 내보내기", icon: Upload, owner: "argus", desc: "train/valid 를 JSONL 로 내보냅니다. test(홀드아웃)는 Argus 가 보관해 객관적 평가에 씁니다.", href: "/dashboard/fine-tuning/datasets" },
    ],
  },
  {
    id: "train",
    label: "② 학습 (외부 프로그램)",
    intro:
      "실제 학습 연산은 교체 가능한 외부 트레이너가 담당합니다. Argus 는 잡을 트리거하고 상태만 추적합니다.",
    accentBorder: "border-amber-500",
    steps: [
      { n: 5, title: "외부 학습 실행", icon: Cpu, owner: "external", desc: "extensions/retrieval-fine-tuning 트레이너가 데이터셋을 받아 임베딩/리랭커를 파인튜닝합니다(GPU)." },
    ],
  },
  {
    id: "verify",
    label: "③ 검증·적용 (Argus)",
    intro:
      "학습 결과를 등록·서빙하고, 좋아졌는지 숫자로 판정해 적용하거나 데이터를 보강해 반복합니다.",
    accentBorder: "border-emerald-500",
    steps: [
      { n: 6, title: "모델 등록·서빙", icon: Server, owner: "argus", desc: "결과 모델을 레지스트리에 등록하고 임베딩/리랭크 서버로 서빙해 컬렉션에 연결합니다.", href: "/dashboard/fine-tuning/models" },
      { n: 7, title: "평가 (base vs tuned)", icon: BarChart3, owner: "argus", desc: "홀드아웃 골든셋으로 기존 모델과 Hit Rate·MRR 을 나란히 비교합니다.", href: "/dashboard/evaluation" },
      { n: 8, title: "적용 또는 반복", icon: RefreshCw, owner: "argus", desc: "개선됐으면 컬렉션에 적용하고, 부족하면 데이터를 보강해 다시 반복합니다." },
    ],
  },
]

function OwnerBadge({ owner }: { owner: Owner }) {
  if (owner === "argus") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full border border-sky-500/40 bg-sky-500/10 px-1.5 py-0.5 text-[10px] font-medium text-sky-600 dark:text-sky-400">
        Argus
      </span>
    )
  }
  if (owner === "external") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-600 dark:text-amber-400">
        <Cpu className="h-2.5 w-2.5" /> 외부 학습
      </span>
    )
  }
  return null
}

function CostBadge({ cost }: { cost: Cost }) {
  if (cost === "index") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-600 dark:text-amber-400">
        <Lock className="h-2.5 w-2.5" /> 재인덱싱 필요
      </span>
    )
  }
  if (cost === "query") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full border border-emerald-500/40 bg-emerald-500/10 px-1.5 py-0.5 text-[10px] font-medium text-emerald-600 dark:text-emerald-400">
        <RotateCw className="h-2.5 w-2.5" /> 재인덱싱 불필요
      </span>
    )
  }
  return null
}

function StepCard({ step }: { step: Step }) {
  const Icon = step.icon
  const inner = (
    <div className="flex h-full w-[210px] shrink-0 flex-col gap-2 rounded-lg border bg-card p-3 transition-colors hover:border-primary/50 hover:bg-accent/40">
      <div className="flex items-center gap-2">
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary/10 text-sm font-bold text-primary">
          {step.n}
        </span>
        <Icon className="h-4 w-4 text-muted-foreground" />
        <span className="truncate text-sm font-semibold text-foreground">{step.title}</span>
      </div>
      <p className="text-sm leading-relaxed text-muted-foreground">{step.desc}</p>
      <div className="mt-auto flex items-center justify-between pt-1">
        <OwnerBadge owner={step.owner} />
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

function Heading({ icon: Icon, children }: { icon: LucideIcon; children: React.ReactNode }) {
  return (
    <div className="mb-1 flex items-center gap-2">
      <Icon className="h-4 w-4 text-primary" />
      <h2 className="text-base font-semibold">{children}</h2>
    </div>
  )
}

function Sub({ icon: Icon, color = "text-primary", children }: { icon: LucideIcon; color?: string; children: React.ReactNode }) {
  return (
    <div className="mb-2 flex items-center gap-2">
      <Icon className={`h-4 w-4 ${color}`} />
      <h3 className="text-sm font-semibold">{children}</h3>
    </div>
  )
}

function Bullets({ items, icon: Icon = ChevronRight, color = "text-muted-foreground/60" }: { items: React.ReactNode[]; icon?: LucideIcon; color?: string }) {
  return (
    <ul className="flex flex-col gap-1.5">
      {items.map((it, i) => (
        <li key={i} className="flex gap-2 text-sm text-muted-foreground">
          <Icon className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${color}`} />
          <span>{it}</span>
        </li>
      ))}
    </ul>
  )
}

function Callout({ icon: Icon = Sparkles, children }: { icon?: LucideIcon; children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-2 rounded-lg border border-dashed bg-muted/30 p-3 text-sm text-muted-foreground">
      <Icon className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
      <span>{children}</span>
    </div>
  )
}

const TabShell = ({ children }: { children: React.ReactNode }) => (
  <div className="flex max-w-3xl flex-col gap-6 text-sm leading-relaxed">{children}</div>
)

// ---------------------------------------------------------------------------
// 탭 1 — 절차
// ---------------------------------------------------------------------------

function FlowTab() {
  return (
    <div className="flex flex-col gap-6">
      <div className="max-w-3xl">
        <h2 className="text-lg font-semibold">파인튜닝은 어떤 절차로 진행되나요?</h2>
        <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
          파인튜닝은 기성 모델을 내 도메인 데이터로 추가 학습해 검색 정확도를 끌어올리는 작업입니다.
          Argus 는 <span className="font-medium text-foreground">데이터 준비와 평가</span>를 담당하고, 실제 학습은
          <span className="font-medium text-foreground"> 외부 트레이너</span>가 담당합니다. 아래 순서대로 진행하십시오.
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
          <span className="inline-flex items-center gap-1">
            <OwnerBadge owner="argus" /> Argus 가 수행(데이터·평가)
          </span>
          <span className="inline-flex items-center gap-1">
            <OwnerBadge owner="external" /> 외부 프로그램이 수행(학습 연산)
          </span>
        </div>
      </div>

      {PHASES.map((phase, pi) => (
        <div key={phase.id}>
          <div className={`mb-2 border-l-2 ${phase.accentBorder} pl-3`}>
            <h3 className="text-sm font-semibold text-foreground">{phase.label}</h3>
            <p className="mt-0.5 max-w-3xl text-sm leading-relaxed text-muted-foreground">{phase.intro}</p>
          </div>
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
          {pi < PHASES.length - 1 && (
            <div className="flex items-center gap-2 py-3 pl-3 text-sm text-muted-foreground">
              <ChevronDown className="h-5 w-5 text-muted-foreground/50" />
              <span>다음 단계로 진행하십시오</span>
            </div>
          )}
        </div>
      ))}

      <div className="flex items-center gap-2 rounded-lg border border-dashed bg-muted/30 p-3 text-sm text-muted-foreground">
        <RefreshCw className="h-4 w-4 shrink-0 text-emerald-500" />
        <span>
          <span className="font-medium text-foreground">파인튜닝은 반복입니다.</span> 평가에서 부족하면 데이터(용어·라벨·
          하드네거티브)를 보강해 다시 학습하십시오. 제품을 쓸수록 피드백 루프로 학습 데이터가 쌓입니다.
        </span>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// 탭 2 — 언제 하나
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
  { step: 5, method: "검색 모델 파인튜닝 (직접 학습)", cost: null, effect: "도메인에 따라 큼 — 단, 비용·전문성이 매우 큽니다." },
]

const SIGNALS: string[] = [
  "전문 도메인 용어를 기성 모델이 이해하지 못합니다 (법률·세무·의료·바이오·반도체 등). ← 대표 사례",
  "좋은 모델과 리랭커까지 적용했는데도 골든셋 Hit Rate·MRR 이 목표에 한참 못 미칩니다 (감이 아니라 평가 숫자로 확인).",
  "질의↔정답문서 라벨 데이터를 충분히(보통 수천 건 이상) 모을 수 있습니다.",
  "같은 도메인 질의가 대량으로 반복되어, 학습 투자 대비 효과가 분명합니다.",
]

function WhenTab() {
  return (
    <TabShell>
      <section>
        <Heading icon={Gauge}>언제 파인튜닝하나요?</Heading>
        <p className="text-muted-foreground">
          파인튜닝은 비용·전문성이 큰 <span className="font-medium text-foreground">최후의 수단</span>입니다. 아래 개선
          사다리를 위에서부터 시도하고, 막힐 때만 내려가십시오.
        </p>
      </section>

      <section>
        <Sub icon={Wrench}>개선 사다리</Sub>
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
                <tr key={r.step} className="border-t align-top">
                  <td className="p-2 text-center font-semibold text-foreground">{r.step}</td>
                  <td className="p-2 text-foreground">{r.method}</td>
                  <td className="p-2">{r.cost ? <CostBadge cost={r.cost} /> : <span className="text-muted-foreground">학습 비용 큼</span>}</td>
                  <td className="p-2 text-muted-foreground">{r.effect}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-sm text-muted-foreground">대부분 1~3단계에서 해결됩니다. 5단계는 1~4를 모두 했는데도 부족할 때만 검토하십시오.</p>
      </section>

      <section>
        <Sub icon={AlertTriangle} color="text-amber-500">파인튜닝이 정당화되는 신호</Sub>
        <p className="mb-2 text-sm text-muted-foreground">아래가 여러 개 동시에 해당할 때만 검토하십시오.</p>
        <Bullets items={SIGNALS} icon={CheckCircle2} color="text-amber-500" />
      </section>

      <section>
        <Sub icon={ClipboardCheck}>전제 조건 (없으면 시작 불가)</Sub>
        <Bullets
          items={[
            "학습 데이터: (질의, 정답 청크, 오답 청크) — 가장 큰 장벽입니다.",
            "평가 체계: 파인튜닝 전·후를 비교할 홀드아웃 골든셋.",
            "GPU·MLOps: 학습 인프라와 모델 버전 관리.",
            "운영 부담: 임베딩 모델 교체 시 기존 문서 전체 재임베딩(재인덱싱)이 필요합니다.",
          ]}
        />
      </section>
    </TabShell>
  )
}

// ---------------------------------------------------------------------------
// 탭 3 — 입력 데이터
// ---------------------------------------------------------------------------

function InputTab() {
  return (
    <TabShell>
      <section>
        <Heading icon={Database}>파인튜닝 입력 데이터</Heading>
        <p className="text-muted-foreground">
          임베딩 파인튜닝은 <span className="font-medium text-foreground">대조 학습(contrastive)</span>입니다 — &ldquo;같은
          의미는 가깝게, 다른 의미는 멀게&rdquo;를 배웁니다. 따라서 학습의 본체는 (질의, 정답, 오답) 묶음입니다.
        </p>
      </section>

      <section>
        <Sub icon={Scale} color="text-sky-500">핵심 학습 데이터 (3종) — 세금·법률 예시</Sub>
        <div className="overflow-hidden rounded-lg border">
          <table className="w-full text-left text-sm">
            <thead className="bg-muted/50 text-muted-foreground">
              <tr>
                <th className="w-32 p-2">입력</th>
                <th className="p-2">정의 · 예시</th>
              </tr>
            </thead>
            <tbody>
              <tr className="border-t align-top">
                <td className="p-2 font-medium text-foreground">Anchor(질의)</td>
                <td className="p-2 text-muted-foreground">사용자가 실제로 묻는 질문. 예: &ldquo;1세대 1주택 양도세 비과세 요건이 뭔가요?&rdquo;</td>
              </tr>
              <tr className="border-t align-top">
                <td className="p-2 font-medium text-foreground">Positive(정답)</td>
                <td className="p-2 text-muted-foreground">정답이 담긴 문서 조각. 예: 소득세법 제89조 + 시행령 해당 조항 청크</td>
              </tr>
              <tr className="border-t align-top">
                <td className="p-2 font-medium text-foreground">Hard Negative(오답)</td>
                <td className="p-2 text-muted-foreground">주제는 비슷하나 정답이 아닌 조각. 예: 다주택자 양도세 <span className="text-foreground">중과</span> 조항</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-sm text-muted-foreground">
          세법·법률은 &ldquo;비슷한데 다른 조항&rdquo;(비과세 vs 감면, 개정 전 vs 후)이 최대 함정이라,
          <span className="font-medium text-foreground"> hard negative 설계</span>가 성패를 가릅니다.
        </p>
        <pre className="mt-2 overflow-x-auto rounded-md border bg-muted/40 p-3 text-[11px] leading-relaxed text-muted-foreground">
{`{"query": "1세대 1주택 양도세 비과세 요건",
 "positive": "소득세법 제89조 … 보유기간 2년 이상 …",
 "negatives": ["다주택자 양도세 중과세율 …"],
 "meta": {"source_doc": "소득세법", "as_of": "2026"}}`}
        </pre>
      </section>

      <section>
        <Sub icon={BookA}>함께 준비해야 할 입력</Sub>
        <Bullets
          items={[
            <><span className="font-medium text-foreground">도메인 코퍼스</span> — 법령·예규·판례 등을 청킹한 패시지 풀. positive/negative 의 출처.</>,
            <><span className="font-medium text-foreground">용어 사전</span> — 전문용어↔정의↔동의어/약어/구어체. &ldquo;인식 못함&rdquo; 문제의 직접 해결 열쇠로, 질의 생성·하드네거티브 마이닝에 쓰입니다.</>,
            <><span className="font-medium text-foreground">전문가 검수 라벨</span> — 골든셋·피드백을 세무사·변호사가 검수. 도메인은 라벨 정확도가 생명입니다.</>,
            <><span className="font-medium text-foreground">평가셋(분리)</span> — 전·후 비교용. train/valid/test 를 문서 단위로 분리해 데이터 누수를 막으십시오.</>,
          ]}
        />
      </section>

      <Callout>
        이 데이터는 제품을 잘 쓰면 <span className="font-medium text-foreground">피드백 루프로 자연히 쌓입니다</span> —
        쓸수록 파인튜닝 준비가 되는 구조입니다.
      </Callout>
    </TabShell>
  )
}

// ---------------------------------------------------------------------------
// 탭 4 — 임베딩 vs 리랭커
// ---------------------------------------------------------------------------

function TargetTab() {
  return (
    <TabShell>
      <section>
        <Heading icon={Boxes}>무엇을 파인튜닝할 수 있나</Heading>
        <p className="text-muted-foreground">검색 단계의 두 모델을 파인튜닝할 수 있습니다. 데이터셋 포맷은 동일합니다.</p>
      </section>

      <div className="overflow-hidden rounded-lg border">
        <table className="w-full text-left text-sm">
          <thead className="bg-muted/50 text-muted-foreground">
            <tr>
              <th className="w-24 p-2">구분</th>
              <th className="p-2">임베딩 (bi-encoder)</th>
              <th className="p-2">리랭커 (cross-encoder)</th>
            </tr>
          </thead>
          <tbody>
            {[
              ["효과", "검색 정확도↑(도메인 용어 이해)", "1차 결과 재정렬 정밀화"],
              ["손실", "MultipleNegativesRankingLoss", "BCEWithLogitsLoss"],
              ["출력", "1024차원 벡터", "관련도 점수 1개"],
              ["입력 접두", "e5 query:/passage:", "사용 안 함"],
              ["재인덱싱", "교체 시 필요", "불필요(질의 시점)"],
              ["서빙 연결", "OpenAI 호환 임베딩 서버", "cross_encoder 리랭크 서버"],
            ].map(([k, a, b]) => (
              <tr key={k} className="border-t align-top">
                <td className="p-2 font-medium text-foreground">{k}</td>
                <td className="p-2 text-muted-foreground">{a}</td>
                <td className="p-2 text-muted-foreground">{b}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Callout icon={ListFilter}>
        임베딩보다 <span className="font-medium text-foreground">리랭커 파인튜닝</span>이 데이터가 적게 들고 재인덱싱도
        필요 없어, 보통 먼저 시도할 가치가 큽니다. 다만 <em>모델이 용어 자체를 모른다</em>면 임베딩 파인튜닝이 맞습니다.
      </Callout>
    </TabShell>
  )
}

// ---------------------------------------------------------------------------
// 탭 5 — 역할 분리
// ---------------------------------------------------------------------------

function ArchitectureTab() {
  return (
    <TabShell>
      <section>
        <Heading icon={GraduationCap}>역할 분리 — Argus 와 외부 트레이너</Heading>
        <p className="text-muted-foreground">
          학습 연산(GPU·MLOps)을 제품 안에 넣지 않습니다. <span className="font-medium text-foreground">Argus 는 데이터
          파운드리 + 평가 하니스</span>, 실제 학습은 교체 가능한 외부 프로그램(<span className="font-mono text-sm">extensions/retrieval-fine-tuning</span>)이
          담당합니다.
        </p>
      </section>

      <section>
        <Sub icon={Languages}>닫힌 루프</Sub>
        <pre className="overflow-x-auto rounded-md border bg-muted/40 p-3 text-[11px] leading-relaxed text-muted-foreground">
{`Argus(데이터 수집·라벨·하드네거티브)
  → 데이터셋 내보내기(train/valid)
    → 외부 트레이너 (GPU)
      → 모델 등록·호환성 검증
        → 임베딩/리랭크 서버로 서빙
          → 홀드아웃 골든셋으로 평가
            → 리더보드 base vs tuned
              → 부족분이 다음 라벨 작업 → 반복`}
        </pre>
      </section>

      <section>
        <Sub icon={CheckCircle2} color="text-emerald-500">세 가지 계약</Sub>
        <Bullets
          items={[
            <><span className="font-medium text-foreground">데이터 내보내기</span> — 불변·버전된 데이터셋 스냅샷. <span className="font-medium text-foreground">test(홀드아웃)는 Argus 가 보관</span>해 트레이너가 평가셋을 못 보게 합니다(누수·부정 방지).</>,
            <><span className="font-medium text-foreground">모델 가져오기</span> — 트레이너 산출물(모델 + metadata)을 레지스트리에 등록. 차원·포맷 <span className="font-medium text-foreground">호환성 검증</span>.</>,
            <><span className="font-medium text-foreground">트레이너 CLI</span> — 데이터셋 디렉터리를 받아 모델을 출력하는 독립 실행 규약. 파일 + 얇은 잡 상태만 주고받습니다.</>,
          ]}
        />
      </section>

      <Callout>
        <span className="font-medium text-foreground">평가 주도권은 Argus 가 쥡니다.</span> 학습은 위임하되 &ldquo;좋아졌는가&rdquo;의
        판정은 Argus 가 홀드아웃 골든셋으로 내리므로, 트레이너가 누구 것이든 객관적 비교가 됩니다.
      </Callout>
    </TabShell>
  )
}

// ---------------------------------------------------------------------------
// 탭 6 — FAQ
// ---------------------------------------------------------------------------

const FAQS: { q: string; a: React.ReactNode }[] = [
  { q: "꼭 직접 학습해야 하나요?", a: <>대부분은 아닙니다. 기성 모델 선택 + 설정 + 리랭커로 충분합니다. 평가 숫자가 천장에 막혔고 라벨이 충분한 전문 도메인일 때만 검토하십시오.</> },
  { q: "데이터는 어디서 모으나요?", a: <>피드백(👍/👎·수정답변)·검색 로그·골든셋·LLM 합성 질의에서 모읍니다. 제품을 쓸수록 자연히 쌓입니다.</> },
  { q: "임베딩과 리랭커 중 무엇부터 할까요?", a: <>리랭커를 먼저 권합니다. 데이터가 적게 들고 재인덱싱이 필요 없습니다. 용어 자체를 모르는 문제면 임베딩 파인튜닝이 맞습니다.</> },
  { q: "학습한 모델은 어떻게 적용하나요?", a: <>임베딩은 OpenAI 호환 임베딩 서버로, 리랭커는 cross_encoder 리랭크 서버로 서빙해 컬렉션에 연결합니다. 임베딩은 교체 시 재인덱싱이 필요합니다.</> },
  { q: "좋아졌는지 어떻게 아나요?", a: <>같은 홀드아웃 골든셋으로 base 모델과 fine-tuned 모델을 평가·스윕해 Hit Rate·MRR 을 나란히 비교하십시오.</> },
  { q: "세법처럼 매년 바뀌는 도메인은요?", a: <>시점(연도) 메타데이터를 학습·평가에 반영하고, 개정 시 데이터를 갱신해 재학습하십시오.</> },
]

function FaqTab() {
  return (
    <TabShell>
      <section>
        <Heading icon={HelpCircle}>자주 묻는 질문 (FAQ)</Heading>
        <p className="text-muted-foreground">파인튜닝을 처음 검토할 때 자주 막히는 지점을 모았습니다.</p>
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

export default function FineTuningOverviewPage() {
  return (
    <>
      <DashboardHeader title="파인 튜닝 개요" />
      <div className="flex flex-1 flex-col p-4">
        <UrlTabs defaultValue="flow" className="gap-4">
          <TabsList>
            <TabsTrigger value="flow">절차</TabsTrigger>
            <TabsTrigger value="when">언제 하나</TabsTrigger>
            <TabsTrigger value="input">입력 데이터</TabsTrigger>
            <TabsTrigger value="target">임베딩 vs 리랭커</TabsTrigger>
            <TabsTrigger value="architecture">역할 분리</TabsTrigger>
            <TabsTrigger value="faq">FAQ</TabsTrigger>
          </TabsList>
          <TabsContent value="flow">
            <FlowTab />
          </TabsContent>
          <TabsContent value="when">
            <WhenTab />
          </TabsContent>
          <TabsContent value="input">
            <InputTab />
          </TabsContent>
          <TabsContent value="target">
            <TargetTab />
          </TabsContent>
          <TabsContent value="architecture">
            <ArchitectureTab />
          </TabsContent>
          <TabsContent value="faq">
            <FaqTab />
          </TabsContent>
        </UrlTabs>
      </div>
    </>
  )
}
