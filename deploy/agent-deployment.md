# 에이전트 배포 가이드 (Argus RAG Studio Agent)

- **역할**: 각 서버에서 **root 권한**으로 동작하는 관리 데몬 — 컨테이너/systemd 배포 실행,
  모델 볼륨 설치(modelmgr), 명령/터미널, 하트비트 보고. **부트스트랩 컴포넌트**라서
  다른 모든 서비스는 플랫폼(배포 API)이 배포하지만, 에이전트 자신만은 수동 설치가 필요하다.
- **소스**: `agent/` · **포트**: 4501 · **실행 방식**: systemd 전용(권장·표준 — root 상주 데몬)
- **탐색**: 설치 후 에이전트가 백엔드로 하트비트를 보내면 **에이전트 > 서버 관리에 자동
  등장**(UNREGISTERED) → 화면에서 "등록"하면 배포 대상이 된다.
- ⚠️ **보안**: root + 무인증 REST API — 내부망 전용. 외부 노출 금지(방화벽 필수).

## 방법 1 — deb/rpm 패키지

```bash
cd agent && make deb        # 또는 make rpm — dist/ 에 패키지 생성
# 대상 서버에서
sudo dpkg -i argus-rag-studio-agent_*.deb
sudo vi /etc/argus-rag-studio-agent/server.properties   # 백엔드 주소(하트비트 대상) 지정
sudo systemctl enable --now argus-rag-studio-agent
```

패키지가 systemd unit(`packaging/systemd/`)·설정(`/etc/argus-rag-studio-agent/`)·코드
(`/opt/argus-rag-studio-agent/`)를 배치한다.

## 방법 2 — 소스 설치 (현행 dev/DGX 방식)

```bash
# 1) 코드 배치 + venv (대상 서버, root)
sudo mkdir -p /opt/argus-rag-studio-agent && cd /opt/argus-rag-studio-agent
# agent/ 디렉터리 내용 복사(tar 전송 등: app/ pyproject.toml requirements.txt)
python3 -m venv venv && venv/bin/pip install .

# 2) 설정 — /etc/argus-rag-studio-agent/
sudo mkdir -p /etc/argus-rag-studio-agent
sudo cp packaging/config/config.yml packaging/config/config.properties /etc/argus-rag-studio-agent/
# server.properties — 하트비트를 보낼 백엔드 주소
printf 'server.ip=<backend-host>\nserver.port=4700\n' | sudo tee /etc/argus-rag-studio-agent/server.properties

# 3) systemd unit — 제공 unit 의 ExecStart 만 venv 경로로 조정
sudo cp packaging/systemd/argus-rag-studio-agent.service /etc/systemd/system/
sudo sed -i 's|/opt/argus-rag-studio-agent/bin/|/opt/argus-rag-studio-agent/venv/bin/|' \
  /etc/systemd/system/argus-rag-studio-agent.service
sudo systemctl daemon-reload && sudo systemctl enable --now argus-rag-studio-agent
```

> 개발 호스트(백엔드 체크아웃이 있는 서버)는 체크아웃 직접 실행도 가능:
> `ExecStart=<체크아웃>/agent/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 4501`,
> `WorkingDirectory=<체크아웃>/agent` — 코드 수정이 재시작만으로 반영된다.

## 비-root 실행 (제한 모드)

보안 정책상 root 상주 데몬이 불가한 호스트용. Docker 데몬은 root 로 돌지만, 에이전트
계정은 **docker 그룹**만 있으면 컨테이너 라이프사이클을 수행할 수 있다.

```bash
# 1) 서비스 계정 + docker 그룹 (관리자 1회)
sudo useradd -r -m -s /usr/sbin/nologin argus-agent
sudo usermod -aG docker argus-agent

# 2) 파일 소유권 — 코드·인증서 디렉터리를 서비스 계정으로
sudo chown -R argus-agent:argus-agent /opt/argus-rag-studio-agent

# 3) unit 의 실행 계정 변경
sudo sed -i 's/^User=root/User=argus-agent/; s/^Group=root/Group=docker/' \
  /etc/systemd/system/argus-rag-studio-agent.service
sudo systemctl daemon-reload && sudo systemctl restart argus-rag-studio-agent
```

(unit 의 `StateDirectory`/`LogsDirectory`/`ConfigurationDirectory` 지시자가
`/var/lib`·`/var/log`·`/etc` 하위 디렉터리를 실행 계정 소유로 만들어 주므로 별도 chown 불필요.)

**기능 매트릭스 — 비-root 에서 되는 것/안 되는 것:**

