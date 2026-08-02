// 답변 👍/👎 피드백 위젯 — Playground/Chat 답변 하단에 배치.
// 👍 는 즉시 전송, 👎 는 코멘트/수정답변을 받는 다이얼로그를 연다.
"use client"

import { useState } from "react"
import { ThumbsDown, ThumbsUp } from "lucide-react"
import { Button } from "@workspace/ui/components/button"
import { Textarea } from "@workspace/ui/components/textarea"
import { Label } from "@workspace/ui/components/label"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@workspace/ui/components/dialog"
import { toast } from "sonner"
import { submitFeedback } from "./api"

type Props = {
  query: string
  answer: string
  collectionId?: number | null
  traceId?: string | null
}

export function FeedbackButtons({ query, answer, collectionId, traceId }: Props) {
  const [sent, setSent] = useState<"up" | "down" | null>(null)
  const [busy, setBusy] = useState(false)
  const [open, setOpen] = useState(false)
  const [comment, setComment] = useState("")
  const [corrected, setCorrected] = useState("")

  const sendUp = async () => {
    setBusy(true)
    try {
      await submitFeedback({ rating: "up", query, answer, collection_id: collectionId, trace_id: traceId })
      setSent("up")
      toast.success("피드백 감사합니다 👍")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "피드백 전송 실패")
    } finally {
      setBusy(false)
    }
  }

  const sendDown = async () => {
    setBusy(true)
    try {
      await submitFeedback({
        rating: "down",
        query,
        answer,
        collection_id: collectionId,
        trace_id: traceId,
        comment: comment.trim() || null,
        corrected_answer: corrected.trim() || null,
      })
      setSent("down")
      setOpen(false)
      setComment("")
      setCorrected("")
      toast.success("피드백이 등록되었습니다. 평가 골든셋 보강에 활용됩니다.")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "피드백 전송 실패")
    } finally {
      setBusy(false)
    }
  }

  if (sent) {
    return (
      <p className="text-xs text-muted-foreground">
        {sent === "up" ? "👍 도움이 됐다고 표시함" : "👎 개선 필요로 표시함"}
      </p>
    )
  }

  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-muted-foreground">이 답변이 도움이 되었나요?</span>
      <Button variant="outline" size="sm" className="h-7 px-2" disabled={busy} onClick={sendUp}>
        <ThumbsUp className="size-3.5" />
      </Button>
      <Button variant="outline" size="sm" className="h-7 px-2" disabled={busy} onClick={() => setOpen(true)}>
        <ThumbsDown className="size-3.5" />
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>답변 개선 피드백</DialogTitle>
            <DialogDescription>
              무엇이 부족했는지 알려주시면 평가 골든셋 보강에 활용합니다. (선택 입력)
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-1.5">
              <Label className="text-xs text-muted-foreground">코멘트</Label>
              <Textarea
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                placeholder="예: 핵심 조항을 누락함, 출처가 틀림 등"
                className="min-h-16"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label className="text-xs text-muted-foreground">기대했던 답변 (선택)</Label>
              <Textarea
                value={corrected}
                onChange={(e) => setCorrected(e.target.value)}
                placeholder="이상적인 답변을 적어주시면 골든셋 기대답변으로 사용됩니다."
                className="min-h-20"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)} disabled={busy}>
              취소
            </Button>
            <Button onClick={sendDown} disabled={busy}>
              {busy ? "전송 중..." : "피드백 보내기"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
