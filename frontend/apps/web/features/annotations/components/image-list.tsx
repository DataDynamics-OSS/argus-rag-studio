"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { useRouter } from "next/navigation"
import { ImagePlus, Loader2, Trash2 } from "lucide-react"
import { Button } from "@workspace/ui/components/button"
import { Badge } from "@workspace/ui/components/badge"
import { Input } from "@workspace/ui/components/input"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@workspace/ui/components/table"
import { toast } from "sonner"
import type { AnnotationImage } from "../data/schema"
import { deleteImage, listImages, uploadImage } from "../api"
import { ConfirmDialog } from "@/components/confirm-dialog"

const STATUS_LABEL: Record<string, string> = {
  draft: "업로드",
  in_progress: "작업중",
  completed: "완료",
}

export function ImageList() {
  const router = useRouter()
  const [items, setItems] = useState<AnnotationImage[]>([])
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [search, setSearch] = useState("")
  const [pendingDelete, setPendingDelete] = useState<AnnotationImage | null>(null)
  const [deleting, setDeleting] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await listImages({ search: search || undefined, pageSize: 100 })
      setItems(res.items)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "목록 조회 실패")
    } finally {
      setLoading(false)
    }
  }, [search])

  useEffect(() => {
    void load()
  }, [load])

  const onUpload = async (files: FileList | null) => {
    if (!files || files.length === 0) return
    setUploading(true)
    let lastId = ""
    try {
      for (const file of Array.from(files)) {
        const r = await uploadImage(file)
        lastId = r.image_id
      }
      toast.success(`${files.length}개 이미지를 업로드했습니다.`)
      if (files.length === 1 && lastId) {
        router.push(`/dashboard/annotations/${lastId}`)
        return
      }
      await load()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "업로드 실패")
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ""
    }
  }

  const onDelete = async () => {
    const img = pendingDelete
    if (!img) return
    setDeleting(true)
    try {
      await deleteImage(img.image_id)
      setItems((prev) => prev.filter((i) => i.image_id !== img.image_id))
      toast.success("삭제되었습니다.")
      setPendingDelete(null)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "삭제 실패")
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div className="flex flex-1 flex-col gap-4 p-4">
      <div className="flex items-center gap-2">
        <Input
          placeholder="파일명 검색"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="h-9 max-w-xs"
        />
        <div className="ml-auto">
          <input
            ref={fileRef}
            type="file"
            accept="image/*"
            multiple
            hidden
            onChange={(e) => onUpload(e.target.files)}
          />
          <Button onClick={() => fileRef.current?.click()} disabled={uploading}>
            {uploading ? (
              <Loader2 className="mr-1 h-4 w-4 animate-spin" />
            ) : (
              <ImagePlus className="mr-1 h-4 w-4" />
            )}
            이미지 업로드
          </Button>
        </div>
      </div>

      <div className="rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>파일명</TableHead>
              <TableHead className="w-28">크기</TableHead>
              <TableHead className="w-20">박스</TableHead>
              <TableHead className="w-24">상태</TableHead>
              <TableHead className="w-40">생성</TableHead>
              <TableHead className="w-16" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              <TableRow>
                <TableCell colSpan={6} className="h-24 text-center">
                  <Loader2 className="mx-auto h-5 w-5 animate-spin text-muted-foreground" />
                </TableCell>
              </TableRow>
            ) : items.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6} className="h-24 text-center text-sm text-muted-foreground">
                  업로드된 이미지가 없습니다.
                </TableCell>
              </TableRow>
            ) : (
              items.map((img) => (
                <TableRow
                  key={img.image_id}
                  className="cursor-pointer"
                  onClick={() => router.push(`/dashboard/annotations/${img.image_id}`)}
                >
                  <TableCell className="font-medium">{img.filename}</TableCell>
                  <TableCell className="text-muted-foreground tabular-nums">
                    {img.width}×{img.height}
                  </TableCell>
                  <TableCell className="tabular-nums">{img.box_count}</TableCell>
                  <TableCell>
                    <Badge variant={img.status === "completed" ? "default" : "outline"}>
                      {STATUS_LABEL[img.status] ?? img.status}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {new Date(img.created_at).toLocaleString()}
                  </TableCell>
                  <TableCell>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 text-muted-foreground hover:text-destructive"
                      onClick={(e) => {
                        e.stopPropagation()
                        setPendingDelete(img)
                      }}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      <ConfirmDialog
        open={pendingDelete !== null}
        onOpenChange={(o) => {
          if (!o) setPendingDelete(null)
        }}
        title="이미지 삭제"
        desc={pendingDelete ? `'${pendingDelete.filename}' 을(를) 삭제할까요?` : ""}
        destructive
        confirmText="삭제"
        isLoading={deleting}
        handleConfirm={() => void onDelete()}
      />
    </div>
  )
}
