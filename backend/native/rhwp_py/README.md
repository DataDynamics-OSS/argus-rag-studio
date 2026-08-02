# rhwp_py — 한글 HWP/HWPX 추출용 Rust 파서 바인딩

[rhwp](https://github.com/edwardkim/rhwp)(MIT, Rust)에 대한 PyO3 바인딩입니다.
HWP 5.0 바이너리와 HWPX 를 **표(셀 병합 포함)·레이아웃을 보존**해 Markdown/텍스트로
추출합니다. 인제스천의 `rhwp` 파싱 전략(`app.ingestion.parsers`)에서 사용합니다.

순수 Python 로더(`text`/`layout` 전략)는 의존성 없이 동작하는 기본 경로이고, 이 바인딩은
표·복잡 레이아웃 정확도가 더 높은 **선택적** 경로입니다. 같은 문서에 두 전략을 적용해
검색 품질을 비교할 수 있습니다.

## API

```python
import rhwp_py
md   = rhwp_py.extract_markdown(data: bytes) -> str   # 표를 Markdown 표로 보존(권장)
text = rhwp_py.extract_text(data: bytes) -> str       # 평문 텍스트
# 페이지별 (Markdown — [[RHWP_IMAGE:n]] 토큰 유지, [bin_data_id...]) 목록.
# 토큰 n(1-based)은 그 페이지 id 목록 순서와 대응 — 인제스천이 이미지 위치 마커로
# 치환해 청크↔이미지 정밀 연결에 쓴다(HWPX: binaryItemIDRef 숫자부, HWP: BinData ID).
pages = rhwp_py.extract_markdown_pages_with_images(data: bytes) -> list[tuple[str, list[int]]]
```

`data` 는 HWP/HWPX 파일의 원본 바이트입니다(포맷 자동 판별).

## 버전 정책 / 업그레이드 런북

rhwp 코어는 리포 세 곳에서 소비된다 — **반드시 같은 릴리스로 유지**한다
(`scripts/check-rhwp-version.sh` 가 검사, 불일치 시 exit 1):

| 소비처 | 형태 | 고정 방식 |
|---|---|---|
| `backend/native/rhwp_py` | Rust 크레이트(PyO3 네이티브) | Cargo.toml `rev = <릴리스 태그의 커밋>` + `# rev <hash> = vX.Y.Z` 주석 |
| `frontend/apps/web` | npm `@rhwp/core`(브라우저 WASM) | package.json **정확 버전**(캐럿 금지) |
| `extensions/hwp_render_server` | npm `@rhwp/core`(Node WASM) | package.json 정확 버전 + Dockerfile `npm ci`(락 고정) |

**바인딩(rhwp_py) 자체 버전은 RAG Studio 버전(`backend/app/__init__.py __version__`)과
함께 올린다** — Cargo.toml·pyproject.toml 두 곳. 런타임 확인: `rhwp_py.__version__`(바인딩)
/ `rhwp_py.__rhwp_version__`·`__rhwp_rev__`(코어), 렌더 서버는 `/stats` 의 `rhwp` 필드.

rhwp 코어 업그레이드 절차(한 커밋으로):
1. `git ls-remote --tags https://github.com/edwardkim/rhwp` 로 릴리스 태그의 커밋 확인
2. Cargo.toml `rev` + 주석 갱신, `src/lib.rs` 의 `__rhwp_version__`/`__rhwp_rev__` 갱신
3. 두 package.json 버전 갱신 → `pnpm install`(frontend) / `npm install`(render server) 로 락 갱신
4. `maturin build --release` → wheel 을 backend venv 에 설치, `pytest tests/` 통과 확인
   (파싱 산출이 바뀔 수 있음 — 기존 문서는 재인덱싱 시점에 반영)
5. 렌더 서버 이미지 재빌드·재배포, frontend 는 `copy-wasm` 이 새 WASM 반영
6. `scripts/check-rhwp-version.sh` 로 정합 확인

## 빌드 / 설치

Rust 툴체인(`cargo`/`rustc`)과 [maturin](https://www.maturin.rs/) 이 필요합니다. rhwp 본체는
crates.io 에 없어 git rev 로 고정되어 있어, 최초 빌드 시 소스를 받아 컴파일합니다(수 분 소요).

### 1) Rust(cargo/rustc) 설치 — 이미 있으면 건너뜀

`cargo --version` 이 동작하면 이미 설치된 것이니 2)로 갑니다. 없으면 rustup 으로 설치:

```bash
# Linux / macOS — rustup 설치(stable 툴체인 포함). -y: 기본값으로 비대화식 설치
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y

# 설치 직후, 현재 셸 세션에 cargo/rustc 를 PATH 에 적용
source "$HOME/.cargo/env"        # 또는 새 터미널을 열면 자동 적용

# 확인
cargo --version && rustc --version
```

rustup 설치 스크립트는 `~/.cargo/bin` 을 PATH 에 추가하는 줄을 셸 프로파일
(`~/.bashrc`·`~/.zshrc`·`~/.profile` 등)에 자동으로 넣습니다. 새 셸에서는 자동 적용되고,
**현재 셸에는 위 `source "$HOME/.cargo/env"`** 로 즉시 반영합니다. (수동으로 하려면
`export PATH="$HOME/.cargo/bin:$PATH"` 를 프로파일에 추가.)

> Windows 는 https://rustup.rs 의 `rustup-init.exe`, 또는 `winget install Rustlang.Rustup`.
> Docker/CI 이미지라면 베이스에 `rust:1` 또는 rustup 설치 단계를 포함하세요.

### 2) maturin 설치 후 빌드 / 설치

```bash
pip install maturin

cd backend/native/rhwp_py
maturin build --release           # target/wheels/ 에 wheel 생성
pip install target/wheels/rhwp_py-*.whl

# 개발 중에는 develop 으로 현재 venv 에 바로 설치:
# maturin develop --release
```

설치되면 `rhwp` 전략의 가용성이 `GET /api/v1/embedding/parse-strategies` 에서 `available:true`
로 표시되고, 컬렉션 생성/재인덱싱 시 선택할 수 있습니다. 미설치 시 다른 선택적 전략(docai/vlm)
과 동일하게 `(미설치)` 로 표시되며 선택 시 명확한 오류를 던집니다.

## 참고

- rhwp 는 렌더링 엔진이라 수식 등 일부 객체는 텍스트로 추출되지 않을 수 있습니다.
- 고정 rev 는 `Cargo.toml` 의 `rhwp_core` 의존성 및 `src/lib.rs` 의 `__rhwp_rev__` 에 기록됩니다.
- 라이선스: 이 바인딩은 MIT, rhwp 본체도 MIT 입니다.
