# SPDX-License-Identifier: Apache-2.0
"""파싱 전략(parse_strategy) 회귀 테스트.

이 세션에서 ad-hoc 으로 한 검증을 코드로 박제한 것. GPU/실모델 없이 CI 에서 돌도록:
    - text       : 항상 실행
    - layout     : pdfplumber 있을 때(표→Markdown)
    - docai      : docling 있을 때
    - vlm        : 테스트 내장 목 비전 엔드포인트(래스터화→페이로드→응답 파싱 검증), pymupdf 있을 때
    - vlm 실모델 : VLM_TEST_ENDPOINT 환경변수 설정 시에만(opt-in, DGX 등 실 엔드포인트)

픽스처 PDF(tests/fixtures/table.pdf)는 제목 + 헤딩 + 4×3 표(분기 실적, 격자선 포함).
"""

import base64
import importlib.util
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from app.ingestion.parsers import PARSE_STRATEGIES, list_parse_strategies, parse_document

TABLE_PDF = Path(__file__).parent / "fixtures" / "table.pdf"


def _has(mod: str) -> bool:
    return importlib.util.find_spec(mod) is not None


# ── text ─────────────────────────────────────────────────────────────────────
def test_text_plaintext():
    out = parse_document("a.txt", "안녕하세요 RAG 스튜디오".encode(), "text")
    assert "RAG" in out


def test_unknown_strategy_falls_back_to_text():
    out = parse_document("a.txt", b"hello world", "does-not-exist")
    assert "hello world" in out


def test_auto_resolve_parse_strategy_by_extension():
    from app.ingestion.parsers import resolve_parse_strategy

    # 평문/오피스 포맷은 항상 text
    assert resolve_parse_strategy("a.txt") == "text"
    assert resolve_parse_strategy("a.docx") == "text"
    assert resolve_parse_strategy("a.xlsx") == "text"
    # PDF/HWP 는 의존성 있으면 특화 전략, 없으면 text 폴백
    assert resolve_parse_strategy("a.pdf") in ("layout", "text")
    assert resolve_parse_strategy("a.hwp") in ("rhwp", "text")
    assert resolve_parse_strategy("a.hwpx") in ("rhwp", "text")


def test_auto_parse_document_dispatches(tmp_path=None):
    # auto 로 호출하면 확장자에 맞는 전략으로 추출(txt → text)
    out = parse_document("note.txt", "자동 파싱 테스트".encode(), "auto")
    assert "자동 파싱" in out


def test_list_parse_strategies_shape():
    items = list_parse_strategies()
    assert {i["strategy"] for i in items} == set(PARSE_STRATEGIES)
    for i in items:
        assert set(i) >= {"strategy", "label", "description", "available"}
    text = next(i for i in items if i["strategy"] == "text")
    assert text["available"] is True  # text 는 의존성 없음 → 항상 가용


# ── layout (pdfplumber) ──────────────────────────────────────────────────────
@pytest.mark.skipif(not _has("pdfplumber"), reason="pdfplumber 미설치")
def test_layout_serializes_table_to_markdown():
    out = parse_document("t.pdf", TABLE_PDF.read_bytes(), "layout")
    assert "| Quarter | Revenue | Growth |" in out
    assert "| Q1 | 100 | 5% |" in out
    assert "| Q3 | 150 | 25% |" in out


# ── docai (docling) ──────────────────────────────────────────────────────────
@pytest.mark.skipif(not _has("docling"), reason="docling 미설치")
def test_docai_extracts_table_and_heading():
    out = parse_document("t.pdf", TABLE_PDF.read_bytes(), "docai")
    assert "Quarter" in out and "Revenue" in out
    assert "100" in out and "150" in out


