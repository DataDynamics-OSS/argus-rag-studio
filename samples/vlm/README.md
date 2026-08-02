# vlm 파싱 전략 검증 샘플

`parse_strategy=vlm` 을 실제 비전 LLM 으로 end-to-end 검증한 산출물입니다.

| 파일 | 설명 |
|---|---|
| `qwen_test_input.pdf` | 입력 — 제목 + 헤딩 + 4×3 표(분기 실적)가 있는 PDF |
| `qwen_test_output.md` | 출력 — `parse_document(..., "vlm")` 가 생성한 Markdown |

## 재현

- 모델: `Qwen/Qwen2-VL-7B-Instruct` (served name `qwen2-vl-7b`), vLLM(NGC `nvcr.io/nvidia/vllm`)로 서빙
- 하드웨어: NVIDIA GB10 (DGX Spark)
- 경로: vlm 파서가 PDF 페이지를 PNG 로 렌더링(PyMuPDF) → OpenAI 호환 `/chat/completions` 비전 호출 → Markdown 반환
- 설정 예: `llm.server_url=http://<host>:8000/v1`, `llm.model=qwen2-vl-7b`, `llm.api_key=changeme`(raw vLLM 은 표준 Bearer)

제목→`#`, 헤딩→`##`, 표 전 셀이 Markdown 표로 정확히 복원됨을 확인했습니다.
다른 전략(text/layout/docai)은 백엔드 인프로세스로 동작하며, 자세한 내용은
`docs` 의 xref 파싱 전략 문서를 참고하세요.