| 기능 | 비-root | 비고 |
|---|---|---|
| 컨테이너 배포/조회/제어 (containermgr) | ✅ | docker 그룹으로 충분 — 서버형 kind 전부 배포 가능 |
| 하트비트·모니터링·sysmon·메트릭 | ✅ | |
| 명령 실행·터미널·filemgr | ⚠️ | 해당 계정 권한 범위 내에서만(시스템 파일 수정 불가) |
| **systemd 워커 배포 (servicemgr)** | ❌ | system unit 생성은 root 필수 — 워커는 Docker 방식으로 배포 |
| **모델 볼륨 설치 (modelmgr)** | ❌ | 볼륨 Mountpoint(`/var/lib/docker/...`)가 root 소유 — 배포 시 온라인 폴백(`ALLOW_ONLINE_MODEL=1`) 또는 모델 수동 반입으로 대체 |
| usermgr·hostmgr·yum·certmgr(시스템 변경류) | ❌ | 서버 관리 화면의 해당 기능 사용 불가 |

즉 비-root 에이전트는 **"Docker 배포 + 관측" 전용**으로 동작한다 — 에어갭 모델
사전 설치와 systemd 워커가 필요한 호스트는 root 실행이 필요하다.
(배포 방식별 요구 권한 등급 — docker=host_docker, systemd=host_root, k8s=cluster_rbac.)

**root 가 아예 없는 호스트**(sudo 불가 — 예: 공용 GPU 장비)는 사용자 세션으로도 가능:

```bash
# 관리자에게 1회 요청: docker 그룹 추가 + linger 활성화(로그아웃 후에도 유지)
#   sudo usermod -aG docker <user> && sudo loginctl enable-linger <user>
mkdir -p ~/.config/systemd/user
cp packaging/systemd/argus-rag-studio-agent.service ~/.config/systemd/user/
# unit 에서 User=/Group= 줄 삭제 + ExecStart 를 사용자 경로(venv)로 수정 후:
systemctl --user daemon-reload && systemctl --user enable --now argus-rag-studio-agent
```

## 업데이트 절차 (운영 중 에이전트)

에이전트는 자기 자신을 배포/재시작할 수 없다(systemd 자기 unit 보호). 확립된 절차:

```bash
# 1) 새 코드 전송(관리 워크스테이션에서)
tar czf /tmp/agent-update.tar.gz --exclude='__pycache__' app/ pyproject.toml requirements.txt
scp /tmp/agent-update.tar.gz <user>@<host>:/tmp/

# 2) 전개 + venv 재설치 — 에이전트 command API(root)로 원격 수행 가능
#    ⚠️ pip 재설치 필수: 서비스는 venv site-packages 의 "사본"으로 실행되므로
#       /opt 소스만 바꾸면 반영되지 않는다.
curl -X POST http://<host>:4501/api/v1/command/execute -H 'Content-Type: application/json' -d '{
  "command": "set -e; cd /opt/argus-rag-studio-agent; cp -a app app.bak-$(date +%Y%m%d); tar xzf /tmp/agent-update.tar.gz -C .; venv/bin/pip install --no-deps --quiet .; echo OK",
  "timeout": 110}'

# 3) 재시작 — 자기 cgroup 이 죽어도 실행되도록 분리 트랜지언트 유닛으로 예약
curl -X POST http://<host>:4501/api/v1/command/execute -H 'Content-Type: application/json' -d '{
  "command": "systemd-run --on-active=2 --unit=agent-restart-$(date +%s) /bin/systemctl restart argus-rag-studio-agent",
  "timeout": 10}'
```

## 검증

```bash
curl -s http://<host>:4501/health          # {"status":"ok",...}
curl -s http://<host>:4501/openapi.json | jq '.paths | keys | length'
# 백엔드: 에이전트 > 서버 관리에 하트비트 수신(1분 내) 확인 후 "등록"
```

## 옵션 레퍼런스 (`/etc/argus-rag-studio-agent/`)

| 파일/키 | 기본값 | 설명 |
|---|---|---|
| `server.properties` → server.ip / server.port | localhost / 4700 | **하트비트 대상 백엔드** — 반드시 실제 백엔드 주소로 |
| config.properties → server.host / server.port | 0.0.0.0 / 4501 | 에이전트 바인드 주소/포트 |
| heartbeat.interval | 60 | 하트비트 주기(초) — 관리 서비스 인벤토리 포함 보고 |
| command.timeout / command.max_output | 300 / 1MB | 원격 명령 실행 한계 |
| terminal.shell / terminal.max_sessions | /bin/bash / 10 | 원격 터미널 |
| cert.dir / log.* / backup.dir / data.dir | (CLAUDE.md 참조) | 인증서·로그·백업·데이터 경로 |
| prometheus.* | push 활성, localhost:9091 | 호스트 메트릭 Push Gateway 전송 |

전체 키·CLI는 `agent/CLAUDE.md` 참조.
