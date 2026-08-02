# NiFi 보안 클러스터 배포 (Ansible)

> 이 구성요소는 Ansible 기반 설치형으로, 에이전트 Docker 배포(이미지 파이프라인) 대상이 아니다.

> Apache NiFi **보안 클러스터**를 Ansible 로 배포하는 외부 참조 구현.
> **TLS(사설 CA)** 와 **로그인 인증(Single-User / LDAP)** 을 기본 적용하고,
> 외부 **ZooKeeper 앙상블**로 클러스터 코디네이션을 구성한다.

Argus RAG Studio 의 데이터 수집 파이프라인(소스 커넥터·전처리·적재)을 NiFi 로
운영할 때, 고객 인프라에 **재현 가능한 보안 클러스터**를 빠르게 세우기 위한 도구다.
NiFi 자체는 느슨하게 결합된 외부 런타임이며, 이 플레이북은 그 *배포·구성*만 담당한다.

---

## 무엇을 구성하나

| 영역 | 적용 내용 |
|------|-----------|
| **TLS** | NiFi Toolkit `tls-toolkit standalone` 로 사설 CA + 노드별 keystore/truststore + 관리자 클라이언트 인증서 발급(**유효기간 10년**). 모든 노드 간/UI 통신 HTTPS. HTTP 비활성. |
| **로그인 인증** | 기본 **Single-User**(사용자명/비밀번호). 변수 한 줄로 **LDAP/AD** 전환. |
| **인가** | single-user → `SingleUserAuthorizer`(단일 사용자 전권). ldap/클러스터 → 파일 기반 Managed Authorizer(최초 관리자 + 노드 신원 자동 등록). |
| **클러스터** | 모든 노드 동일 클러스터, 노드 간 프로토콜 TLS, 외부 ZooKeeper 로 프라이머리/코디네이터 선출. |
| **상태 저장** | 외부 ZooKeeper 앙상블(임베디드 ZK 미사용). |
| **운영** | systemd 유닛, ulimit/커널 튜닝, JVM 힙 설정, 순차(serial) 기동. |

---

## 디렉터리 구조

```
nifi-cluster-deploy/
  ansible.cfg
  site.yml                      # 진입점 플레이북
  requirements.yml              # (외부 컬렉션 의존 없음)
  Makefile
  inventories/sample/
    hosts.yml                   # 인벤토리(호스트/그룹)
    group_vars/
      all.yml                   # 버전·CA·TLS 비밀번호
      nifi_cluster.yml          # NiFi 포트·인증·힙·민감키
      zookeeper.yml             # ZK 포트·경로
  roles/
    common/                     # 계정·패키지·ulimit·sysctl
    java/                       # JVM 설치 + JAVA_HOME 탐지
    zookeeper/                  # ZK 앙상블
    nifi_certs/                 # 사설 CA + 인증서 발급/분배
    nifi/                       # NiFi 설치 + 보안 클러스터 구성
```

---

## 사전 요구사항

- 컨트롤러: Ansible 2.15+ (core), Python 3, 대상 호스트로의 SSH/sudo.
- 대상 호스트: Ubuntu 22.04+/Debian 12+ 또는 RHEL 계열 9+, 인터넷(또는 사내 Apache 미러) 접근.
- **Java 21**: NiFi 2.x 는 Java 21 이 필요하다(플레이북이 자동 설치). 인증서 발급용
  1.x 툴킷도 Java 21 에서 동작한다.
- **DNS/FQDN**: 인벤토리의 `inventory_hostname` 은 노드 간 통신이 되는 FQDN 이어야 한다
  (인증서 CN/SAN, 클러스터 노드 주소로 쓰임).
- 방화벽 개방: `9444`(UI HTTPS), `11443`(클러스터 프로토콜), `6342`(로드밸런스),
  `10443`(Site-to-Site), ZooKeeper `2181/2888/3888`.

---

## 빠른 시작

```bash
cd extensions/nifi-cluster-deploy

# 1) 인벤토리/변수 편집 — 실제 호스트, 비밀번호, 관리자 자격증명
$EDITOR inventories/sample/hosts.yml
$EDITOR inventories/sample/group_vars/all.yml
$EDITOR inventories/sample/group_vars/nifi_cluster.yml

# 2) 연결 확인
make ping

# 3) 전체 배포(인증서 → ZooKeeper → NiFi)
make deploy            # 또는: ansible-playbook site.yml

# 부분 실행
make certs             # 인증서만
make zk                # ZooKeeper만
make nifi              # NiFi만
```

배포 후 UI: `https://<노드 FQDN>:9444/nifi`

---

## 로그인 / 접속

### Single-User (기본)
`nifi_cluster.yml` 의 자격증명으로 로그인한다.

```yaml
nifi_auth_method: single-user
nifi_initial_admin_identity: "admin"     # 로그인 사용자명과 동일해야 함
nifi_single_user_username: "admin"
nifi_single_user_password: "adminadminadmin"   # NiFi 최소 12자. 운영은 vault 권장
```

> 기본 자격증명은 `admin` / `adminadminadmin` 이다. **운영 전 반드시 교체**하라.

> 비밀번호 교체 시: 각 노드의 `conf/.single-user-applied` 와
> `conf/login-identity-providers.xml` 삭제 후 플레이북 재실행.

### LDAP / AD
```yaml
nifi_auth_method: ldap
nifi_initial_admin_identity: "uid=alice,ou=people,dc=example,dc=com"  # 또는 USE_USERNAME 시 "alice"
nifi_ldap_url: "ldaps://ldap.example.com:636"
nifi_ldap_manager_dn: "cn=admin,dc=example,dc=com"
nifi_ldap_manager_password: "<bind 비밀번호>"
nifi_ldap_user_search_base: "ou=people,dc=example,dc=com"
nifi_ldap_user_search_filter: "(uid={0})"
nifi_ldap_identity_strategy: "USE_USERNAME"
```

