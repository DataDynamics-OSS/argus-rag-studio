#!/usr/bin/env bash
# Argus RAG Studio — systemd/shell(비 Docker) production 배포용 tar 패키지 빌드
#
# 사용:
#   scripts/package.sh <backend|agent|embedding|reranker|detection|all> \
#       [--with-deps [VARIANT]] [--deb] [--rpm]
#
#   --with-deps [VARIANT]  의존성 wheel 을 wheels/ 에 동봉(에어갭 오프라인 설치용).
#                          VARIANT: cpu(기본)|gpu|gpu-torch — requirements-<v>.txt 기준.
#                          wheel 은 빌드 호스트의 아키/파이썬 기준으로 받는다 —
#                          대상 서버와 같은 플랫폼에서 빌드할 것.
#   --deb / --rpm          tar 와 동일한 페이로드를 OS 패키지로도 산출.
#                          페이로드는 /opt/argus-rag-studio/dist/<name>/ 에 설치되고
#                          postinst(%post)가 동봉 install.sh 를 실행해 venv·설정·
#                          systemd 유닛까지 전개한다(유닛은 enable 하지 않음 —
#                          설정 수정 후 operator 가 enable --now). 제거(purge) 시
#                          venv 등 생성물도 정리. rpm 은 rpmbuild 필요.
#
# 산출물: dist/argus-rag-studio-<comp>-<V>.tar.gz [+ .deb / .rpm]
#   (V = backend/app/__init__.py 의 제품 버전 — VERSIONING.md 락스텝)
# 패키지 구성: install.sh + (wheel|모듈 소스) + requirements*.txt + config/ + systemd/
# 설치(tar): 대상 서버에서 전개 후 `sudo ./install.sh` (옵션은 install.sh 헤더 참조)
set -euo pipefail
cd "$(dirname "$0")/.."

V=$(grep -oP '__version__ = "\K[0-9.]+' backend/app/__init__.py)
PY="${PY:-$( [ -x backend/.venv/bin/python ] && echo backend/.venv/bin/python || echo python3 )}"
WITH_DEPS=0
DEPS_VARIANT=cpu
BUILD_DEB=0
BUILD_RPM=0

comp="${1:-}"
shift || true
while [ $# -gt 0 ]; do
  case "$1" in
    --with-deps) WITH_DEPS=1; shift
                 if [ $# -gt 0 ] && [[ "$1" != --* ]]; then DEPS_VARIANT="$1"; shift; fi ;;
    --deb) BUILD_DEB=1; shift ;;
    --rpm) BUILD_RPM=1; shift ;;
    *) echo "알 수 없는 옵션: $1" >&2; exit 1 ;;
  esac
done

render_install() { # render_install <stage> <component> <mode> <module>
  sed "s|@COMPONENT@|$2|g; s|@MODE@|$3|g; s|@MODULE@|$4|g" \
    scripts/packaging/install-template.sh > "$1/install.sh"
  chmod +x "$1/install.sh"
}

bundle_deps() { # bundle_deps <stage> — --with-deps 시 requirements 를 wheels/ 로
  [ "$WITH_DEPS" = 1 ] || return 0
  local req="$1/requirements.txt"
  [ "$DEPS_VARIANT" != "cpu" ] && [ -f "$1/requirements-$DEPS_VARIANT.txt" ] && \
    req="$1/requirements-$DEPS_VARIANT.txt"
  echo ">> 의존성 wheel 동봉($req → wheels/)"
  "$PY" -m pip download -q -r "$req" -d "$1/wheels"
}

# OS 패키지 공통 — 설치/제거 스크립트 본문(deb postinst·rpm %post 공용)
_os_post() { # _os_post <name>
  cat <<EOF
set -e
cd /opt/argus-rag-studio/dist/$1
./install.sh --no-enable
echo "argus: 설정(/opt/argus-rag-studio/*/config) 확인 후 'systemctl enable --now <유닛>' 으로 시작하세요."
EOF
}

