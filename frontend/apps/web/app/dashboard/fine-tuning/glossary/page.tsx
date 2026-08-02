// 용어 사전 — 도메인 전문용어·동의어 관리. 합성 질의·하드네거티브 마이닝에 활용.
"use client"

import { useCallback, useEffect, useState, type FormEvent } from "react"
import { BookA, Pencil, Plus, Search, Trash2, X } from "lucide-react"
import { getCoreRowModel, useReactTable } from "@tanstack/react-table"
import { Button } from "@workspace/ui/components/button"
import { Input } from "@workspace/ui/components/input"
import { Label } from "@workspace/ui/components/label"
import { Textarea } from "@workspace/ui/components/textarea"
import { Badge } from "@workspace/ui/components/badge"
import { Checkbox } from "@workspace/ui/components/checkbox"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@workspace/ui/components/table"
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@workspace/ui/components/dialog"
import { toast } from "sonner"
import { ConfirmDialog } from "@/components/confirm-dialog"
import { DataTablePagination } from "@/components/data-table"
import { DashboardHeader } from "@/components/dashboard-header"
import { useAuth } from "@/features/auth"
import { createTerm, deleteTerm, listTerms, updateTerm } from "@/features/finetune/api"
import type { FtGlossaryTerm } from "@/features/finetune/data/schema"

/** 칩(배지) 입력 — 값 입력 후 Enter 로 배지 추가, 배지의 X 로 삭제.
 *  single 이면 한 개만 보유(도메인용): 값이 있으면 입력칸을 숨긴다. */
function ChipInput({
  values,
  onChange,
  placeholder,
  single = false,
  id,
}: {
  values: string[]
  onChange: (next: string[]) => void
  placeholder?: string
  single?: boolean
  id?: string
}) {
  const [draft, setDraft] = useState("")
  const commit = (raw: string) => {
    const v = raw.trim()
    if (!v || values.includes(v)) {
      setDraft("")
      return
    }
    onChange(single ? [v] : [...values, v])
    setDraft("")
  }
  const remove = (v: string) => onChange(values.filter((x) => x !== v))
  const showInput = !single || values.length === 0
  return (
    <div className="flex flex-wrap items-center gap-1.5 rounded-md border bg-transparent px-2 py-1.5 text-sm focus-within:ring-1 focus-within:ring-ring">
      {values.map((v) => (
        <Badge key={v} variant="secondary" className="gap-1 font-normal">
          {v}
          <button
            type="button"
            aria-label={`${v} 삭제`}
            onClick={() => remove(v)}
            className="ml-0.5 rounded-sm text-muted-foreground hover:text-foreground"
          >
            <X className="size-3" />
          </button>
        </Badge>
      ))}
      {showInput && (
        <input
          id={id}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault()
              commit(draft)
            } else if (e.key === "Backspace" && !draft && values.length) {
              remove(values[values.length - 1]!)
            }
          }}
          onBlur={() => commit(draft)}
          placeholder={values.length ? "" : placeholder}
          className="min-w-[100px] flex-1 bg-transparent outline-none placeholder:text-muted-foreground"
        />
      )}
    </div>
  )
}

