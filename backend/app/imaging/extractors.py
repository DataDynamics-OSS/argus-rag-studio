# SPDX-License-Identifier: Apache-2.0
"""문서에서 임베디드 이미지를 추출하는 포맷별 디스패처.

지원 입력과 전략:
    - PDF                : PyMuPDF 로 페이지별 임베디드 이미지(페이지·위치 정보 포함)
    - 단일 이미지 파일   : 파일 자체가 1장
    - docx/xlsx/pptx     : zip 내부 미디어 폴더(word|xl|ppt/media/*)
    - hwpx               : zip 내부 BinData/*
    - hwp(바이너리)       : OLE 복합문서의 BinData/* 스트림(임베디드 이미지만, 압축 해제)
    - html/htm           : 본문의 data: URI 임베디드 이미지(외부 URL 은 air-gap 미지원)
    - 구형 doc/xls/ppt    : LibreOffice 로 PDF 변환 후 PDF 경로(페이지 확보)

모든 경로는 ``ExtractedImage`` 리스트로 정규화한다. ``index`` 는 추출 순서(0,1,2…),
``page`` 는 PDF 기반일 때만 채워지고(그 외 None), ``locator`` 는 사람이 읽는 출처
표기(예: "page 3", "word/media/image2.png")다. 최소 크기 필터(min_pixels)는 모든
경로에 동일 적용한다(아이콘/장식 제외).
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import os
import re
import zipfile
import zlib
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif", ".gif")
# zip 기반 문서의 미디어 폴더(소문자 prefix). 매칭이 없으면 이미지 확장자 멤버 전체로 폴백.
_ZIP_MEDIA_PREFIXES = {
    ".docx": ("word/media/",),
    ".xlsx": ("xl/media/",),
    ".pptx": ("ppt/media/",),
    ".hwpx": ("bindata/",),
}
# LibreOffice 로 PDF 변환 후 추출하는 포맷(네이티브 추출이 까다로운 것들). 바이너리 hwp 는
# OLE 면 BinData 네이티브 경로를 쓰고, 비 OLE(구형 3.0 등)일 때만 이 변환 폴백을 탄다.
_OFFICE_TO_PDF_EXTS = (".hwp", ".doc", ".ppt", ".xls")

_DATA_URI_RE = re.compile(
    r"""src\s*=\s*["']data:image/[^;>"']+;base64,([A-Za-z0-9+/=\s]+)["']""",
    re.IGNORECASE,
)


@dataclass
class ExtractedImage:
    """추출된 이미지 1장. ``png`` 는 with_png=True 일 때만 채워진다(분류·썸네일용)."""

    index: int
    page: int | None
    locator: str
    width: int
    height: int
    y_frac: float | None = None
    png: bytes | None = None
    # page 의 단위 — PDF/변환 경로는 None(페이지 기본), PPTX 슬라이드 매핑은 "slide".
    # 표기(p.N vs 슬라이드 N)와 주입 블록 라벨이 이 값으로 갈린다.
    unit: str | None = None
    # zip 기반 문서의 원본 멤버 경로(예 "ppt/media/image2.png") — 외부 파서(rhwp)의
    # 이미지 참조를 우리 index 로 역매핑할 때 쓴다. 비 zip 경로는 None.
    member: str | None = None


def _ext(filename: str) -> str:
    return os.path.splitext(filename or "")[1].lower()


def source_kind(filename: str) -> str:
    """업로드 포맷을 사람이 읽는 분류 라벨로(화면 표기용)."""
    ext = _ext(filename)
    if ext == ".pdf":
        return "PDF"
    if ext in _IMAGE_EXTS:
        return "이미지"
    if ext in (".doc", ".docx"):
        return "Word"
    if ext in (".xls", ".xlsx"):
        return "Excel"
    if ext in (".ppt", ".pptx"):
        return "PowerPoint"
    if ext in (".hwp", ".hwpx"):
        return "HWP"
    if ext in (".html", ".htm"):
        return "HTML"
    return ext.lstrip(".").upper() or "문서"


def is_supported(filename: str) -> bool:
    ext = _ext(filename)
    return (
        ext == ".pdf"
        or ext in _IMAGE_EXTS
        or ext in _ZIP_MEDIA_PREFIXES
        or ext in (".html", ".htm")
        or ext in _OFFICE_TO_PDF_EXTS
    )


# ── 공통 PNG 정규화/필터 ─────────────────────────────────────────────────────
def _norm_png(raw: bytes, with_png: bool) -> tuple[bytes | None, int, int] | None:
    """원본 이미지 바이트 → (png|None, w, h). 디코드 실패·min_pixels 미만은 None.

    필터(min_pixels)는 헤더 크기로 결정하므로 with_png 여부와 무관하게 동일하다."""
    from app.core.config import settings
    from PIL import Image

    try:
        img = Image.open(io.BytesIO(raw))
        w, h = img.size
    except Exception:  # noqa: BLE001 — 손상/벡터(emf/wmf) 등은 건너뜀
        return None
    if max(w, h) < settings.image_classification_min_pixels:
        return None
    png = None
    if with_png:
        try:
            buf = io.BytesIO()
            img.convert("RGB").save(buf, format="PNG")
            png = buf.getvalue()
        except Exception:  # noqa: BLE001 — 디코드는 됐으나 변환 실패: png 없이 포함(index 보존)
            png = None
    return png, w, h


# ── PDF (페이지·위치 포함) ───────────────────────────────────────────────────
def _extract_pdf(data: bytes, with_png: bool) -> list[ExtractedImage]:
    # 인제스천 분류와 동일한 열거(페이지·y_frac·min_pixels 필터) 재사용 → index 의미 일관.
    from app.ingestion.image_classifier import enumerate_pdf_images

    out: list[ExtractedImage] = []
    for it in enumerate_pdf_images(data, with_png=with_png):
        out.append(ExtractedImage(
            index=it["index"], page=it["page"], locator=f"page {it['page']}",
            width=it["width"], height=it["height"], y_frac=it.get("y_frac"),
            png=it.get("png"),
        ))
    return out


# ── 단일 이미지 파일 ─────────────────────────────────────────────────────────
def _extract_image_file(filename: str, data: bytes, with_png: bool) -> list[ExtractedImage]:
    norm = _norm_png(data, with_png)
    if not norm:
        return []
    png, w, h = norm
    return [ExtractedImage(index=0, page=1, locator=os.path.basename(filename) or "image",
                           width=w, height=h, y_frac=0.0, png=png)]


# ── zip 미디어(docx/xlsx/pptx/hwpx) ──────────────────────────────────────────
def _pptx_slide_media_map(zf: zipfile.ZipFile) -> dict[str, int]:
    """PPTX 미디어 멤버명(소문자) → 첫 등장 슬라이드 번호(1..N).

    슬라이드 순서는 ``ppt/presentation.xml`` 의 sldIdLst(r:id 순서)가 정본이다 —
    slideN.xml 의 N 은 재정렬 후 순서와 어긋날 수 있다. 각 슬라이드의 rels 에서
    media/* 타깃을 모아 매핑한다. 어떤 이유로든 파싱 실패 시 빈 dict(매핑 없이 진행).
    """
    import posixpath
    import xml.etree.ElementTree as ET

    r_ns = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    try:
        pres = ET.fromstring(zf.read("ppt/presentation.xml"))
        rids = [el.get(r_ns + "id") for el in pres.iter() if el.tag.endswith("}sldId")]
        rels = ET.fromstring(zf.read("ppt/_rels/presentation.xml.rels"))
        slide_target = {
            rel.get("Id"): rel.get("Target")
            for rel in rels
            if (rel.get("Type") or "").endswith("/slide")
        }
        out: dict[str, int] = {}
        for slide_no, rid in enumerate(rids, start=1):
            target = slide_target.get(rid)
            if not target:
                continue
            slide_path = posixpath.normpath(posixpath.join("ppt", target))
            rels_path = posixpath.join(
                posixpath.dirname(slide_path), "_rels", posixpath.basename(slide_path) + ".rels"
            )
            try:
                srels = ET.fromstring(zf.read(rels_path))
            except KeyError:  # 관계 파일 없는 슬라이드(이미지 없음)
                continue
            for rel in srels:
                t = rel.get("Target") or ""
                if "media/" not in t.lower():
                    continue
                media = posixpath.normpath(
                    posixpath.join(posixpath.dirname(slide_path), t)
                ).lower()
                out.setdefault(media, slide_no)  # 여러 슬라이드에 반복되면 첫 슬라이드
        return out
    except Exception:  # noqa: BLE001 — 매핑은 부가정보, 추출 자체를 막지 않는다
        logger.warning("pptx 슬라이드-미디어 매핑 실패 — 슬라이드 번호 없이 진행", exc_info=True)
        return {}


def _docx_para_media_map(zf: zipfile.ZipFile) -> dict[str, int]:
    """DOCX 미디어 멤버명(소문자) → 첫 등장 문단 번호(1..N).

    문단 축은 본문(w:body)의 **최상위 w:p 순서** — python-docx ``Document.paragraphs``
    와 동일해 파서의 마커 삽입 지점과 1:1 이다. 문단 내 이미지는 DrawingML(a:blip
    r:embed)과 구형 VML(v:imagedata r:id) 둘 다 커버한다. 표 안 이미지는 이 축에
    없으므로 제외(→ 캡션은 부록 폴백). 파싱 실패 시 빈 dict.
    """
    import posixpath
    import xml.etree.ElementTree as ET

    w_ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    r_ns = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    a_ns = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
    v_ns = "{urn:schemas-microsoft-com:vml}"
    try:
        rels = ET.fromstring(zf.read("word/_rels/document.xml.rels"))
        target_of = {rel.get("Id"): rel.get("Target") for rel in rels}
        body = ET.fromstring(zf.read("word/document.xml")).find(w_ns + "body")
        if body is None:
            return {}
        out: dict[str, int] = {}
        pno = 0
        for child in body:
            if child.tag != w_ns + "p":
                continue
            pno += 1
            rids = [el.get(r_ns + "embed") for el in child.iter(a_ns + "blip")]
            rids += [el.get(r_ns + "id") for el in child.iter(v_ns + "imagedata")]
            for rid in rids:
                t = target_of.get(rid or "")
                if not t or "media/" not in t.lower():
                    continue
                media = posixpath.normpath(posixpath.join("word", t)).lower()
                out.setdefault(media, pno)
        return out
    except Exception:  # noqa: BLE001 — 매핑은 부가정보, 추출 자체를 막지 않는다
        logger.warning("docx 문단-미디어 매핑 실패 — 문단 번호 없이 진행", exc_info=True)
        return {}


def _hwpx_pic_media_map(zf: zipfile.ZipFile) -> dict[str, int]:
    """HWPX 미디어 멤버명(소문자) → 그림(hp:pic)의 문서 내 등장 순번(1..N).

    순번 축은 ``Contents/section*.xml``(정렬 순)을 pre-order 로 걸으며 만나는,
    ``binaryItemIDRef`` 를 가진 ``pic`` 요소의 순서 — 본문 로더(``_hwpx_render``)의
    재귀 순회와 동일해 파서의 마커 삽입 지점과 1:1 이다. id→파일 해석은
    ``Contents/content.hpf``(OPF item id → href). 같은 미디어가 반복되면(로고 등)
    첫 등장 순번만 매핑한다. 파싱 실패 시 빈 dict.
    """
    import posixpath
    import xml.etree.ElementTree as ET

    try:
        hpf = ET.fromstring(zf.read("Contents/content.hpf"))
        href_of = {
            el.get("id"): (el.get("href") or "")
            for el in hpf.iter()
            if el.tag.endswith("}item") and el.get("id") and el.get("href")
        }
        sections = sorted(
            n for n in zf.namelist()
            if n.startswith("Contents/section") and n.lower().endswith(".xml")
        )
        out: dict[str, int] = {}
        ordinal = 0
        for sec in sections:
            root = ET.fromstring(zf.read(sec))
            for el in root.iter():
                if not el.tag.endswith("}pic"):
                    continue
                ref = next(
                    (d.get("binaryItemIDRef") for d in el.iter() if d.get("binaryItemIDRef")),
                    None,
                )
                if not ref:
                    continue
                ordinal += 1  # 필터/해석 실패와 무관하게 소비 — 로더 카운터와 정합
                href = href_of.get(ref)
                if href:
                    out.setdefault(posixpath.normpath(href).lower(), ordinal)
        return out
    except Exception:  # noqa: BLE001 — 매핑은 부가정보, 추출 자체를 막지 않는다
        logger.warning("hwpx 그림-미디어 매핑 실패 — 위치 순번 없이 진행", exc_info=True)
        return {}


def _extract_zip(filename: str, data: bytes, with_png: bool) -> list[ExtractedImage]:
    prefixes = _ZIP_MEDIA_PREFIXES.get(_ext(filename), ())
    out: list[ExtractedImage] = []
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise RuntimeError("zip 기반 문서를 열 수 없습니다(손상/암호화 가능).")
    with zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
        lower = {n: n.lower() for n in names}
        # 지정 미디어 폴더 우선, 없으면 이미지 확장자 멤버 전체로 폴백.
        # 폴백에서 패키지 메타데이터는 제외 — docProps/thumbnail.jpeg(문서 미리보기 스냅샷)는
        # 본문 임베디드 이미지가 아니라서 분류/주입 시 유령 이미지가 된다.
        _META_PREFIXES = ("docprops/", "_rels/", "customxml/")
        picked = [n for n in names if any(lower[n].startswith(p) for p in prefixes)]
        if not picked:
            picked = [
                n for n in names
                if lower[n].endswith(_IMAGE_EXTS)
                and not any(lower[n].startswith(p) for p in _META_PREFIXES)
            ]
        picked.sort(key=lambda n: lower[n])
        # 위치 앵커 매핑 — PPTX 는 슬라이드 번호(unit="slide"), DOCX 는 문단 번호
        # (unit="para"), HWPX 는 그림 등장 순번(unit="img" — in-place 라 라벨 생략).
        # 주입 블록 위치·청크 마커 연결·화면 표기에 쓰인다.
        ext = _ext(filename)
        if ext == ".pptx":
            anchor_of, unit = _pptx_slide_media_map(zf), "slide"
        elif ext == ".docx":
            anchor_of, unit = _docx_para_media_map(zf), "para"
        elif ext == ".hwpx":
            anchor_of, unit = _hwpx_pic_media_map(zf), "img"
        else:
            anchor_of, unit = {}, None
        idx = 0
        for name in picked:
            try:
                raw = zf.read(name)
            except Exception:  # noqa: BLE001
                continue
            norm = _norm_png(raw, with_png)
            if not norm:
                continue
            png, w, h = norm
            anchor = anchor_of.get(lower[name])
            out.append(ExtractedImage(
                index=idx, page=anchor,
                locator=f"{unit} {anchor} · {name}" if anchor else name,
                width=w, height=h, png=png,
                unit=unit if anchor else None,
                member=name,
            ))
            idx += 1
    return out


def hwpx_binid_media_map(data: bytes) -> dict[int, str]:
    """HWPX bin data id(숫자) → 이미지 미디어 멤버명(소문자).

    rhwp 파서의 이미지 참조(bin_data_id — ``binaryItemIDRef`` "imageN" 의 숫자부)를
    zip 멤버로 역해석한다. ``Contents/content.hpf`` 의 OPF item(id→href) 중 이미지
    확장자만 대상(ole 등 비이미지 id 와의 숫자 충돌 방지). 실패 시 빈 dict.
    """
    import posixpath
    import xml.etree.ElementTree as ET

    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        with zf:
            hpf = ET.fromstring(zf.read("Contents/content.hpf"))
        out: dict[int, str] = {}
        for el in hpf.iter():
            if not el.tag.endswith("}item"):
                continue
            item_id, href = el.get("id") or "", el.get("href") or ""
            if not item_id or _ext(href) not in _IMAGE_EXTS:
                continue
            digits = "".join(c for c in item_id if c.isdigit())
            if digits:
                out.setdefault(int(digits), posixpath.normpath(href).lower())
        return out
    except Exception:  # noqa: BLE001 — 매핑은 부가정보
        logger.warning("hwpx bin id-미디어 매핑 실패", exc_info=True)
        return {}


# ── 바이너리 HWP 5.0(OLE BinData) ────────────────────────────────────────────
def _extract_hwp_binary(data: bytes, with_png: bool) -> list[ExtractedImage]:
    """바이너리 HWP 5.0(OLE)의 ``BinData/*`` 에서 임베디드 이미지만 추출한다.

    LibreOffice PDF 변환을 거치지 않고 문서에 박혀 있는 원본 이미지를 그대로 꺼낸다
    ('문서에서 이미지만 추출' 요구사항). BinData 스트림은 FileHeader 압축 플래그에 따라
    raw deflate 로 압축돼 있으나, 플래그가 켜져 있어도 개별 스트림이 비압축으로 저장된
    경우가 있어 zlib 실패 시 원본 바이트로 폴백한다. 이미지 여부는 스트림 이름의 확장자
    (예 ``BIN0001.png``)로 가린다. min_pixels 미만/비이미지(emf 등)는 _norm_png 가 제외.
    """
    import olefile

    if not olefile.isOleFile(io.BytesIO(data)):
        raise RuntimeError("올바른 HWP 5.0 파일이 아닙니다(구형 3.0 또는 손상 가능).")
    ole = olefile.OleFileIO(io.BytesIO(data))
    try:
        header = ole.openstream("FileHeader").read()
        if header[:17] != b"HWP Document File":
            raise RuntimeError("HWP 시그니처가 없습니다.")
        flags = int.from_bytes(header[36:40], "little")
        if flags & 0x02:
            raise RuntimeError("암호화/DRM HWP 는 지원하지 않습니다(비밀번호 필요).")
        compressed = bool(flags & 0x01)

        # BinData 스토리지의 이미지 스트림만(이름 확장자로 판별), 정렬로 index 안정화.
        entries = sorted(
            (e for e in ole.listdir()
             if len(e) == 2 and e[0] == "BinData" and _ext(e[1]) in _IMAGE_EXTS),
            key=lambda e: e[1].lower(),
        )
        out: list[ExtractedImage] = []
        idx = 0
        for entry in entries:
            try:
                raw = ole.openstream(entry).read()
            except Exception:  # noqa: BLE001 — 손상 스트림은 건너뜀
                continue
            payload = raw
            if compressed:
                try:
                    payload = zlib.decompress(raw, -15)
                except zlib.error:
                    payload = raw  # 일부 BinData 는 비압축 저장 — 원본 사용
            norm = _norm_png(payload, with_png)
            if not norm:
                continue
            png, w, h = norm
            out.append(ExtractedImage(index=idx, page=None,
                                      locator=f"BinData/{entry[1]}",
                                      width=w, height=h, png=png))
            idx += 1
        return out
    finally:
        ole.close()


# ── HTML(data: URI 임베디드) ─────────────────────────────────────────────────
def _extract_html(data: bytes, with_png: bool) -> list[ExtractedImage]:
    """HTML 본문의 data: URI ``<img>`` 를 추출한다.

    ``page`` 는 data URI img 의 **문서 내 등장 순번**(1..N — 필터 탈락분 포함) —
    파서(``_html_text_with_markers``)가 같은 순번 축으로 img 위치에 마커를 넣어
    정밀 연결한다. 위치가 본문 흐름 그 자리이므로 표기 라벨은 생략(unit="img").
    """
    try:
        text = data.decode("utf-8", errors="ignore")
    except Exception:  # noqa: BLE001
        return []
    out: list[ExtractedImage] = []
    idx = 0
    for occ, m in enumerate(_DATA_URI_RE.finditer(text), start=1):
        b64 = re.sub(r"\s+", "", m.group(1))
        try:
            raw = base64.b64decode(b64)
        except Exception:  # noqa: BLE001
            continue
        norm = _norm_png(raw, with_png)
        if not norm:
            continue
        png, w, h = norm
        out.append(ExtractedImage(index=idx, page=occ, locator=f"<img> #{occ}",
                                  width=w, height=h, png=png, unit="img"))
        idx += 1
    return out


# ── 외부 URL(HTML)에서 <img> 가져오기 ────────────────────────────────────────
# 업로드 경로와 달리 네트워크 접근이 필요하다(air-gap 환경에서는 동작하지 않음).
_URL_IMG_ATTRS = ("src", "data-src", "data-original", "data-lazy-src", "data-lazy")
_URL_MAX_IMAGES = 300  # 한 페이지에서 시도할 최대 이미지 수(과대 페이지 방어).


def _decode_url_image(raw: bytes, with_png: bool, min_px: int):
    """다운로드한 이미지 바이트 → (png|None, w, h). 디코드 실패·min_px 미만은 None."""
    from PIL import Image

    try:
        img = Image.open(io.BytesIO(raw))
        w, h = img.size
    except Exception:  # noqa: BLE001
        return None
    if max(w, h) < min_px:
        return None
    png = None
    if with_png:
        try:
            buf = io.BytesIO()
            img.convert("RGB").save(buf, format="PNG")
            png = buf.getvalue()
        except Exception:  # noqa: BLE001
            png = None
    return png, w, h


async def open_url_images(
    url: str, *, with_png: bool, drop_small: bool, min_kb: int = 10
):
    """외부 URL 의 HTML 을 받아 후보를 파싱하고 ``(후보 총수, HTML 타이틀, async 제너레이터)`` 를 반환한다.

    제너레이터는 이미지를 **받는 대로 한 장씩** ``ExtractedImage`` 로 yield 하고(진행형 표시용),
    소진/중단 시 HTTP 클라이언트를 닫는다. ``drop_small=True`` 면 파일 크기가 ``min_kb`` KB
    미만인 이미지를 버린다. http/https 만 허용하며 air-gap 환경에서는 동작하지 않는다.
    """
    import httpx
    from urllib.parse import urljoin

    from bs4 import BeautifulSoup

    target = (url or "").strip()
    if not re.match(r"^https?://", target, re.I):
        raise RuntimeError("http 또는 https URL 만 지원합니다.")

    headers = {"User-Agent": "Mozilla/5.0 (compatible; ArgusRAGStudio/1.0)"}
    client = httpx.AsyncClient(follow_redirects=True, timeout=20.0, headers=headers)
    try:
        resp = await client.get(target)
        resp.raise_for_status()
        base = str(resp.url)
        soup = BeautifulSoup(resp.text, "html.parser")
        title = (soup.title.string or "").strip() if soup.title and soup.title.string else ""

        # 후보 이미지 소스 수집(순서 유지·중복 제거). data: URI 는 즉시 디코드, 그 외는 절대 URL.
        data_raws: list[bytes] = []
        http_urls: list[str] = []
        seen: set[str] = set()
        for tag in soup.find_all("img"):
            src = None
            for attr in _URL_IMG_ATTRS:
                v = tag.get(attr)
                if v and v.strip():
                    src = v.strip()
                    break
            if not src:
                continue
            if src.startswith("data:image/"):
                m = re.match(r"data:image/[^;]+;base64,(.*)", src, re.I | re.S)
                if m:
                    try:
                        data_raws.append(base64.b64decode(re.sub(r"\s+", "", m.group(1))))
                    except Exception:  # noqa: BLE001
                        pass
                continue
            absu = urljoin(base, src)
            if absu.lower().startswith(("http://", "https://")) and absu not in seen:
                seen.add(absu)
                http_urls.append(absu)
            if len(http_urls) >= _URL_MAX_IMAGES:
                break
    except BaseException:
        await client.aclose()
        raise

    total = len(data_raws) + len(http_urls)
    min_bytes = max(0, min_kb) * 1024 if drop_small else 0

    def _build(idx: int, locator: str, raw: bytes) -> ExtractedImage | None:
        if drop_small and len(raw) < min_bytes:  # 파일 크기 기준 작은 이미지 제거
            return None
        dec = _decode_url_image(raw, with_png, min_px=1)
        if not dec:
            return None
        png, w, h = dec
        return ExtractedImage(index=idx, page=None, locator=locator, width=w, height=h, png=png)

    async def _gen():
        idx = 0
        try:
            for i, raw in enumerate(data_raws):  # data: URI 는 즉시
                ei = _build(idx, f"data:image #{i + 1}", raw)
                if ei is not None:
                    yield ei
                    idx += 1

            sem = asyncio.Semaphore(8)

            async def _fetch(u: str):
                async with sem:
                    try:
                        r = await client.get(u)
                        r.raise_for_status()
                        return u, r.content
                    except Exception:  # noqa: BLE001 — 한 장 실패는 건너뜀
                        return u, None

            tasks = [asyncio.create_task(_fetch(u)) for u in http_urls]
            for fut in asyncio.as_completed(tasks):  # 받는 대로 한 장씩
                u, raw = await fut
                if not raw:
                    continue
                ei = _build(idx, u, raw)
                if ei is not None:
                    yield ei
                    idx += 1
        finally:
            await client.aclose()

    return total, title, _gen()


def _extract_sync(filename: str, data: bytes, with_png: bool) -> list[ExtractedImage]:
    """동기 추출 경로(PDF/이미지/zip/html). 오피스 폴백은 extract_images 에서 비동기 처리."""
    ext = _ext(filename)
    if ext == ".pdf":
        return _extract_pdf(data, with_png)
    if ext in _IMAGE_EXTS:
        return _extract_image_file(filename, data, with_png)
    if ext in _ZIP_MEDIA_PREFIXES:
        return _extract_zip(filename, data, with_png)
    if ext in (".html", ".htm"):
        return _extract_html(data, with_png)
    return []


async def extract_images(filename: str, data: bytes, *, with_png: bool) -> list[ExtractedImage]:
    """문서에서 이미지를 추출한다(포맷별 디스패치).

    바이너리 HWP 5.0(OLE)은 BinData 스트림에서 임베디드 이미지를 직접 꺼낸다(LibreOffice
    불필요). 구형 오피스(doc/xls/ppt)와 비 OLE HWP 만 LibreOffice 로 PDF 변환 후 PDF 경로를
    탄다(미설치면 RuntimeError). 그 외는 스레드에서 동기 추출한다.
    """
    ext = _ext(filename)
    if ext == ".hwp" and olefile_is_ole(data):
        return await asyncio.to_thread(_extract_hwp_binary, data, with_png)
    if ext in _OFFICE_TO_PDF_EXTS:
        from app.annotations import convert

        pdf = await convert.to_pdf(filename, data)  # LibreOffice 변환(미설치 시 RuntimeError)
        return await asyncio.to_thread(_extract_pdf, pdf, with_png)
    return await asyncio.to_thread(_extract_sync, filename, data, with_png)


def extract_images_sync(filename: str, data: bytes, *, with_png: bool) -> list[ExtractedImage]:
    """``extract_images`` 의 동기 버전 — 이벤트 루프가 없는 워커 스레드용(인제스천 이미지 분류).

    디스패치는 비동기 버전과 동일하다. LibreOffice 변환만 async subprocess 라 스레드 내
    임시 루프(``asyncio.run``)로 감싼다 — 러닝 루프가 있는 스레드에서 부르면 안 된다
    (인제스천 분류는 ``asyncio.to_thread`` 안에서 실행되므로 안전).
    """
    ext = _ext(filename)
    if ext == ".hwp" and olefile_is_ole(data):
        return _extract_hwp_binary(data, with_png)
    if ext in _OFFICE_TO_PDF_EXTS:
        from app.annotations import convert

        pdf = asyncio.run(convert.to_pdf(filename, data))  # LibreOffice(미설치 시 RuntimeError)
        return _extract_pdf(pdf, with_png)
    return _extract_sync(filename, data, with_png)


def olefile_is_ole(data: bytes) -> bool:
    """바이너리 HWP(OLE 복합문서) 판별. 구형 3.0/손상 파일은 False → 오피스 변환 폴백."""
    try:
        import olefile

        return bool(olefile.isOleFile(io.BytesIO(data)))
    except Exception:  # noqa: BLE001 — olefile 미설치/판별 실패 시 변환 경로로 폴백
        return False
