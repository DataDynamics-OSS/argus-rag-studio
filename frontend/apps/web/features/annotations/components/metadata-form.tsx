"use client"

import type { ReactNode } from "react"
import { Input } from "@workspace/ui/components/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@workspace/ui/components/select"
import type { AnnotationMeta } from "../data/schema"
import {
  ACQUISITION_LOCATION_CHOICES,
  BACKGROUND,
  DATASET_CATEGORY,
  DATASET_TYPE,
  MEDIA_TYPE,
  OBJECT_RECOGNITION,
  PEN_COLOR_CHOICES,
  PEN_TYPE,
  TEXT_LANGUAGE,
  WRITER_SEX,
  WRITTEN_CONTENT,
  type CodeOption,
} from "../lib/aihub-codes"

interface MetadataFormProps {
  meta: AnnotationMeta
  onChange: (meta: AnnotationMeta) => void
}

type Block = "Annotation" | "Dataset" | "Images"

/** AI-Hub 메타 블록(Annotation/Dataset/Images) 편집 폼 — 라벨/값 2열 테이블. */
export function MetadataForm({ meta, onChange }: MetadataFormProps) {
  const get = (block: Block, key: string): unknown => (meta[block] as Record<string, unknown> | undefined)?.[key]

  const set = (block: Block, key: string, value: unknown) => {
    onChange({
      ...meta,
      [block]: { ...(meta[block] as Record<string, unknown> | undefined), [key]: value },
    })
  }

  const codeControl = (block: Block, key: string, opts: CodeOption[]) => {
    const raw = get(block, key)
    const value = raw == null ? "" : String(raw)
    return (
      <Select value={value} onValueChange={(v) => set(block, key, Number(v))}>
        <SelectTrigger className="h-7 w-full text-sm text-black">
          <SelectValue placeholder="선택" />
        </SelectTrigger>
        <SelectContent>
          {opts.map((o) => (
            <SelectItem key={o.value} value={String(o.value)}>
              {o.label} ({o.value})
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    )
  }

  const textControl = (block: Block, key: string, placeholder?: string) => (
    <Input
      value={(get(block, key) as string) ?? ""}
      placeholder={placeholder}
      onChange={(e) => set(block, key, e.target.value)}
      className="h-7 text-sm text-black"
    />
  )

  const numberControl = (block: Block, key: string) => (
    <Input
      type="number"
      value={(get(block, key) as number | undefined) ?? 0}
      onChange={(e) => set(block, key, Number(e.target.value))}
      className="h-7 text-sm text-black"
    />
  )

  const choiceControl = (block: Block, key: string, choices: string[]) => {
    const value = (get(block, key) as string) ?? ""
    return (
      <Select value={value} onValueChange={(v) => set(block, key, v)}>
        <SelectTrigger className="h-7 w-full text-sm text-black">
          <SelectValue placeholder="선택" />
        </SelectTrigger>
        <SelectContent>
          {choices.map((c) => (
            <SelectItem key={c} value={c}>
              {c}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    )
  }

  const sectionRow = (title: string) => (
    <tr key={`__sec_${title}`}>
      <th
        colSpan={2}
        className="border border-border bg-muted/60 px-2 py-1.5 text-left text-sm font-semibold text-black"
      >
        {title}
      </th>
    </tr>
  )

  const fieldRow = (label: string, control: ReactNode) => (
    <tr key={label}>
      <td className="border border-border bg-muted/20 px-2 py-1 align-middle text-sm text-black">
        {label}
      </td>
      <td className="border border-border px-2 py-1">{control}</td>
    </tr>
  )

  return (
    <div className="space-y-3">
      <table className="w-full table-fixed border-collapse">
        <colgroup>
          <col style={{ width: 100 }} />
          <col />
        </colgroup>
        <tbody>
          {sectionRow("Dataset")}
          {fieldRow("이름(name)", textControl("Dataset", "name"))}
          {fieldRow("카테고리", codeControl("Dataset", "category", DATASET_CATEGORY))}
          {fieldRow("데이터셋 용도", codeControl("Dataset", "type", DATASET_TYPE))}

          {sectionRow("Images")}
          {fieldRow("수집 위치", choiceControl("Images", "acquistion_location", ACQUISITION_LOCATION_CHOICES))}
          {fieldRow("적용 분야", textControl("Images", "application_field"))}
          {fieldRow("작성일", textControl("Images", "data_captured", "YYYY.MM.DD"))}
          {fieldRow("펜 색상", choiceControl("Images", "pen_color", PEN_COLOR_CHOICES))}
          {fieldRow("펜 종류", codeControl("Images", "pen_type", PEN_TYPE))}
          {fieldRow("매체", codeControl("Images", "media_type", MEDIA_TYPE))}
          {fieldRow("배경", codeControl("Images", "background", BACKGROUND))}
          {fieldRow("작성자 나이", numberControl("Images", "writer_age"))}
          {fieldRow("작성자 성별", codeControl("Images", "writer_sex", WRITER_SEX))}
          {fieldRow("작성 내용", codeControl("Images", "written_content", WRITTEN_CONTENT))}

          {sectionRow("Annotation")}
          {fieldRow("객체 인식", codeControl("Annotation", "object_recognition", OBJECT_RECOGNITION))}
          {fieldRow("언어", codeControl("Annotation", "text_language", TEXT_LANGUAGE))}
        </tbody>
      </table>
    </div>
  )
}
