#!/usr/bin/env bash
# Argus RAG Studio — @COMPONENT@ 패키지 설치 스크립트 (tar 패키지에 동봉되어 배포됨)
# 생성: scripts/package.sh (리포). 이 파일을 직접 수정하지 말 것 — 템플릿에서 렌더된다.
#
# 사용: sudo ./install.sh [옵션]
#   --prefix <dir>    설치 루트 (기본 /opt/argus-rag-studio) → <prefix>/@COMPONENT@/
#   --variant <v>     cpu|gpu|gpu-torch — requirements-<v>.txt 선택(있을 때만, 기본 cpu)
#   --workers <N>     (backend 전용) argus-rag-worker-1..N systemd 유닛 생성 (기본 1)
#   --python <bin>    venv 를 만들 파이썬 (기본 python3 — 3.11+ 필요)
#   --no-enable       systemd 유닛 설치만 하고 enable/start 는 생략
#
# 오프라인(에어갭): 패키지에 wheels/ 디렉터리가 있으면(--with-deps 로 빌드된 패키지)
# PyPI 접속 없이 wheels/ 만으로 설치한다.
set -euo pipefail
cd "$(dirname "$0")"

COMPONENT="@COMPONENT@"     # backend | agent | embedding-server | ...
MODE="@MODE@"               # wheel(백엔드·에이전트) | source(확장 서버)
MODULE="@MODULE@"           # source 모드에서 복사되는 모듈 디렉터리명

PREFIX=/opt/argus-rag-studio
VARIANT=cpu
WORKERS=1
PYTHON=python3
ENABLE=1
while [ $# -gt 0 ]; do
  case "$1" in
    --prefix) PREFIX="$2"; shift 2 ;;
    --variant) VARIANT="$2"; shift 2 ;;
    --workers) WORKERS="$2"; shift 2 ;;
    --python) PYTHON="$2"; shift 2 ;;
    --no-enable) ENABLE=0; shift ;;
    *) echo "알 수 없는 옵션: $1" >&2; exit 1 ;;
  esac
done

INSTALL_DIR="$PREFIX/$COMPONENT"
echo ">> $COMPONENT → $INSTALL_DIR (variant=$VARIANT)"

"$PYTHON" - <<'PYCHK'
import sys
assert sys.version_info >= (3, 11), f"Python 3.11+ 필요 (현재 {sys.version.split()[0]})"
PYCHK

mkdir -p "$INSTALL_DIR"

# 1) venv + 의존성 (wheels/ 있으면 오프라인)
[ -d "$INSTALL_DIR/venv" ] || "$PYTHON" -m venv "$INSTALL_DIR/venv"
PIP="$INSTALL_DIR/venv/bin/pip"
PIP_OPTS=()
if [ -d wheels ]; then
  PIP_OPTS=(--no-index --find-links wheels)
  echo ">> 오프라인 설치(wheels/)"
fi
REQ=requirements.txt
[ "$VARIANT" != "cpu" ] && [ -f "requirements-$VARIANT.txt" ] && REQ="requirements-$VARIANT.txt"
"$PIP" install -q --upgrade pip
if [ "$MODE" = "wheel" ]; then
  "$PIP" install -q "${PIP_OPTS[@]}" ./*.whl -r "$REQ"
else
  "$PIP" install -q "${PIP_OPTS[@]}" -r "$REQ"
  rm -rf "$INSTALL_DIR/$MODULE"
  cp -a "$MODULE" "$INSTALL_DIR/"
fi

# 2) 설정 — 기존 설치의 config 는 보존하고 새 기본값은 .new 로
if [ -d "$INSTALL_DIR/config" ]; then
  for f in config/*; do
    base="$(basename "$f")"
    if [ -f "$INSTALL_DIR/config/$base" ]; then cp "$f" "$INSTALL_DIR/config/$base.new";
    else cp "$f" "$INSTALL_DIR/config/"; fi
  done
  echo ">> 기존 config 보존(새 기본값은 *.new)"
else
  mkdir -p "$INSTALL_DIR/config"
  cp -a config/* "$INSTALL_DIR/config/"
fi

# 3) systemd 유닛 — __INSTALL_DIR__ 치환 후 설치
render() { sed "s|__INSTALL_DIR__|$INSTALL_DIR|g; s|__N__|$2|g" "$1"; }
UNITS=()
for u in systemd/*.service; do
  [ -e "$u" ] || continue
  name="$(basename "$u")"
  render "$u" 0 > "/etc/systemd/system/$name"
  UNITS+=("$name")
done
if [ -f systemd/argus-rag-worker.service.in ]; then
  for i in $(seq 1 "$WORKERS"); do
    render systemd/argus-rag-worker.service.in "$i" > "/etc/systemd/system/argus-rag-worker-$i.service"
    UNITS+=("argus-rag-worker-$i.service")
  done
fi
systemctl daemon-reload
if [ "$ENABLE" = 1 ]; then
  for u in "${UNITS[@]}"; do systemctl enable --now "$u"; done
fi

echo ">> 완료. 유닛: ${UNITS[*]:-없음}"
echo ">> 설정 확인: $INSTALL_DIR/config (DB/MinIO/서버 URL 등을 환경에 맞게 수정 후 restart)"
