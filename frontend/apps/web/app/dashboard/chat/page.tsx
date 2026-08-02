// Chat — 지식베이스 기반 멀티턴 챗(SSE 스트리밍 + 출처 패널).
"use client"

import { useEffect, useRef, useState } from "react"
import Link from "next/link"
import { Bot, MessageSquare, Quote, Send, SlidersHorizontal, ThumbsUp, User2 } from "lucide-react"
import { Button } from "@workspace/ui/components/button"
import { Input } from "@workspace/ui/components/input"
import { Badge } from "@workspace/ui/components/badge"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@workspace/ui/components/select"
import { Checkbox } from "@workspace/ui/components/checkbox"
import { TabsContent, TabsList, TabsTrigger } from "@workspace/ui/components/tabs"
import { toast } from "sonner"
import { DashboardHeader } from "@/components/dashboard-header"
import { Bullets, Callout, Heading, Sub, TabShell } from "@/components/doc-blocks"
import { listCollections } from "@/features/collections/api"
import type { Collection } from "@/features/collections/data/schema"
import { listPipelines } from "@/features/pipelines/api"
import type { Pipeline } from "@/features/pipelines/data/schema"
import { chatStream } from "@/features/search/api"
import type { Citation } from "@/features/search/data/schema"
import { FeedbackButtons } from "@/features/feedback/feedback-buttons"
import { UrlTabs } from "@/components/url-tabs"

type Turn = {
  role: "user" | "assistant"
  content: string
  citations?: Citation[]
  traceId?: string | null
  query?: string
  done?: boolean
  mode?: string
  metric?: string
}

export default function ChatPage() {
  return (
    <>
      <DashboardHeader title="Chat" />
      <div className="flex min-h-0 flex-1 flex-col p-4">
        <UrlTabs defaultValue="chat" className="flex min-h-0 flex-1 flex-col gap-4">
          <TabsList>
            <TabsTrigger value="chat">대화</TabsTrigger>
            <TabsTrigger value="guide">사용법</TabsTrigger>
          </TabsList>
          {/* forceMount + CSS 숨김: 사용법 탭으로 갔다 와도 대화·스트리밍 상태가 유지된다(언마운트 방지). */}
          <TabsContent value="chat" forceMount className="min-h-0 flex-1 data-[state=inactive]:hidden">
            <ChatTab />
          </TabsContent>
          <TabsContent value="guide">
            <ChatUsageTab />
          </TabsContent>
        </UrlTabs>
      </div>
    </>
  )
}