_os_preun() { # _os_preun <comp> — 유닛 정지·비활성(제거 시)
  cat <<'EOF'
set +e
for u in $(systemctl list-unit-files 'argus-rag-*' --no-legend 2>/dev/null | awk '{print $1}'); do
  case "$u" in
EOF
  # 이 컴포넌트가 설치한 유닛만 대상(백엔드는 워커 인스턴스 포함)
  local pats="$1"
  [ "$1" = "backend" ] && pats="argus-rag-studio-server.service argus-rag-worker-*.service" \
    || pats="argus-rag-studio-$1.service"
  for p in $pats; do echo "    $p) systemctl stop \"\$u\"; systemctl disable \"\$u\"; rm -f \"/etc/systemd/system/\$u\" ;;"; done
  cat <<'EOF'
  esac
done
systemctl daemon-reload
exit 0
EOF
}

_emit_deb() { # _emit_deb <stage> <name> <comp>
  local stage="$1" name="$2" c="$3" arch=all
  [ -d "$stage/wheels" ] && arch=$(dpkg --print-architecture)
  local root="dist/.debroot-$c"
  rm -rf "$root"; mkdir -p "$root/opt/argus-rag-studio/dist/$name" "$root/DEBIAN"
  cp -a "$stage/." "$root/opt/argus-rag-studio/dist/$name/"
  cat > "$root/DEBIAN/control" <<EOF
Package: argus-rag-studio-$c
Version: $V
Section: misc
Priority: optional
Architecture: $arch
Depends: python3 (>= 3.11), python3-venv
Maintainer: Data Dynamics Inc. <support@data-dynamics.io>
Description: Argus RAG Studio - $c
 systemd/shell production 배포용. postinst 가 venv 를 만들고 systemd 유닛을 설치한다.
EOF
  { echo "#!/bin/sh"; _os_post "$name"; } > "$root/DEBIAN/postinst"
  { echo "#!/bin/sh"; _os_preun "$c"; } > "$root/DEBIAN/prerm"
  { echo "#!/bin/sh"; cat <<EOF
set +e
if [ "\$1" = "purge" ] || [ "\$1" = "remove" ]; then
  rm -rf "/opt/argus-rag-studio/$c"        # postinst 가 만든 venv/설정 전개물
fi
exit 0
EOF
  } > "$root/DEBIAN/postrm"
  chmod 755 "$root/DEBIAN/postinst" "$root/DEBIAN/prerm" "$root/DEBIAN/postrm"
  dpkg-deb --build --root-owner-group "$root" "dist/argus-rag-studio-${c}_${V}_${arch}.deb" >/dev/null
  rm -rf "$root"
  echo ">> dist/argus-rag-studio-${c}_${V}_${arch}.deb"
}

_emit_rpm() { # _emit_rpm <stage> <name> <comp>
  command -v rpmbuild >/dev/null || { echo "!! rpmbuild 없음 — rpm 생략(rpm 계열 호스트에서 실행)"; return 0; }
  local stage="$1" name="$2" c="$3" arch=noarch
  [ -d "$stage/wheels" ] && arch=$(uname -m)
  local top="dist/.rpmtop-$c"
  rm -rf "$top"; mkdir -p "$top/SPECS" "$top/RPMS"
  cat > "$top/SPECS/pkg.spec" <<EOF
%global __brp_mangle_shebangs %{nil}
%global __brp_check_rpaths %{nil}
%global debug_package %{nil}
%global _build_id_links none
Name: argus-rag-studio-$c
Version: $V
Release: 1
Summary: Argus RAG Studio - $c (systemd/shell production 배포)
License: Proprietary
BuildArch: $arch
AutoReqProv: no
Requires: python3 >= 3.11

%description
Argus RAG Studio $c. %post 가 venv 를 만들고 systemd 유닛을 설치한다.

%install
mkdir -p %{buildroot}/opt/argus-rag-studio/dist/$name
cp -a $PWD/$stage/. %{buildroot}/opt/argus-rag-studio/dist/$name/

%files
/opt/argus-rag-studio/dist/$name

%post
$(_os_post "$name")

%preun
if [ \$1 -eq 0 ]; then
$(_os_preun "$c")
fi

%postun
if [ \$1 -eq 0 ]; then rm -rf /opt/argus-rag-studio/$c; fi
EOF
  rpmbuild -bb --define "_topdir $PWD/$top" "$top/SPECS/pkg.spec" >/dev/null 2>&1 || {
    rpmbuild -bb --define "_topdir $PWD/$top" "$top/SPECS/pkg.spec" 2>&1 | tail -5; return 1; }
  find "$top/RPMS" -name "*.rpm" -exec mv {} dist/ \;
  rm -rf "$top"
  echo ">> dist/argus-rag-studio-$c-$V-1.$arch.rpm"
}

