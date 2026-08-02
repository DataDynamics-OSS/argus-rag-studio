#!/usr/bin/env bash
# Argus RAG Studio — 이미지 빌드/푸시 래퍼 (docker buildx bake)
#
# 사용:
#   scripts/build-images.sh load                 # 로컬(현재 아키, --load)
#   scripts/build-images.sh push                 # 멀티아키 빌드 + 레지스트리 push
#   scripts/build-images.sh one <KIND> [VARIANT] # 단일 타깃 빌드(--load)
#
# 환경변수:
#   VERSION   미지정 시 git describe --tags --always (없으면 dev)
#   REGISTRY  push 대상 (예: zot.airgap.local:5000/argus). load 시 비워도 됨.
set -euo pipefail
cd "$(dirname "$0")/.."

: "${VERSION:=$(git describe --tags --always 2>/dev/null || echo dev)}"
: "${REGISTRY:=}"
: "${FLAT_REPO:=}"
export VERSION REGISTRY FLAT_REPO

# 현재 호스트 아키 → buildx platform (load 는 단일 플랫폼만 가능)
case "$(uname -m)" in
  x86_64|amd64) HOSTPLAT="linux/amd64" ;;
  aarch64|arm64) HOSTPLAT="linux/arm64" ;;
  *) HOSTPLAT="linux/$(uname -m)" ;;
esac

# kind(+variant) → bake 타깃명
target_for() {
  local kind="$1" variant="${2:-cpu}" base
  case "$kind" in
    hwp_render|hwp) base="hwp" ;;
    worker|backend) base="backend" ;;   # 배포 kind=worker, 이미지/타깃=backend(API·워커 겸용)
    *) base="$kind" ;;
  esac
  case "$variant" in
    cpu|""|auto) echo "$base" ;;
    gpu) echo "${base}-gpu" ;;
    gpu-torch) echo "${base}-gpu-torch" ;;
    *) echo "알 수 없는 variant: $variant" >&2; exit 1 ;;
  esac
}

cmd="${1:-load}"
case "$cmd" in
  load)
    echo ">> 로컬 빌드 (VERSION=$VERSION, platform=$HOSTPLAT, --load)"
    docker buildx bake --set "*.platform=$HOSTPLAT" --load
    ;;
  push)
    [ -n "$REGISTRY" ] || [ -n "$FLAT_REPO" ] || { echo "REGISTRY 또는 FLAT_REPO 가 필요합니다 (예: REGISTRY=zot:5000/argus, FLAT_REPO=datadynamics/argus-rag-studio)" >&2; exit 1; }
    echo ">> 멀티아키 빌드+푸시 (VERSION=$VERSION, REGISTRY=$REGISTRY)"
    docker buildx bake --push
    ;;
  one)
    [ $# -ge 2 ] || { echo "사용: $0 one <KIND> [VARIANT]" >&2; exit 1; }
    t="$(target_for "$2" "${3:-cpu}")"
    echo ">> 단일 빌드: $t (VERSION=$VERSION, platform=$HOSTPLAT, --load)"
    docker buildx bake --set "*.platform=$HOSTPLAT" --load "$t"
    ;;
  *)
    echo "사용: $0 {load|push|one <KIND> [VARIANT]}" >&2
    exit 1
    ;;
esac