export default function FtGlossaryPage() {
  const { user } = useAuth()
  const canManage = user?.is_admin || user?.is_superuser
  const [terms, setTerms] = useState<FtGlossaryTerm[]>([])
  const [loading, setLoading] = useState(true)
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<FtGlossaryTerm | null>(null)
  const [deleting, setDeleting] = useState<FtGlossaryTerm | null>(null)
  const [deletingLoading, setDeletingLoading] = useState(false)
  // 다중 선택 + 일괄 삭제
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [bulkOpen, setBulkOpen] = useState(false)
  const [bulkLoading, setBulkLoading] = useState(false)

  // 검색 + 클라이언트 페이징(지식베이스 grid 와 동일 방식 — manualPagination + DataTablePagination)
  const [query, setQuery] = useState("")
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(50)

  const [term, setTerm] = useState("")
  const [definition, setDefinition] = useState("")
  const [synonyms, setSynonyms] = useState<string[]>([])
  const [domain, setDomain] = useState("")
  const [submitting, setSubmitting] = useState(false)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      setTerms(await listTerms())
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "조회 실패")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  // 검색 필터(용어·정의·동의어·도메인) → 페이지 슬라이스
  const q = query.trim().toLowerCase()
  const filtered = q
    ? terms.filter((t) =>
        [t.term, t.definition ?? "", t.domain ?? "", ...t.synonyms].some((s) =>
          s.toLowerCase().includes(q)
        )
      )
    : terms
  const total = filtered.length
  const pageCount = Math.max(1, Math.ceil(total / pageSize))
  const pageItems = filtered.slice((page - 1) * pageSize, page * pageSize)

  // 삭제/필터로 페이지가 범위를 벗어나면 보정
  useEffect(() => {
    if (page > pageCount) setPage(pageCount)
  }, [page, pageCount])

  const table = useReactTable({
    data: pageItems,
    columns: [],
    pageCount,
    state: { pagination: { pageIndex: page - 1, pageSize } },
    manualPagination: true,
    getCoreRowModel: getCoreRowModel(),
    onPaginationChange: (updater) => {
      const next =
        typeof updater === "function" ? updater({ pageIndex: page - 1, pageSize }) : updater
      if (next.pageSize !== pageSize) {
        setPageSize(next.pageSize)
        setPage(1)
      } else {
        setPage(next.pageIndex + 1)
      }
    },
  })

  function openCreate() {
    setEditing(null)
    setTerm("")
    setDefinition("")
    setSynonyms([])
    setDomain("")
    setOpen(true)
  }

  function openEdit(t: FtGlossaryTerm) {
    setEditing(t)
    setTerm(t.term)
    setDefinition(t.definition ?? "")
    setSynonyms(t.synonyms)
    setDomain(t.domain ?? "")
    setOpen(true)
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    if (!term.trim()) {
      toast.error("용어를 입력하세요.")
      return
    }
    const syn = synonyms.map((s) => s.trim()).filter(Boolean)
    setSubmitting(true)
    try {
      if (editing) {
        await updateTerm(editing.id, { term: term.trim(), definition: definition || null, synonyms: syn, domain: domain || null })
        toast.success("용어를 수정했습니다.")
      } else {
        await createTerm({ term: term.trim(), definition: definition || null, synonyms: syn, domain: domain || null })
        toast.success("용어를 추가했습니다.")
      }
      setOpen(false)
      await refresh()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "저장 실패")
    } finally {
      setSubmitting(false)
    }
  }

  async function confirmDelete() {
    if (!deleting) return
    setDeletingLoading(true)
    try {
      await deleteTerm(deleting.id)
      setTerms((prev) => prev.filter((t) => t.id !== deleting.id))
      toast.success("용어를 삭제했습니다.")
      setDeleting(null)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "삭제 실패")
    } finally {
      setDeletingLoading(false)
    }
  }

  function toggleSelect(id: number) {
    setSelected((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  async function confirmBulkDelete() {
    const ids = [...selected]
    if (ids.length === 0) return
    setBulkLoading(true)
    try {
      const results = await Promise.allSettled(ids.map((id) => deleteTerm(id)))
      const ok = results.filter((r) => r.status === "fulfilled").length
      const fail = ids.length - ok
      setSelected(new Set())
      setBulkOpen(false)
      if (fail) toast.error(`${ok}개 삭제, ${fail}개 실패`)
      else toast.success(`${ok}개 용어를 삭제했습니다.`)
      await refresh()
    } finally {
      setBulkLoading(false)
    }
  }

  return (
    <>
      <DashboardHeader title="용어 사전" />
      <div className="flex flex-1 flex-col gap-4 p-4">
        <p className="max-w-3xl text-sm text-muted-foreground">
          도메인 전문용어와 동의어·약어를 등록합니다. 합성 질의 생성과 하드네거티브 마이닝에 활용되어,
          모델이 &lsquo;용어 자체를 모르는&rsquo; 문제를 개선하는 데 쓰입니다.
        </p>

        <div className="flex items-center justify-between gap-2">
          <div className="relative max-w-xs flex-1">
            <Search className="absolute left-2 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={query}
              onChange={(e) => {
                setQuery(e.target.value)
                setPage(1)
              }}
              placeholder="용어·동의어·도메인 검색…"
              className="pl-8"
            />
          </div>
          {canManage && (
            <div className="flex items-center gap-2">
              <Button onClick={openCreate} size="sm">
                <Plus className="size-4" /> 용어 추가
              </Button>
              <Button
                variant="destructive"
                size="sm"
                disabled={selected.size === 0}
                onClick={() => setBulkOpen(true)}
              >
                <Trash2 className="size-4" /> 용어 삭제{selected.size > 0 ? ` (${selected.size})` : ""}
              </Button>
            </div>
          )}
        </div>

        <div className="rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                {canManage && (
                  <TableHead className="w-10">
                    <Checkbox
                      aria-label="현재 페이지 전체 선택"
                      checked={
                        pageItems.length > 0 && pageItems.every((t) => selected.has(t.id))
                          ? true
                          : pageItems.some((t) => selected.has(t.id))
                            ? "indeterminate"
                            : false
                      }
                      onCheckedChange={(v) => {
                        const on = v === true
                        setSelected((prev) => {
                          const next = new Set(prev)
                          for (const t of pageItems) on ? next.add(t.id) : next.delete(t.id)
                          return next
                        })
                      }}
                    />
                  </TableHead>
                )}
                <TableHead className="w-40">용어</TableHead>
                <TableHead>정의</TableHead>
                <TableHead>동의어</TableHead>
                <TableHead className="w-24">도메인</TableHead>
                {canManage && <TableHead className="w-20" />}
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                <TableRow>
                  <TableCell colSpan={canManage ? 6 : 4} className="text-center text-sm text-muted-foreground">
                    불러오는 중…
                  </TableCell>
                </TableRow>
              ) : total === 0 ? (
                <TableRow>
                  <TableCell colSpan={canManage ? 6 : 4} className="text-center text-sm text-muted-foreground">
                    {q ? "검색 결과가 없습니다." : "등록된 용어가 없습니다."}
                  </TableCell>
                </TableRow>
              ) : (
                pageItems.map((t) => (
                  <TableRow key={t.id} data-state={selected.has(t.id) ? "selected" : undefined}>
                    {canManage && (
                      <TableCell>
                        <Checkbox
                          aria-label={`${t.term} 선택`}
                          checked={selected.has(t.id)}
                          onCheckedChange={() => toggleSelect(t.id)}
                        />
                      </TableCell>
                    )}
                    <TableCell className="font-medium text-foreground">
                      <span className="flex items-center gap-2">
                        <BookA className="size-4 text-muted-foreground" />
                        {t.term}
                      </span>
                    </TableCell>
                    <TableCell className="max-w-[280px] truncate text-sm text-black" title={t.definition ?? ""}>
                      {t.definition ?? "—"}
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      <span className="flex flex-wrap gap-1">
                        {t.synonyms.length === 0
                          ? "—"
                          : t.synonyms.map((s) => (
                              <Badge key={s} variant="secondary" className="font-normal">
                                {s}
                              </Badge>
                            ))}
                      </span>
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {t.domain ? (
                        <Badge variant="outline" className="font-normal">{t.domain}</Badge>
                      ) : (
                        "—"
                      )}
                    </TableCell>
                    {canManage && (
                      <TableCell>
                        <span className="flex items-center gap-1">
                          <Button variant="ghost" size="icon" className="size-7" onClick={() => openEdit(t)}>
                            <Pencil className="size-3.5 text-muted-foreground" />
                          </Button>
                          <Button variant="ghost" size="icon" className="size-7" onClick={() => setDeleting(t)}>
                            <Trash2 className="size-3.5 text-muted-foreground" />
                          </Button>
                        </span>
                      </TableCell>
                    )}
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>

        {total > 0 && <DataTablePagination table={table} />}
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <form onSubmit={onSubmit}>
            <DialogHeader>
              <DialogTitle>{editing ? "용어 수정" : "용어 추가"}</DialogTitle>
            </DialogHeader>
            <div className="flex flex-col gap-4 py-4">
              <div className="flex flex-col gap-2">
                <Label htmlFor="g-term">용어</Label>
                <Input id="g-term" value={term} onChange={(e) => setTerm(e.target.value)} placeholder="예: 가산세" />
              </div>
              <div className="flex flex-col gap-2">
                <Label htmlFor="g-def">정의</Label>
                <Textarea id="g-def" value={definition} onChange={(e) => setDefinition(e.target.value)} rows={2} placeholder="용어의 뜻" />
              </div>
              <div className="flex flex-col gap-2">
                <Label htmlFor="g-syn">동의어·약어 <span className="text-xs font-normal text-muted-foreground">(입력 후 Enter)</span></Label>
                <ChipInput
                  id="g-syn"
                  values={synonyms}
                  onChange={setSynonyms}
                  placeholder="동의어·약어 입력 후 Enter (예: RFP)"
                />
              </div>
              <div className="flex flex-col gap-2">
                <Label htmlFor="g-domain">도메인 <span className="text-xs font-normal text-muted-foreground">(입력 후 Enter)</span></Label>
                <ChipInput
                  id="g-domain"
                  single
                  values={domain ? [domain] : []}
                  onChange={(vs) => setDomain(vs[0] ?? "")}
                  placeholder="예: 공공조달RFP"
                />
              </div>
            </div>
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={() => setOpen(false)}>
                취소
              </Button>
              <Button type="submit" disabled={submitting}>
                {submitting ? "저장 중…" : "저장"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={!!deleting}
        onOpenChange={(o) => {
          if (!o) setDeleting(null)
        }}
        title="용어 삭제"
        desc={
          <>
            <span className="font-medium text-foreground">{deleting?.term}</span> 용어를 삭제하시겠습니까?
            이 작업은 되돌릴 수 없습니다.
          </>
        }
        destructive
        confirmText="삭제"
        isLoading={deletingLoading}
        handleConfirm={confirmDelete}
      />

      <ConfirmDialog
        open={bulkOpen}
        onOpenChange={(o) => {
          if (!o) setBulkOpen(false)
        }}
        title="선택한 용어 삭제"
        desc={
          <>
            선택한 <span className="font-medium text-foreground">{selected.size}개</span> 용어를 삭제하시겠습니까?
            이 작업은 되돌릴 수 없습니다.
          </>
        }
        destructive
        confirmText="삭제"
        isLoading={bulkLoading}
        handleConfirm={confirmBulkDelete}
      />
    </>
  )
}
