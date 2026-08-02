#!/usr/bin/env bash
# rhwp 버전 정합 검사 — 세 소비처가 같은 rhwp 코어 릴리스를 쓰는지 확인한다.
#   1) backend/native/rhwp_py/Cargo.toml  : "# rev <hash> = v{버전}" 주석
#   2) frontend/apps/web/package.json     : "@rhwp/core": "{버전}" (정확 버전, 캐럿 금지)
#   3) extensions/hwp_render_server/package.json : 동일
# 추가로 rhwp_py 바인딩 버전이 RAG Studio 버전(backend/app/__init__.py)과 같은지 검사.
# 사용: scripts/check-rhwp-version.sh  (리포 루트 기준, CI/Makefile 연결용 — 불일치 시 exit 1)
set -euo pipefail
cd "$(dirname "$0")/.."

fail=0

cargo_ver=$(grep -oP '# rev [0-9a-f]+ = v\K[0-9.]+' backend/native/rhwp_py/Cargo.toml || true)
fe_ver=$(grep -oP '"@rhwp/core":\s*"\K[0-9.]+(?=")' frontend/apps/web/package.json || true)
rs_ver=$(grep -oP '"@rhwp/core":\s*"\K[0-9.]+(?=")' extensions/hwp_render_server/package.json || true)

echo "rhwp core: cargo(rev 주석)=$cargo_ver frontend=$fe_ver render-server=$rs_ver"
if [ -z "$cargo_ver" ] || [ -z "$fe_ver" ] || [ -z "$rs_ver" ]; then
  echo "ERROR: 버전 파싱 실패 — 캐럿(^) 사용 또는 rev 주석(# rev <hash> = vX.Y.Z) 누락" >&2
  fail=1
elif [ "$cargo_ver" != "$fe_ver" ] || [ "$cargo_ver" != "$rs_ver" ]; then
  echo "ERROR: rhwp 코어 버전 불일치 — 세 곳을 같은 릴리스로 맞추세요(native/rhwp_py/README.md 런북)" >&2
  fail=1
fi

app_ver=$(grep -oP '__version__ = "\K[0-9.]+' backend/app/__init__.py || true)
py_ver=$(grep -oP '^version = "\K[0-9.]+' backend/native/rhwp_py/pyproject.toml || true)
echo "rhwp_py 바인딩=$py_ver / RAG Studio=$app_ver"
if [ "$app_ver" != "$py_ver" ]; then
  echo "ERROR: rhwp_py 바인딩 버전이 RAG Studio 버전과 다릅니다(정책: 함께 올림)" >&2
  fail=1
fi

[ "$fail" -eq 0 ] && echo "OK — rhwp 버전 정합"
exit "$fail"