function ChatTab() {
  const [collections, setCollections] = useState<Collection[]>([])
  const [collectionId, setCollectionId] = useState("")
  const [rerank, setRerank] = useState(false)
  const [pipelines, setPipelines] = useState<Pipeline[]>([])
  const [pipelineId, setPipelineId] = useState("") // "" = 사용 안 함
  const [turns, setTurns] = useState<Turn[]>([])
  const [input, setInput] = useState("")
  const [streaming, setStreaming] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const usingPipeline = pipelineId !== ""

  useEffect(() => {
    listCollections({ page_size: 100 })
      .then((res) => {
        setCollections(res.items)
        if (res.items.length) setCollectionId(String(res.items[0]!.id))
      })
      .catch(() => {})
    listPipelines()
      .then(setPipelines)
      .catch(() => {})
  }, [])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight })
  }, [turns])

  async function send() {
    const text = input.trim()
    if (!text || !collectionId || streaming) return
    const history: Turn[] = [...turns, { role: "user", content: text }]
    setTurns([...history, { role: "assistant", content: "" }])
    setInput("")
    setStreaming(true)

    try {
      await chatStream(
        Number(collectionId),
        {
          messages: history.map((t) => ({ role: t.role, content: t.content })),
          mode: "hybrid",
          rerank,
          ...(pipelineId ? { pipeline_id: Number(pipelineId) } : {}),
        },
        (e) => {
          if (e.type === "hits") {
            setTurns((prev) => {
              const next = [...prev]
              const last = next[next.length - 1]!
              next[next.length - 1] = { ...last, mode: e.mode, metric: e.distance_metric }
              return next
            })
          } else if (e.type === "token") {
            setTurns((prev) => {
              const next = [...prev]
              const last = next[next.length - 1]!
              next[next.length - 1] = { ...last, content: last.content + e.text }
              return next
            })
          } else if (e.type === "citations") {
            setTurns((prev) => {
              const next = [...prev]
              const last = next[next.length - 1]!
              next[next.length - 1] = { ...last, citations: e.citations }
              return next
            })
          } else if (e.type === "done") {
            setTurns((prev) => {
              const next = [...prev]
              const last = next[next.length - 1]!
              next[next.length - 1] = { ...last, traceId: e.trace_id ?? null, query: text, done: true }
              return next
            })
          } else if (e.type === "error") {
            toast.error(e.detail)
          }
        }
      )
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "챗 실패")
    } finally {
      setStreaming(false)
    }
  }

  return (
      <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-lg border">
        <div className="flex items-center gap-3 border-b px-4 py-2">
          <Select value={collectionId} onValueChange={setCollectionId}>
            <SelectTrigger className="w-64">
              <SelectValue placeholder="지식베이스 선택" />
            </SelectTrigger>
            <SelectContent>
              {collections.map((c) => (
                <SelectItem key={c.id} value={String(c.id)}>
                  {c.name} ({c.document_count})
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={pipelineId || "__none__"} onValueChange={(v) => setPipelineId(v === "__none__" ? "" : v)}>
            <SelectTrigger className="w-48">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__none__">파이프라인 사용 안 함</SelectItem>
              {pipelines.map((p) => (
                <SelectItem key={p.id} value={String(p.id)}>
                  {p.name} (v{p.active_version})
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <label
            className="flex items-center gap-2 text-sm text-muted-foreground"
            title={usingPipeline ? "파이프라인 적용 중 — 리랭크는 파이프라인 설정을 따릅니다." : undefined}
          >
            <Checkbox checked={rerank} onCheckedChange={(v) => setRerank(!!v)} disabled={usingPipeline} />
            리랭크
          </label>
          {turns.length > 0 && (
            <Button variant="ghost" size="sm" className="ml-auto" onClick={() => setTurns([])}>
              대화 비우기
            </Button>
          )}
        </div>

        <div ref={scrollRef} className="flex-1 overflow-y-auto p-4">
          {turns.length === 0 ? (
            <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
              지식베이스에 대해 질문해 보세요.
            </div>
          ) : (
            <div className="mx-auto flex max-w-3xl flex-col gap-4">
              {turns.map((t, i) => (
                <div key={i} className="flex gap-3">
                  <div className="mt-0.5 shrink-0">
                    {t.role === "user" ? (
                      <User2 className="size-5 text-muted-foreground" />
                    ) : (
                      <Bot className="size-5 text-primary" />
                    )}
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="whitespace-pre-wrap text-sm leading-relaxed">
                      {t.content || (streaming && i === turns.length - 1 ? "…" : "")}
                    </p>
                    {t.citations && t.citations.length > 0 && (
                      <div className="mt-2 flex flex-col gap-1 border-l-2 pl-3">
                        {t.citations.map((c) => (
                          <div key={c.marker} className="flex gap-1.5 text-xs">
                            <Badge variant="secondary" className="h-4">
                              [{c.marker}]
                            </Badge>
                            <span className="truncate text-muted-foreground">
                              {c.document_name} — {c.text.slice(0, 80)}
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                    {t.role === "assistant" && t.done && t.content && t.metric && (
                      <div className="mt-2 flex items-center gap-1.5">
                        <Badge variant="outline" className="h-5 font-normal">
                          {t.mode === "vector" ? "벡터" : t.mode === "lexical" ? "렉시컬" : "하이브리드"}
                        </Badge>
                        {t.mode !== "lexical" && (
                          <Badge variant="secondary" className="h-5 font-normal">
                            거리: {t.metric}
                          </Badge>
                        )}
                      </div>
                    )}
                    {t.role === "assistant" && t.done && t.content && (
                      <div className="mt-2">
                        <FeedbackButtons
                          query={t.query ?? ""}
                          answer={t.content}
                          collectionId={collectionId ? Number(collectionId) : null}
                          traceId={t.traceId}
                        />
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="border-t p-4">
          <div className="mx-auto flex max-w-3xl gap-2">
            <Input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault()
                  send()
                }
              }}
              placeholder="메시지를 입력하세요..."
              disabled={!collectionId}
            />
            <Button onClick={send} disabled={streaming || !collectionId || !input.trim()}>
              <Send className="size-4" />
            </Button>
          </div>
        </div>
      </div>
  )
}

// ---------------------------------------------------------------------------
// 사용법
// ---------------------------------------------------------------------------

function ChatUsageTab() {
  return (
    <TabShell>
      <section>
        <Heading icon={Bot}>Chat — 지식베이스와 멀티턴 대화</Heading>
        <p className="text-muted-foreground">
          Chat은 선택한 지식베이스를 근거로 <span className="font-medium text-foreground">이어지는 대화(멀티턴)</span>를
          나누는 곳입니다. 답변은 <span className="font-medium text-foreground">실시간 스트리밍</span>되며, 사용한 근거가
          출처로 함께 표시됩니다. 단발성 검색·튜닝은 <Link href="/dashboard/playground" className="text-primary hover:underline">Playground</Link>,
          이어지는 질의응답은 Chat을 쓰십시오.
        </p>
      </section>

      <section>
        <Sub icon={MessageSquare}>① 시작하기</Sub>
        <Bullets
          items={[
            <>상단에서 <span className="font-medium text-foreground">지식베이스</span>를 고르고 질문을 입력하면 그 KB의 내용으로 답합니다.</>,
            <>이전 질문·답변이 문맥으로 유지되어 <span className="font-medium text-foreground">후속 질문(&ldquo;그럼 그건?&rdquo;)</span>도 이어집니다. 주제를 바꾸려면 <span className="font-medium text-foreground">대화 비우기</span>로 초기화하십시오.</>,
            <>검색 방식은 <span className="font-medium text-foreground">하이브리드</span>(의미+키워드)로 동작합니다.</>,
          ]}
        />
      </section>

      <section>
        <Sub icon={Quote}>② 출처 확인</Sub>
        <Bullets
          items={[
            <>답변 아래에 <span className="font-medium text-foreground">[번호] 출처</span>로 어떤 문서·청크를 근거로 썼는지 표시됩니다. 근거 없이 지어낸 답이 아닌지 확인하십시오.</>,
            <>답변에 붙는 <span className="font-medium text-foreground">검색 방식·거리 메트릭</span> 배지로 어떻게 검색됐는지 알 수 있습니다.</>,
          ]}
        />
      </section>

      <section>
        <Sub icon={SlidersHorizontal}>③ 옵션</Sub>
        <Bullets
          items={[
            <><span className="font-medium text-foreground">리랭크</span> — 검색 결과를 한 번 더 정밀 재정렬해 근거 정확도를 높입니다(선택).</>,
            <><span className="font-medium text-foreground">대화 비우기</span> — 누적된 맥락을 지우고 새 대화를 시작합니다.</>,
          ]}
        />
      </section>

      <Callout icon={ThumbsUp}>
        답변이 좋거나 아쉬우면 <span className="font-medium text-foreground">👍/👎</span>를 남겨 주십시오. <Link href="/dashboard/feedback" className="text-primary hover:underline">피드백</Link>에
        쌓여 골든셋으로 승격되고, <Link href="/dashboard/evaluation" className="text-primary hover:underline">평가</Link>·
        <Link href="/dashboard/pipelines" className="text-primary hover:underline">파이프라인</Link> 개선의 재료가 됩니다.
      </Callout>
    </TabShell>
  )
}