# ── vlm (목 비전 엔드포인트) ──────────────────────────────────────────────────
class _VisionHandler(BaseHTTPRequestHandler):
    """OpenAI 호환 비전 엔드포인트 스텁 — 받은 요청을 기록하고 Markdown 을 돌려준다."""

    received: list = []

    def log_message(self, *a):  # 테스트 로그 소음 억제
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        content = body["messages"][0]["content"]
        img = next(c for c in content if c["type"] == "image_url")["image_url"]["url"]
        png = base64.b64decode(img.split(",", 1)[1])
        type(self).received.append({
            "authorization": self.headers.get("Authorization"),
            "x_api_key": self.headers.get("X-API-Key"),
            "model": body.get("model"),
            "valid_png": png[:8] == b"\x89PNG\r\n\x1a\n",
            "has_text_prompt": any(c["type"] == "text" for c in content),
        })
        md = "## Page\n\n| Quarter | Revenue |\n| --- | --- |\n| Q1 | 100 |"
        out = json.dumps({"choices": [{"message": {"content": md}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


@pytest.fixture
def mock_vision_server():
    _VisionHandler.received = []
    srv = HTTPServer(("127.0.0.1", 0), _VisionHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}/v1", _VisionHandler
    finally:
        srv.shutdown()


def _point_llm_at(monkeypatch, url, *, model="qwen2-vl-7b", key="test-key",
                  header="Authorization", scheme="Bearer"):
    from app.core.config import settings

    monkeypatch.setattr(settings, "llm_server_url", url)
    monkeypatch.setattr(settings, "llm_model", model)
    monkeypatch.setattr(settings, "llm_api_key", key)
    monkeypatch.setattr(settings, "llm_auth_header", header)
    monkeypatch.setattr(settings, "llm_auth_scheme", scheme)
    monkeypatch.setattr(settings, "llm_timeout", 30)


@pytest.mark.skipif(not _has("fitz"), reason="pymupdf 미설치")
def test_vlm_against_mock_endpoint(monkeypatch, mock_vision_server):
    url, handler = mock_vision_server
    _point_llm_at(monkeypatch, url)
    out = parse_document("t.pdf", TABLE_PDF.read_bytes(), "vlm")

    # 응답 파싱 → Markdown 반환
    assert "| Quarter | Revenue |" in out
    # 파서가 보낸 페이로드 검증: 모델/Bearer 인증/유효 PNG/텍스트 프롬프트
    assert handler.received, "비전 엔드포인트가 호출되지 않음"
    call = handler.received[0]
    assert call["model"] == "qwen2-vl-7b"
    assert call["authorization"] == "Bearer test-key"
    assert call["valid_png"] and call["has_text_prompt"]


@pytest.mark.skipif(not _has("fitz"), reason="pymupdf 미설치")
def test_vlm_custom_auth_header(monkeypatch, mock_vision_server):
    """X-API-Key 게이트웨이 — 커스텀 인증 헤더가 그대로 전달되는지(Bearer 없음)."""
    url, handler = mock_vision_server
    _point_llm_at(monkeypatch, url, key="sk-x", header="X-API-Key", scheme="")
    parse_document("t.pdf", TABLE_PDF.read_bytes(), "vlm")

    call = handler.received[0]
    assert call["x_api_key"] == "sk-x"
    assert call["authorization"] is None  # Bearer 헤더는 없어야 함


# ── vlm 실모델(opt-in) ───────────────────────────────────────────────────────
@pytest.mark.skipif(
    not os.environ.get("VLM_TEST_ENDPOINT"),
    reason="VLM_TEST_ENDPOINT 미설정 — 실모델 vlm 테스트는 opt-in",
)
def test_vlm_real_endpoint(monkeypatch):
    """실제 비전 LLM 으로 검증. 예:
    VLM_TEST_ENDPOINT=http://192.0.2.48:8000/v1 VLM_TEST_MODEL=qwen2-vl-7b \
        VLM_TEST_KEY=changeme pytest -k real_endpoint
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "llm_server_url", os.environ["VLM_TEST_ENDPOINT"])
    monkeypatch.setattr(settings, "llm_model", os.environ.get("VLM_TEST_MODEL", "qwen2-vl-7b"))
    monkeypatch.setattr(settings, "llm_api_key", os.environ.get("VLM_TEST_KEY", "changeme"))
    monkeypatch.setattr(settings, "llm_auth_header", os.environ.get("VLM_TEST_AUTH_HEADER", "Authorization"))
    monkeypatch.setattr(settings, "llm_auth_scheme", os.environ.get("VLM_TEST_AUTH_SCHEME", "Bearer"))
    monkeypatch.setattr(settings, "llm_timeout", 180)

    out = parse_document("t.pdf", TABLE_PDF.read_bytes(), "vlm")
    assert "Quarter" in out and "100" in out


# ── rhwp (한글 HWP/HWPX — Rust 바인딩) ────────────────────────────────────────
def test_rhwp_falls_back_to_text_for_non_hwp():
    """HWP/HWPX 가 아니면 rhwp_py 없이도 text 로 폴백한다."""
    out = parse_document("a.txt", "한글 테스트 RAG".encode(), "rhwp")
    assert "RAG" in out


@pytest.mark.skipif(not _has("rhwp_py"), reason="rhwp_py 미빌드(backend/native/rhwp_py)")
@pytest.mark.skipif(
    not os.environ.get("RHWP_TEST_HWP"),
    reason="RHWP_TEST_HWP 미설정 — 실파일 추출은 opt-in",
)
def test_rhwp_extracts_real_file():
    """실제 HWP/HWPX 를 rhwp 로 추출(표 Markdown). 예:
    RHWP_TEST_HWP=/path/table.hwp pytest -k rhwp_extracts_real
    """
    path = Path(os.environ["RHWP_TEST_HWP"])
    out = parse_document(path.name, path.read_bytes(), "rhwp")
    assert out.strip(), "rhwp 추출 결과가 비어 있음"
