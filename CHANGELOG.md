# Changelog

이 프로젝트의 주요 변경 사항을 기록합니다. 형식은 [Keep a Changelog](https://keepachangelog.com/ko/1.1.0/)
를 따르며, 버전 체계는 [Semantic Versioning](https://semver.org/lang/ko/) 을 따릅니다.
버전 관리 규칙은 [VERSIONING.md](VERSIONING.md) 를 참고하세요.

## [Unreleased]

### Added
- **오픈소스 공개 준비** — Apache License 2.0 적용(`LICENSE`·`NOTICE`), 기여 가이드
  (`CONTRIBUTING.md`)·보안 정책(`SECURITY.md`), GitHub 이슈/PR 템플릿, CI 워크플로

## [0.1.2] - 2026-07-12

### Added
- **RAG 문서 라우팅** — 경로·메타데이터 규칙과 내용 임베딩 유사도로 문서를 컬렉션에
  자동 배정. 검토 큐(불확실 문서 사람 확인)와 수정 피드백 루프(재배정 내역 → 규칙 제안
  → 1클릭 정책 반영) 포함
- **소스 워치** — 드롭존을 주기적으로 스캔해 신규/변경 문서를 무인 수집
- **모델 레지스트리 + 에어갭 모델 반입** — 모델 팩을 Model Repository 로 반입하면 배포
  시 대상 서버에 자동 설치되어 오프라인 서빙
- **에이전트 기반 원격 배포** — 호스트별 Agent(:4501)가 Worker·임베딩/리랭커/검출·
  HWP 렌더·VLM 서버를 Docker/systemd 로 배포·관리. GPU 변형 자동 선택, 배포 시 RAG
  설정 자동 주입
- **HWP/HWPX 지원 강화** — `rhwp` 파싱 전략(표·레이아웃 보존), LibreOffice·
  `hwp_render` 기반 페이지 렌더링
- **이미지 파이프라인** — 이미지 OCR 라벨링(AI-Hub JSON 입출력), 이미지 탐색기,
  이미지 내용 색인

### Changed
- 사용자 매뉴얼을 여정 중심으로 재편하고 개발자 매뉴얼 모듈 신설

<!--
릴리스 시 아래 형식으로 섹션을 추가합니다.

## [X.Y.Z] - YYYY-MM-DD

### Added / Changed / Deprecated / Removed / Fixed / Security
-->
