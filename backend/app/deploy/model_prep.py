# SPDX-License-Identifier: Apache-2.0
"""vlm 배포의 모델 준비 단계 — 모델 저장소(argus-models) 보유 확인 → 에이전트 설치.

설계: design/model-packaging.md §3.4(Phase 2). 흐름:

  1. 배포 스펙의 VLM_MODEL(카탈로그 키)을 해석한다(미지정=기본 모델).
  2. 모델 저장소에서 manifest 를 찾는다(revision 은 main 우선).
     - 보유: 아카이브 presigned URL 을 만들어 에이전트 ``/model/install`` 호출(sha256
       검증·멱등 전개) → 스펙에 로컬 경로(VLM_LOCAL_PATH)를 주입해 **오프라인 서빙**.
     - 미보유: 배포 거부(409) + 반입 안내. 단 ALLOW_ONLINE_MODEL=1(배포 UI 체크)이면
       경고 후 온라인(HF 다운로드) 모드로 진행한다.
  3. VLLM_ARGS(고급, 인자 직접 지정)면 준비 단계를 건너뛴다(모델 관리는 사용자 책임).

presigned URL 을 쓰는 이유: 에이전트에 S3 자격증명을 주지 않기 위함. 엔드포인트는
배포 스펙의 os_endpoint(라우팅 가능 주소) 우선 — localhost 기본값은 원격 에이전트가
접근할 수 없다.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator

from botocore.exceptions import ClientError

from app.core.config import settings
from app.deploy._agent import AgentHost, agent_request
from app.deploy.models import DeployError, DeploySpec

logger = logging.getLogger(__name__)

VLM_VOLUME = "argus-rag-vlm-models"

# 배포 시 보유 모델을 사전 설치(pre-warm)하는 kind — 서버가 이름으로 캐시 조회(hf-cache).
PREWARM_KINDS = ("embedding", "reranker")


def _models_client(endpoint: str):
    import boto3
    from botocore.config import Config as BotoConfig

    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=settings.os_access_key,
        aws_secret_access_key=settings.os_secret_key,
        region_name=settings.os_region,
        config=BotoConfig(
            signature_version="s3v4", s3={"addressing_style": "path"},
            connect_timeout=3, retries={"max_attempts": 1},
        ),
    )


def _find_manifest(client, name: str) -> dict | None:
    """모델 저장소에서 vlm/{name} 의 manifest 를 찾는다(main revision 우선)."""
    bucket = settings.os_models_bucket
    try:
        resp = client.list_objects_v2(Bucket=bucket, Prefix=f"vlm/{name}/")
    except ClientError:
        return None
    revisions = sorted({
        key.split("/")[2]
        for obj in resp.get("Contents", [])
        if len((key := obj["Key"]).split("/")) == 4 and key.endswith("manifest.json")
    })
    if not revisions:
        return None
    rev = "main" if "main" in revisions else revisions[0]
    try:
        raw = client.get_object(Bucket=bucket, Key=f"vlm/{name}/{rev}/manifest.json")["Body"].read()
        manifest = json.loads(raw)
    except (ClientError, ValueError):
        return None
    manifest["revision"] = manifest.get("revision") or rev
    return manifest


async def prepare_vlm_model(spec: DeploySpec, host: AgentHost) -> AsyncIterator[dict]:
    """모델 준비 이벤트를 yield 하며 spec.env 를 갱신한다. 미보유+온라인 불허 시 DeployError."""
    if spec.env.get("VLLM_ARGS"):
        yield {"phase": "model", "status": "done", "detail": "VLLM_ARGS 직접 지정 — 모델 준비 생략"}
        return

    from app.modelreg.service import resolve_vlm_model

    m = await resolve_vlm_model(spec.env.get("VLM_MODEL"))
    if m is None:
        raise DeployError("알 수 없는 VLM 모델입니다(모델 관리에 등록된 name 또는 repo 로 지정).", code=400)
    # 이후 단계(컨테이너 스펙 빌더·설정 주입)는 동기 문맥 — 해석 결과를 env 에 스태시.
    spec.env["VLM_MODEL"] = m["name"]
    spec.env["VLM_REPO"] = m["repo"]
    spec.env["VLM_MAX_LEN"] = str(m["max_len"] or 8192)

    yield {"phase": "model", "status": "running", "detail": f"모델 저장소 확인: {m['name']}"}
    endpoint = spec.os_endpoint or settings.os_endpoint
    client = _models_client(endpoint)
    manifest = await asyncio.to_thread(_find_manifest, client, m["name"])

    if manifest is None:
        if spec.env.get("ALLOW_ONLINE_MODEL") == "1":
            yield {
                "phase": "model", "status": "done",
                "detail": f"미보유 — 온라인(HF 다운로드) 모드로 진행: {m['repo']}",
            }
            return
        raise DeployError(
            f"모델 저장소({settings.os_models_bucket})에 '{m['name']}' 이 없습니다. "
            f"외부망에서 `python -m scripts.pack_model vlm/{m['name']}` 로 팩해 반입하거나, "
            "배포 옵션의 '모델 온라인 다운로드 허용'을 켜세요(에어갭 비권장).",
            code=409,
        )

    # 보유 — 에이전트 설치(멱등). presigned URL 은 에이전트가 접근할 엔드포인트로 서명.
    if "localhost" in endpoint or "127.0.0.1" in endpoint:
        yield {
            "phase": "model", "status": "running",
            "detail": f"주의: 스토리지 엔드포인트({endpoint})가 localhost — 원격 에이전트는 접근 불가(os_endpoint 지정 필요)",
        }
    key = f"vlm/{m['name']}/{manifest['revision']}/{manifest['archive']}"
    url = await asyncio.to_thread(
        client.generate_presigned_url, "get_object",
        Params={"Bucket": settings.os_models_bucket, "Key": key}, ExpiresIn=3600,
    )
    size_mb = (manifest.get("size_bytes") or 0) / 1e6
    yield {
        "phase": "model", "status": "running",
        "detail": f"에이전트에 모델 설치 중: {m['name']}@{manifest['revision']} ({size_mb:.0f} MB)",
    }
    result = await agent_request(
        "POST", host.ip, "/api/v1/model/install",
        json={
            "volume": VLM_VOLUME, "subdir": m["name"],
            "archive_url": url, "archive": manifest["archive"],
            "sha256": manifest["sha256"], "size_bytes": manifest.get("size_bytes") or 0,
            "revision": manifest["revision"],
        },
        timeout=1800.0,  # 수십 GB 다운로드+전개 대비
    )
    spec.env["VLM_LOCAL_PATH"] = f"/models/{m['name']}"
    yield {
        "phase": "model", "status": "done",
        "detail": f"모델 준비 완료({result.get('status')}) — 오프라인 서빙(/models/{m['name']})",
    }


def _find_kind_manifest(client, kind: str, name: str) -> dict | None:
    """모델 저장소에서 {kind}/{name} 의 manifest 를 찾는다(main 우선) — vlm 외 kind 용."""
    bucket = settings.os_models_bucket
    try:
        resp = client.list_objects_v2(Bucket=bucket, Prefix=f"{kind}/{name}/")
    except ClientError:
        return None
    revisions = sorted({
        key.split("/")[2]
        for obj in resp.get("Contents", [])
        if len((key := obj["Key"]).split("/")) == 4 and key.endswith("manifest.json")
    })
    if not revisions:
        return None
    rev = "main" if "main" in revisions else revisions[0]
    try:
        raw = client.get_object(Bucket=bucket, Key=f"{kind}/{name}/{rev}/manifest.json")["Body"].read()
        manifest = json.loads(raw)
    except (ClientError, ValueError):
        return None
    manifest["revision"] = manifest.get("revision") or rev
    return manifest


async def _install_kind_model(
    client, host: AgentHost, kind: str, volume: str, m: dict, manifest: dict
) -> dict:
    """보유 모델 1개를 에이전트 볼륨에 설치(멱등). agent /model/install 응답을 반환."""
    key = f"{kind}/{m['name']}/{manifest['revision']}/{manifest['archive']}"
    url = await asyncio.to_thread(
        client.generate_presigned_url, "get_object",
        Params={"Bucket": settings.os_models_bucket, "Key": key}, ExpiresIn=3600,
    )
    return await agent_request(
        "POST", host.ip, "/api/v1/model/install",
        json={
            "volume": volume, "subdir": m["name"],
            "archive_url": url, "archive": manifest["archive"],
            "sha256": manifest["sha256"], "size_bytes": manifest.get("size_bytes") or 0,
            "revision": manifest["revision"],
            # 레이아웃은 레지스트리(배포 방식의 결정처)가 우선 — manifest 는 팩
            # 시점 기록이라 구버전 팩이 flat 으로 남아 있을 수 있다.
            "layout": m.get("target") or manifest.get("target") or "hf-cache",
            "repo": manifest.get("repo") or m["repo"],
        },
        timeout=1800.0,
    )


async def prepare_kind_models(spec: DeploySpec, host: AgentHost) -> AsyncIterator[dict]:
    """임베딩/리랭커 배포의 모델 준비 — 선택 모델 필수 설치 또는(미선택) 보유분 pre-warm.

    설계: design/model-registry.md §3.3.

    - 선택(MODEL_NAMES): 레지스트리에서 해석해 각 모델을 볼륨에 설치(pull). 미보유가
      하나라도 있으면 배포 거부(409 + 반입 안내) — 사용자가 명시 선택했으므로 VLM 과
      같은 필수 semantics. ALLOW_ONLINE_MODEL=1 이면 경고 후 온라인(HF) 폴백 허용.
      전부 설치되면 오프라인 서빙(HF 접근 차단)을 빌더에 지시한다.
    - 미선택: 보유분 전부 best-effort pre-warm(설치 실패는 경고) — 서버는 자체 설정의
      기본 모델 세트로 뜨고, 온라인이면 요청 시 다운로드로 폴백한다.

    빌더(동기 문맥)로의 전달은 env 스태시: MODELS_REPOS / DEFAULT_REPO / MODELS_OFFLINE.
    """
    from app.modelreg.service import list_models
    from app.servermgr.service import CONTAINER_KINDS

    kind = spec.kind.value
    volume = CONTAINER_KINDS[kind]["volumes"][0].split(":")[0]
    endpoint = spec.os_endpoint or settings.os_endpoint
    client = _models_client(endpoint)
    registry = [m for m in await list_models(kind) if m["source"] == "hf"]

    if "localhost" in endpoint or "127.0.0.1" in endpoint:
        yield {
            "phase": "model", "status": "running",
            "detail": f"주의: 스토리지 엔드포인트({endpoint})가 localhost — 원격 에이전트는 접근 불가(os_endpoint 지정 필요)",
        }

    selected_names = [n.strip() for n in (spec.env.get("MODEL_NAMES") or "").split(",") if n.strip()]

    # ── 미선택 — 보유분 pre-warm(best-effort), 서버 기본 모델 세트 유지 ──────────
    if not selected_names:
        installed = 0
        for m in registry:
            manifest = await asyncio.to_thread(_find_kind_manifest, client, kind, m["name"])
            if manifest is None:
                continue  # 미보유 — 서버의 온라인 폴백에 맡김(에어갭은 반입 필요)
            yield {"phase": "model", "status": "running",
                   "detail": f"모델 사전 설치: {kind}/{m['name']}@{manifest['revision']}"}
            try:
                result = await _install_kind_model(client, host, kind, volume, m, manifest)
                installed += 1
                yield {"phase": "model", "status": "running",
                       "detail": f"{m['name']} 설치 {result.get('status')}"}
            except DeployError as e:
                yield {"phase": "model", "status": "running",
                       "detail": f"경고: {m['name']} 설치 실패 — {e} (온라인 폴백에 맡김)"}
        yield {"phase": "model", "status": "done",
               "detail": f"모델 사전 설치 완료 — 보유 {installed}개 전개(서빙 세트는 서버 기본값)"}
        return

    # ── 선택 — 레지스트리 해석 → 필수 설치 → 서빙 세트 주입 ─────────────────────
    by_key = {}
    for m in registry:
        by_key[m["name"]] = m
        by_key[m["repo"]] = m
    picked: list[dict] = []
    for n in selected_names:
        m = by_key.get(n)
        if m is None:
            raise DeployError(f"모델 관리에 없는 {kind} 모델입니다: {n}", code=400)
        if m not in picked:
            picked.append(m)

    default_key = (spec.env.get("DEFAULT_MODEL") or "").strip()
    default = by_key.get(default_key) if default_key else picked[0]
    if default is None or default not in picked:
        raise DeployError("기본 모델은 선택한 모델 중 하나여야 합니다.", code=400)

    allow_online = spec.env.get("ALLOW_ONLINE_MODEL") == "1"
    offline = True
    missing: list[str] = []
    for m in picked:
        manifest = await asyncio.to_thread(_find_kind_manifest, client, kind, m["name"])
        if manifest is None:
            missing.append(m["name"])
            continue
        size_mb = (manifest.get("size_bytes") or 0) / 1e6
        yield {"phase": "model", "status": "running",
               "detail": f"모델 설치 중: {kind}/{m['name']}@{manifest['revision']} ({size_mb:.0f} MB)"}
        result = await _install_kind_model(client, host, kind, volume, m, manifest)
        yield {"phase": "model", "status": "running",
               "detail": f"{m['name']} 설치 {result.get('status')}"}

    if missing:
        if not allow_online:
            packs = " / ".join(
                f"`python -m scripts.pack_model --kind {kind} --repo {by_key[n]['repo']} --name {n}`"
                for n in missing
            )
            raise DeployError(
                f"모델 저장소({settings.os_models_bucket})에 없는 모델: {', '.join(missing)}. "
                f"외부망에서 팩해 반입하거나({packs}), "
                "배포 옵션의 '모델 온라인 다운로드 허용'을 켜세요(에어갭 비권장).",
                code=409,
            )
        offline = False
        yield {"phase": "model", "status": "running",
               "detail": f"미보유 {', '.join(missing)} — 온라인(HF 다운로드) 폴백 허용됨"}

    # 빌더(동기)로 전달 — 서버 env(EMBED_*/RERANK_*)는 빌더가 kind 별로 구성한다.
    spec.env["MODELS_REPOS"] = ",".join(m["repo"] for m in picked)
    spec.env["DEFAULT_REPO"] = default["repo"]
    if offline:
        spec.env["MODELS_OFFLINE"] = "1"
    yield {
        "phase": "model", "status": "done",
        "detail": f"모델 준비 완료 — {len(picked)}개 서빙"
        + (" (오프라인)" if offline else " (온라인 폴백 포함)"),
    }
