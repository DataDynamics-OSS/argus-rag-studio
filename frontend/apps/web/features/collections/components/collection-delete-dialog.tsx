/**
 * 지식베이스(컬렉션) 삭제 확인 다이얼로그.
 *
 * 실수로 인한 삭제를 막기 위해, 삭제하려면 대상 지식베이스의 이름을 정확히
 * 입력해야 한다. 입력값이 이름과 일치할 때만 삭제 버튼이 활성화된다.
 *
 * 흐름:
 * 1. 다이얼로그가 대상 지식베이스 이름을 보여준다.
 * 2. 사용자가 정확한 이름을 입력한다.
 * 3. 입력값이 일치하기 전까지 "삭제" 버튼은 비활성.
 * 4. 확인 시 deleteCollection() 호출 → 성공 콜백.
 */

"use client"

import { useEffect, useState } from "react"
import { AlertTriangle } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@workspace/ui/components/alert"
import { Input } from "@workspace/ui/components/input"
import { Label } from "@workspace/ui/components/label"
import { ConfirmDialog } from "@/components/confirm-dialog"
import { deleteCollection } from "../api"

type CollectionDeleteDialogProps = {
  /** 다이얼로그 열림 여부. */
  open: boolean
  /** 열림/닫힘 콜백. */
  onOpenChange: (open: boolean) => void
  /** 삭제 대상 지식베이스 id. */
  collectionId: number
  /** 삭제 대상 지식베이스 이름(확인 입력 대상). */
  collectionName: string
  /** 삭제 성공 후 콜백(예: 목록으로 이동). */
  onDeleted: () => void
}

export function CollectionDeleteDialog({
  open,
  onOpenChange,
  collectionId,
  collectionName,
  onDeleted,
}: CollectionDeleteDialogProps) {
  /** 사용자가 입력한 확인 텍스트(이름과 일치해야 함). */
  const [value, setValue] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  // 다이얼로그를 닫거나 다시 열 때 입력값·상태 초기화
  useEffect(() => {
    if (!open) {
      setValue("")
      setError(null)
      setLoading(false)
    }
  }, [open])

  const matches = value.trim() === collectionName

  const handleDelete = async () => {
    if (!matches) return
    setError(null)
    setLoading(true)
    try {
      await deleteCollection(collectionId)
      onDeleted()
    } catch (err) {
      setError(err instanceof Error ? err.message : "지식베이스 삭제에 실패했습니다.")
      setLoading(false)
    }
  }

  return (
    <ConfirmDialog
      open={open}
      onOpenChange={onOpenChange}
      handleConfirm={handleDelete}
      disabled={!matches}
      isLoading={loading}
      title={
        <span className="text-destructive">
          <AlertTriangle className="me-1 inline-block stroke-destructive" size={18} />{" "}
          지식베이스 삭제
        </span>
      }
      desc={
        <div className="space-y-4">
          <p className="mb-2">
            <span className="font-bold">{collectionName}</span> 지식베이스를 정말
            삭제하시겠습니까?
            <br />
            지식베이스와 <span className="font-bold">모든 문서·청크</span> 가
            영구히 제거됩니다. 이 작업은 되돌릴 수 없습니다.
          </p>

          {/* 이름 확인 입력 */}
          <Label className="my-2 flex flex-col items-start gap-1.5">
            <span>지식베이스 이름</span>
            <Input
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder="확인을 위해 지식베이스 이름을 입력하세요."
              autoComplete="off"
            />
          </Label>

          {/* 에러 메시지 */}
          {error && (
            <Alert variant="destructive">
              <AlertTitle>오류</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          {/* 비가역 작업 경고 */}
          {!error && (
            <Alert variant="destructive">
              <AlertTitle>주의!</AlertTitle>
              <AlertDescription>
                이 작업은 되돌릴 수 없으니 신중히 진행해주세요.
              </AlertDescription>
            </Alert>
          )}
        </div>
      }
      confirmText="삭제"
      destructive
    />
  )
}
