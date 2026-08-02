# Argus RAG Studio — 사용자 매뉴얼

[Antora](https://antora.org) 기반 문서 사이트(HTML) + [Asciidoctor PDF](https://docs.asciidoctor.org/pdf-converter/latest/) 기반 PDF.

## 빌드

```bash
cd docs
make install     # npm 의존성 + asciidoctor-pdf gem + 한글 폰트(1회)
make build       # HTML 사이트 → build/site/
make pdf         # PDF        → build/pdf/argus-rag-studio.pdf
make preview     # 로컬 서버 + 브라우저 (포트 8888)
```

`[mermaid]` 다이어그램은 **asciidoctor-kroki**(공개 `https://kroki.io`)로 빌드 시 SVG 로 렌더링·임베드됩니다
(HTML·PDF 공통, `kroki-fetch-diagram` 으로 조회 시점 의존 없음). 외부 전송이 곤란하면 playbook/Makefile 의
`kroki-server-url` 을 사내 Kroki 로 바꾸세요.

## 구조

```
antora.yml              컴포넌트 정의(argus-rag-studio)
antora-playbook.yml     사이트 빌드 플레이북
modules/ROOT/
  nav.adoc              좌측 네비게이션
  pages/                매뉴얼 본문(.adoc)
  assets/images/        스크린샷·다이어그램
pdf/                    PDF 빌드(book.adoc, theme, 폰트)
ui-supplemental/        Antora 기본 UI 위 오버라이드(글꼴·CSS·partials)
```

> `build/`, `node_modules/`, `pdf/fonts/`, `.antora-cache/` 는 빌드 시 생성되며 커밋하지 않는다(.gitignore).