### 관리자 클라이언트 인증서(브라우저 mTLS)
`tls-toolkit` 가 관리자용 PKCS12 번들을 만든다. 배포 후 컨트롤러의
`.generated-certs/admin/` 에 회수된다:

- `CN=<admin>_OU=NIFI.p12` — 브라우저/클라이언트로 가져올 인증서
- `*.password` — 위 p12 의 비밀번호
- `nifi-cert.pem` — 사내 CA 공개 인증서(신뢰 추가용)

p12 를 OS/브라우저에 import 하면 인증서 기반으로도 관리자 접근이 가능하다.

---

## TLS 인증서 동작 방식

1. `cert_authority_host`(기본: 첫 NiFi 노드)에서만 NiFi Toolkit 을 받아
   `tls-toolkit standalone` 로 **CA + 전 노드 인증서 + 관리자 인증서**를 일괄 생성.
2. 생성물을 **컨트롤러로 회수**(`.generated-certs/`, git 제외).
3. 각 노드로 자기 `keystore`/`truststore` 를 배치.
4. 노드 인증서 DN = `CN=<fqdn>, OU={{ tls_org_unit }}` → `authorizers.xml` 의
   Node Identity 와 정확히 일치하여 노드 간 프록시 요청이 인가된다.

인증서 유효기간은 `tls_cert_days`(기본 **3650일 = 10년**) 로 CA·노드·관리자 모두에
적용된다. NiFi 2.x 툴킷에는 `tls-toolkit` 가 없으므로 이를 포함한 마지막 1.x 툴킷
(`nifi_toolkit_version`)을 인증서 발급에만 사용한다 — 산출물은 표준 keystore 라 NiFi
2.x 와 호환된다.

> 재발급: `cert_authority_host` 의 `{{ cert_build_dir }}/target` 삭제 후
> `make certs`. 노드 신원이 바뀌면 각 노드 `conf/users.xml`·`authorizations.xml`
> 도 삭제해야 새 신원이 반영된다.

---

## 비밀값 보호 (ansible-vault)

운영에서는 비밀번호/키를 평문으로 두지 말 것:

```bash
ansible-vault encrypt_string 'MyKeystorePass'   --name 'tls_keystore_password'
ansible-vault encrypt_string 'MyTruststorePass' --name 'tls_truststore_password'
ansible-vault encrypt_string 'MyAdminLogin'     --name 'nifi_single_user_password'
ansible-vault encrypt_string 'random-32-chars'  --name 'nifi_sensitive_props_key'
```
출력 블록을 group_vars 에 붙이고 `make deploy`(기본 `--ask-vault-pass`) 실행.

---

## 주요 변수 (요약)

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `nifi_version` | `2.9.0` | NiFi 2.x 최신(Java 21 필요) |
| `nifi_toolkit_version` | `1.28.1` | 인증서 발급용 툴킷(tls-toolkit 포함 마지막 1.x) |
| `nifi_auth_method` | `single-user` | `single-user` \| `ldap` |
| `nifi_initial_admin_identity` | `admin` | 최초 전권 관리자 |
| `nifi_single_user_password` | `adminadminadmin` | 기본 로그인 비밀번호(운영 전 교체) |
| `nifi_web_https_port` | `9444` | UI(HTTPS) 포트 |
| `nifi_cluster_node_protocol_port` | `11443` | 클러스터 프로토콜(TLS) |
| `tls_store_type` | `JKS` | `JKS` \| `PKCS12` |
| `tls_cert_days` | `3650` | 발급 인증서 유효기간(일, 10년) |
| `tls_org_unit` | `NIFI` | 인증서 OU(노드 DN 구성) |
| `nifi_sensitive_props_key` | (교체 필요) | 민감 속성 암호화 키(클러스터 동일) |
| `cert_authority_host` | 첫 NiFi 노드 | 인증서 일괄 생성 호스트 |

전체 변수는 `inventories/sample/group_vars/` 참고.

---

## 검증 / 트러블슈팅

```bash
# 노드 상태(서비스)
ansible -i inventories/sample/hosts.yml nifi_cluster -m shell -a 'systemctl status nifi --no-pager | head'

# 클러스터 합류 로그
ansible -i inventories/sample/hosts.yml nifi_cluster -m shell \
  -a 'grep -i "Connection Status\|Cluster Coordinator\|Elected" /var/log/nifi/nifi-app.log | tail'
```

- **노드가 클러스터에 안 붙음**: ZooKeeper 연결 문자열/방화벽(`11443`), 시간 동기(NTP),
  FQDN 일치 확인.
- **로그인 실패**: `nifi_initial_admin_identity` 가 로그인 사용자명(single-user)과
  동일한지, LDAP 면 `Identity Strategy` 와 admin 식별자 형식 일치 확인.
- **첫 기동 시 플로우 선출 대기**: `nifi.cluster.flow.election.max.wait` 만큼 대기 후
  선출(정상). `serial: 1` 로 노드를 순차 기동한다.

---

## 한계 / 비범위

- 로드밸런서/리버스 프록시(HAProxy/Nginx) 구성은 포함하지 않는다.
  외부 LB 도메인은 `tls_extra_sans` 와 `nifi.web.proxy.host` 에 추가하면 된다.
- 백업/복구, NiFi Registry, 모니터링(Prometheus) 연동은 별도 범위.
- Single-User 는 PoC/소규모용. 운영 다중 사용자 환경은 LDAP/OIDC 권장.
