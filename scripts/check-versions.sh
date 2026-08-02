#!/usr/bin/env bash
# 제품 버전 정합 검사 — 모든 컴포넌트가 RAG Studio 버전(락스텝)과 같은지 확인한다.
# 기준(단일 소스): backend/app/__init__.py 의 __version__
# 대상 파일 목록·변경 절차: VERSIONING.md
# 사용: scripts/check-versions.sh   (불일치 시 exit 1 — 릴리스 전/CI 에서 실행)
set -euo pipefail
cd "$(dirname "$0")/.."

base=$(grep -oP '__version__ = "\K[0-9.]+' backend/app/__init__.py)
echo "기준(RAG Studio): $base"
fail=0

check() { # check <라벨> <실제값>
  if [ "$2" = "$base" ]; then
    printf '  OK   %-28s %s\n' "$1" "$2"
  else
    printf '  FAIL %-28s %s (≠ %s)\n' "$1" "$2" "$base"
    fail=1
  fi
}

check "frontend(web)"        "$(grep -oP '"version":\s*"\K[0-9.]+' frontend/apps/web/package.json | head -1)"
check "frontend(root)"       "$(grep -oP '"version":\s*"\K[0-9.]+' frontend/package.json | head -1)"
check "agent"                "$(grep -oP '__version__ = "\K[0-9.]+' agent/app/__init__.py)"
check "agent(pyproject)"     "$(grep -oP '^version = "\K[0-9.]+' agent/pyproject.toml)"
check "embedding_server"     "$(grep -oP '__version__ = "\K[0-9.]+' extensions/embedding_server/__init__.py)"
check "reranker_server"      "$(grep -oP '__version__ = "\K[0-9.]+' extensions/reranker_server/__init__.py)"
check "detection_server"     "$(grep -oP '__version__ = "\K[0-9.]+' extensions/detection_server/__init__.py)"
check "hwp_render_server"    "$(grep -oP '"version":\s*"\K[0-9.]+' extensions/hwp_render_server/package.json | head -1)"
check "rhwp_py(pyproject)"   "$(grep -oP '^version = "\K[0-9.]+' backend/native/rhwp_py/pyproject.toml)"
check "rhwp_py(Cargo)"       "$(grep -oP '^version = "\K[0-9.]+' backend/native/rhwp_py/Cargo.toml)"
check "DDL(정합 표기)"       "$(grep -oP -- '-- 정합 앱 버전: \K[0-9.]+' backend/packaging/config/argus-rag-studio-postgresql.sql)"

# rhwp 코어(0.7.x — 별도 축)는 전용 스크립트로 검사
scripts/check-rhwp-version.sh || fail=1

# 릴리스 태그 존재(있으면 이미지 VERSION=git describe 가 이 값을 쓴다) — 경고만
if git rev-parse "v$base" >/dev/null 2>&1; then
  echo "  OK   git tag                      v$base"
else
  echo "  WARN git tag v$base 없음 — 릴리스 시 태그 필요(이미지 태그의 근원)"
fi

[ "$fail" -eq 0 ] && echo "OK — 버전 정합" || echo "FAIL — VERSIONING.md 의 파일 목록을 확인하세요" >&2
exit "$fail"
