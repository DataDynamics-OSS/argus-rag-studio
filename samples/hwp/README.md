# HWP/HWPX 테스트 샘플

한글 HWP/HWPX 파싱(순수 Python 로더 및 `rhwp` 전략) 검증용 샘플입니다.

## 출처

[rhwp](https://github.com/edwardkim/rhwp)(MIT License) 저장소의 `samples/` 에서 가져왔습니다
(rev `bc38ff55a7e8acb65aebebe237dca0542480d381`). 두 부류로 구성됩니다.

* *합성 픽스처* — rhwp 가 포맷 동작 검증용으로 생성한 일반 콘텐츠(rhwp MIT 라이선스).
* *공공 공개 자료* — 시·도교육청 모의고사, 지자체 예산서 등 공공기관이 일반에 공개한 문서.
  실제 한글 문서에서의 표·다페이지·복잡 레이아웃 추출을 검증하기 위한 현실적 샘플입니다.

## 파일

| 파일 | 포맷 | 부류 | 검증 대상 |
|------|------|------|-----------|
| `hwpers_test4_complex_table.hwp` | HWP 5.0 | 합성 | 표/셀 병합 본문 추출 |
| `footnote-tbox-01.hwp` | HWP 5.0 | 합성 | 각주(글상자 내부/일반 문단) 추출 |
| `표-텍스트.hwpx` | HWPX | 합성 | 표 → Markdown 표 직렬화 |
| `table-complex.hwp` | HWP 5.0 | 공개 | 실제 예산서 *병합 표*(바이너리 경로) |
| `3-09월_교육_통합_2023.hwpx` | HWPX | 공개 | 모의고사 — 대용량·다페이지·혼합 콘텐츠 |

## 사용

`backend/tests/test_rhwp_samples.py` 가 이 파일들을 대상으로 두 경로를 검증합니다.

* *순수 Python 로더* (`app.ingestion.loaders`) — 의존성 가볍고 CI 에서 항상 실행.
* *rhwp 전략* (`rhwp_py`) — 네이티브 확장이 설치된 경우에만 실행(미설치 시 skip).
  빌드는 `backend/native/rhwp_py/README.md` 참조.