finish() { # finish <stage-dir-name> <comp>
  tar czf "dist/$1.tar.gz" -C dist "$1"
  echo ">> dist/$1.tar.gz"
  [ "$BUILD_DEB" = 1 ] && _emit_deb "dist/$1" "$1" "$2"
  [ "$BUILD_RPM" = 1 ] && _emit_rpm "dist/$1" "$1" "$2"
  rm -rf "dist/${1:?}"
}

pkg_backend() {
  local name="argus-rag-studio-backend-$V" stage="dist/argus-rag-studio-backend-$V"
  rm -rf "$stage"; mkdir -p "$stage/config" "$stage/systemd"
  "$PY" -m pip wheel -q --no-deps -w "$stage" backend/
  cp backend/requirements.txt "$stage/"
  cp backend/packaging/config/config.properties backend/packaging/config/config.yml "$stage/config/"
  cp backend/packaging/config/argus-rag-studio-postgresql.sql "$stage/"   # 스키마 DDL 동봉
  cp backend/packaging/systemd/argus-rag-studio-server.service "$stage/systemd/"
  cp backend/packaging/systemd/argus-rag-worker.service.in "$stage/systemd/"
  render_install "$stage" backend wheel app
  bundle_deps "$stage"
  finish "$name" backend
}

pkg_agent() {
  local name="argus-rag-studio-agent-$V" stage="dist/argus-rag-studio-agent-$V"
  rm -rf "$stage"; mkdir -p "$stage/config" "$stage/systemd"
  "$PY" -m pip wheel -q --no-deps -w "$stage" agent/
  cp agent/requirements.txt "$stage/"
  cp agent/packaging/config/* "$stage/config/"
  # tar 설치용 유닛(venv 콘솔 스크립트) — deb 패키징의 유닛과 별개 레이아웃
  cat > "$stage/systemd/argus-rag-studio-agent.service" <<'UNIT'
[Unit]
Description=Argus RAG Studio Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
Group=root
Environment=ARGUS_CONFIG_DIR=__INSTALL_DIR__/config
ExecStart=__INSTALL_DIR__/venv/bin/argus-rag-studio-agent
Restart=on-failure
RestartSec=5
LimitNOFILE=65536
StandardOutput=journal
StandardError=journal
SyslogIdentifier=argus-rag-studio-agent

[Install]
WantedBy=multi-user.target
UNIT
  render_install "$stage" agent wheel app
  bundle_deps "$stage"
  finish "$name" agent
}

pkg_ext() { # pkg_ext <embedding|reranker|detection>
  local c="$1" name="argus-rag-studio-$1-server-$V" stage="dist/argus-rag-studio-$1-server-$V"
  local src="extensions/${c}_server"
  rm -rf "$stage"; mkdir -p "$stage/config" "$stage/systemd"
  # pyproject 없는 순수 모듈 — 소스 복사 방식(install.sh 가 INSTALL_DIR 로 전개)
  mkdir -p "$stage/${c}_server"
  find "$src" -maxdepth 1 -name "*.py" -exec cp {} "$stage/${c}_server/" \;
  cp "$src"/requirements*.txt "$stage/"
  cp "$src"/packaging/config/* "$stage/config/"
  cp "$src/packaging/systemd/argus-rag-studio-$c-server.service" "$stage/systemd/"
  render_install "$stage" "$c-server" source "${c}_server"
  bundle_deps "$stage"
  finish "$name" "$c-server"
}

mkdir -p dist
case "$comp" in
  backend) pkg_backend ;;
  agent) pkg_agent ;;
  embedding|reranker|detection) pkg_ext "$comp" ;;
  all) pkg_backend; pkg_agent; pkg_ext embedding; pkg_ext reranker; pkg_ext detection ;;
  *) echo "사용: $0 <backend|agent|embedding|reranker|detection|all> [--with-deps [VARIANT]]" >&2; exit 1 ;;
esac
