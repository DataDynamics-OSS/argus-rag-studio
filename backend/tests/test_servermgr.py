# SPDX-License-Identifier: Apache-2.0
"""servermgr 워커/컨테이너 배포 순수 로직 테스트 (슬롯·spec 빌드·이미지·설정 주입)."""

import pytest

from app.servermgr import service
from app.servermgr.schemas import DeployContainerRequest, DeployWorkerRequest


def test_next_worker_slots_empty():
    assert service.next_worker_slots([], 2) == [
        "argus-rag-worker-1",
        "argus-rag-worker-2",
    ]


def test_next_worker_slots_continues_from_max():
    existing = ["argus-rag-worker-1", "argus-rag-worker-3"]
    assert service.next_worker_slots(existing, 2) == [
        "argus-rag-worker-4",
        "argus-rag-worker-5",
    ]


def test_next_worker_slots_ignores_non_worker_units():
    existing = ["argus-rag-embedding-1", "nginx", "argus-rag-worker-2"]
    assert service.next_worker_slots(existing, 1) == ["argus-rag-worker-3"]


def test_next_worker_slots_zero():
    assert service.next_worker_slots(["argus-rag-worker-1"], 0) == []


def test_build_worker_spec_basics():
    req = DeployWorkerRequest(
        working_directory="/opt/argus-rag-studio/backend",
        python_path="/opt/venv/bin/python",
        user="argus",
        version="0.4.2",
    )
    spec = service.build_worker_spec("argus-rag-worker-1", req)
    assert spec["name"] == "argus-rag-worker-1"
    assert spec["exec_start"] == "/opt/venv/bin/python -m app.worker_main"
    assert spec["working_directory"] == "/opt/argus-rag-studio/backend"
    assert spec["user"] == "argus"
    assert spec["kind"] == "worker"
    assert spec["version"] == "0.4.2"
    assert spec["enable"] is True and spec["start"] is True
    # 슬롯별 로그 파일 주입(다중 워커 로그 충돌 방지).
    assert spec["environment"]["ARGUS_LOG_FILENAME"] == "argus-rag-worker-1.log"


def test_build_worker_spec_env_merge_and_override():
    req = DeployWorkerRequest(
        working_directory="/opt/x",
        environment={"ARGUS_EMBEDDING_MODEL": "custom-model", "EXTRA": "1"},
    )
    env = service.build_worker_spec("argus-rag-worker-1", req)["environment"]
    assert env["ARGUS_INGESTION_LOCAL_WORKER_ENABLED"] == "true"
    assert "ARGUS_DB_URL" in env
    assert env["ARGUS_EMBEDDING_MODEL"] == "custom-model"  # 요청이 기본값을 덮어씀
    assert env["EXTRA"] == "1"


def test_default_worker_env_has_required_keys():
    env = service.default_worker_env()
    assert env["ARGUS_INGESTION_LOCAL_WORKER_ENABLED"] == "true"
    assert env["ARGUS_DB_URL"].startswith(("postgresql", "mysql"))
    # 원격 워커가 원본 문서를 읽으려면 오브젝트 스토리지 연결정보가 필수.
    for k in ("ARGUS_OS_ENDPOINT", "ARGUS_OS_ACCESS_KEY", "ARGUS_OS_SECRET_KEY", "ARGUS_OS_BUCKET"):
        assert k in env


def test_os_endpoint_override_in_worker_env():
    env = service.default_worker_env(os_endpoint="http://192.0.2.10:9000")
    assert env["ARGUS_OS_ENDPOINT"] == "http://192.0.2.10:9000"


# ---------------------------------------------------------------------------
# Docker 컨테이너 배포 — 카탈로그/슬롯/spec 빌더/설정 주입
# ---------------------------------------------------------------------------


def test_container_prefix():
    assert service.container_prefix("worker") == "argus-rag-worker-"
    assert service.container_prefix("embedding") == "argus-rag-embedding-"
    assert service.container_prefix("hwp_render") == "argus-rag-hwp-render-"


def test_next_slots_generic():
    assert service.next_slots("argus-rag-embedding-", [], 1) == ["argus-rag-embedding-1"]
    assert service.next_slots(
        "argus-rag-worker-", ["argus-rag-worker-2", "argus-rag-embedding-1"], 2
    ) == ["argus-rag-worker-3", "argus-rag-worker-4"]


def test_image_for_default_and_registry(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "deploy_image_registry", "", raising=False)
    monkeypatch.setattr(settings, "deploy_image_tag", "latest", raising=False)
    assert service.image_for("embedding") == "argus-rag-studio-embedding-server:latest"

    monkeypatch.setattr(settings, "deploy_image_registry", "reg.local:5000", raising=False)
    monkeypatch.setattr(settings, "deploy_image_tag", "1.2.3", raising=False)
    assert (
        service.image_for("reranker")
        == "reg.local:5000/argus-rag-studio-reranker-server:1.2.3"
    )
    # override 우선
    assert service.image_for("embedding", override="custom/img:dev") == "custom/img:dev"


def test_build_container_spec_embedding():
    req = DeployContainerRequest(kind="embedding", gpus="all", version="0.4.2")
    spec = service.build_container_spec("embedding", "argus-rag-embedding-1", req)
    assert spec["name"] == "argus-rag-embedding-1"
    assert spec["ports"] == ["8080:8080"]
    assert spec["environment"]["EMBED_PORT"] == "8080"
    assert spec["volumes"] == ["argus-rag-embed-models:/models"]
    assert spec["gpus"] == "all"
    assert spec["kind"] == "embedding" and spec["version"] == "0.4.2"


def test_build_container_spec_host_port_override():
    # 호스트 포트 오버라이드 — 기본 포트 점유 시(예: DGX 8080=node). 내부 포트는 유지.
    req = DeployContainerRequest(kind="embedding", host_port=8090)
    spec = service.build_container_spec("embedding", "argus-rag-embedding-1", req)
    assert spec["ports"] == ["8090:8080"]
    assert spec["environment"]["EMBED_PORT"] == "8080"  # 컨테이너 내부는 kind 기본
    assert service.setting_injection("embedding", "192.0.2.48", 8090) == (
        "embedding.server_url", "http://192.0.2.48:8090/v1"
    )
    # 미지정이면 기존과 동일
    assert service.setting_injection("embedding", "192.0.2.48", None) == (
        "embedding.server_url", "http://192.0.2.48:8080/v1"
    )


def test_build_container_spec_vlm_arm64_uses_ngc_image_and_serve_prefix():
    """vlm × arm64 — 공식 이미지(x86 전용) 대신 NGC 자동 선택 + 'vllm serve' 커맨드 prefix."""
    env = {"VLM_MODEL": "qwen2-vl-7b", "VLM_REPO": "Qwen/Qwen2-VL-7B-Instruct", "VLM_MAX_LEN": "8192"}
    req = DeployContainerRequest(kind="vlm", gpus="all", environment=dict(env))
    spec = service.build_container_spec("vlm", "argus-rag-vlm-1", req, arch="arm64", gpu_count=1)
    assert spec["image"] == "nvcr.io/nvidia/vllm:26.02-py3"  # 설정 기본값 — registry/tag 규약 미적용
    assert spec["command"][:2] == ["vllm", "serve"]
    assert "--served-model-name" in spec["command"] and "qwen2-vl-7b" in spec["command"]

    # amd64 — 기존 그대로(공식 이미지 + entrypoint 가 vllm serve 라 인자만)
    req = DeployContainerRequest(kind="vlm", gpus="all", environment=dict(env))
    spec = service.build_container_spec("vlm", "argus-rag-vlm-1", req, arch="amd64", gpu_count=1)
    assert spec["image"].startswith("vllm/vllm-openai")
    assert spec["command"][0] == "Qwen/Qwen2-VL-7B-Instruct"

    # VLLM_ARGS(전체 지정) — 이미 vllm serve 포함이면 중복 prefix 없음, 이미지 override 우선
    req = DeployContainerRequest(
        kind="vlm", gpus="all", image="reg.local/nvidia/vllm:26.02",
        environment={"VLLM_ARGS": "vllm serve Qwen/Qwen2-VL-7B-Instruct --served-model-name x"},
    )
    spec = service.build_container_spec("vlm", "argus-rag-vlm-1", req, arch="arm64", gpu_count=1)
    assert spec["image"] == "reg.local/nvidia/vllm:26.02"
    assert spec["command"][:2] == ["vllm", "serve"] and spec["command"].count("vllm") == 1


def test_build_container_spec_hwp_node():
    req = DeployContainerRequest(kind="hwp_render")
    spec = service.build_container_spec("hwp_render", "argus-rag-hwp-render-1", req)
    assert spec["ports"] == ["8085:8085"]
    assert spec["environment"]["HWP_RENDER_PORT"] == "8085"
    assert spec["volumes"] == []
    assert spec["gpus"] is None


def test_build_container_spec_worker_runs_worker_main():
    # 워커 컨테이너는 공용 이미지를 worker_main 으로 실행(기본 CMD=uvicorn app.main 대신).
    req = DeployContainerRequest(kind="worker")
    spec = service.build_container_spec("worker", "argus-rag-worker-1", req)
    assert spec["command"] == ["python", "-m", "app.worker_main"]
    # 서버형은 command override 없음(이미지 기본 CMD 사용).
    emb = service.build_container_spec("embedding", "argus-rag-embedding-1", DeployContainerRequest(kind="embedding"))
    assert emb["command"] == []


def test_build_container_spec_worker_has_db_env():
    req = DeployContainerRequest(kind="worker", environment={"X": "1"})
    spec = service.build_container_spec("worker", "argus-rag-worker-1", req)
    assert spec["ports"] == []
    assert spec["environment"]["ARGUS_INGESTION_LOCAL_WORKER_ENABLED"] == "true"
    assert spec["environment"]["X"] == "1"
    assert spec["environment"]["ARGUS_LOG_FILENAME"] == "argus-rag-worker-1.log"
    # 기본은 네트워크 미지정(bridge)
    assert spec["network"] is None
    assert spec["extra_hosts"] == []


def test_build_container_spec_networking_options():
    req = DeployContainerRequest(
        kind="worker",
        network="host",
        extra_hosts=["studio-db:192.0.2.10"],
        db_url="postgresql+asyncpg://argus:pw@192.0.2.10:5432/argus",
    )
    spec = service.build_container_spec("worker", "argus-rag-worker-1", req)
    assert spec["network"] == "host"
    assert spec["extra_hosts"] == ["studio-db:192.0.2.10"]
    # db_url override 가 ARGUS_DB_URL 에 반영
    assert spec["environment"]["ARGUS_DB_URL"] == "postgresql+asyncpg://argus:pw@192.0.2.10:5432/argus"


def test_db_url_override_only_affects_worker_env():
    # 서버형(embedding)은 ARGUS_DB_URL 을 쓰지 않음 → db_url 무시, network 는 전달
    req = DeployContainerRequest(kind="embedding", network="host", db_url="postgresql://x")
    spec = service.build_container_spec("embedding", "argus-rag-embedding-1", req)
    assert spec["network"] == "host"
    assert "ARGUS_DB_URL" not in spec["environment"]


def test_build_container_spec_unknown_kind():
    req = DeployContainerRequest(kind="embedding")
    with pytest.raises(ValueError, match="unknown kind"):
        service.build_container_spec("nope", "argus-rag-nope-1", req)


def test_setting_injection():
    assert service.setting_injection("embedding", "192.0.2.50") == (
        "embedding.server_url",
        "http://192.0.2.50:8080/v1",
    )
    assert service.setting_injection("reranker", "192.0.2.50") == (
        "rerank.server_url",
        "http://192.0.2.50:8081/rerank",
    )
    assert service.setting_injection("detection", "192.0.2.50") == (
        "detection.server_url",
        "http://192.0.2.50:8082",
    )
    assert service.setting_injection("hwp_render", "192.0.2.50") == (
        "hwp_render.url",
        "http://192.0.2.50:8085",
    )
    # worker 는 주입 설정 없음
    assert service.setting_injection("worker", "192.0.2.50") is None


# ---------------------------------------------------------------------------
# 변형(variant) 선택 — resolve_variant / image_for(variant)
# ---------------------------------------------------------------------------


def _req(**kw):
    base = dict(kind=kw.pop("kind", "embedding"))
    base.update(kw)
    return DeployContainerRequest(**base)


def test_resolve_variant_auto_amd64_gpu():
    r = service.resolve_variant("embedding", _req(), arch="amd64", gpu_count=1)
    assert r == "gpu"


def test_resolve_variant_auto_arm64_gputorch():
    r = service.resolve_variant("embedding", _req(), arch="arm64", gpu_count=1)
    assert r == "gpu-torch"


def test_resolve_variant_detection_arm64_is_gpu():
    # detection 은 arm64 도 gpu(torch)
    assert service.resolve_variant("detection", _req(kind="detection"), arch="arm64", gpu_count=2) == "gpu"


def test_resolve_variant_auto_no_gpu_is_cpu():
    assert service.resolve_variant("embedding", _req(), arch="amd64", gpu_count=0) == ""


def test_resolve_variant_gpus_signal_triggers_gpu():
    # variant auto + gpus 지정 → GPU (gpu_count 미보고여도)
    assert service.resolve_variant("embedding", _req(gpus="all"), arch="amd64", gpu_count=None) == "gpu"


def test_resolve_variant_explicit_cpu():
    assert service.resolve_variant("embedding", _req(variant="cpu"), arch="arm64", gpu_count=1) == ""


def test_resolve_variant_explicit_gputorch():
    assert service.resolve_variant("embedding", _req(variant="gpu-torch"), arch="amd64", gpu_count=1) == "gpu-torch"


def test_resolve_variant_arch_unknown_defaults_amd64():
    assert service.resolve_variant("embedding", _req(gpus="all"), arch=None, gpu_count=1) == "gpu"


def test_resolve_variant_worker_gpu_unsupported():
    with pytest.raises(service.VariantError, match="지원하지 않"):
        service.resolve_variant("worker", _req(kind="worker", variant="gpu"), arch="amd64", gpu_count=1)


def test_resolve_variant_kind_missing_variant():
    # detection 은 gpu-torch 변형이 없음
    with pytest.raises(service.VariantError, match="변형이 없"):
        service.resolve_variant("detection", _req(kind="detection", variant="gpu-torch"), arch="arm64", gpu_count=1)


def test_image_for_variant_suffix(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "deploy_image_registry", "", raising=False)
    monkeypatch.setattr(settings, "deploy_image_tag", "0.4.2", raising=False)
    assert service.image_for("embedding") == "argus-rag-studio-embedding-server:0.4.2"
    assert service.image_for("embedding", "gpu") == "argus-rag-studio-embedding-server:0.4.2-gpu"
    assert (
        service.image_for("embedding", "gpu-torch")
        == "argus-rag-studio-embedding-server:0.4.2-gpu-torch"
    )


def test_build_container_spec_picks_gpu_image():
    spec = service.build_container_spec(
        "embedding", "argus-rag-embedding-1", _req(), arch="arm64", gpu_count=1
    )
    assert spec["image"].endswith("-gpu-torch")
    assert spec["gpus"] == "all"
    assert spec["labels"]["argus.variant"] == "gpu-torch"


def test_build_container_spec_cpu_when_no_gpu():
    spec = service.build_container_spec(
        "embedding", "argus-rag-embedding-1", _req(), arch="amd64", gpu_count=0
    )
    assert "-gpu" not in spec["image"]
    assert spec["gpus"] is None
    assert spec["labels"]["argus.variant"] == "cpu"


def test_build_container_spec_embedding_model_selection():
    # 모델 준비 단계(prepare_kind_models)의 스태시 → 서버 env(EMBED_*) 변환.
    req = DeployContainerRequest(kind="embedding", environment={
        "MODEL_NAMES": "bge-m3,e5", "DEFAULT_MODEL": "e5",  # 오케스트레이션 입력(제거돼야 함)
        "MODELS_REPOS": "BAAI/bge-m3,intfloat/multilingual-e5-large",
        "DEFAULT_REPO": "intfloat/multilingual-e5-large",
        "MODELS_OFFLINE": "1",
    })
    spec = service.build_container_spec("embedding", "argus-rag-embedding-1", req)
    env = spec["environment"]
    assert env["EMBED_MODELS"] == "BAAI/bge-m3,intfloat/multilingual-e5-large"
    assert env["EMBED_DEFAULT_MODEL"] == "intfloat/multilingual-e5-large"
    assert env["EMBED_CACHE_DIR"] == "/models"  # 카탈로그 기본 — 볼륨 캐시 사용
    assert env["HF_HUB_OFFLINE"] == "1" and env["TRANSFORMERS_OFFLINE"] == "1"
    # 오케스트레이션 키는 컨테이너로 전달되지 않는다.
    for k in ("MODEL_NAMES", "DEFAULT_MODEL", "MODELS_REPOS", "DEFAULT_REPO", "MODELS_OFFLINE"):
        assert k not in env


def test_build_container_spec_reranker_model_selection_online():
    # 온라인 폴백 포함(offline 스태시 없음) — HF 차단 env 를 넣지 않는다.
    req = DeployContainerRequest(kind="reranker", environment={
        "MODELS_REPOS": "BAAI/bge-reranker-v2-m3",
        "DEFAULT_REPO": "BAAI/bge-reranker-v2-m3",
    })
    spec = service.build_container_spec("reranker", "argus-rag-reranker-1", req)
    env = spec["environment"]
    assert env["RERANK_MODELS"] == "BAAI/bge-reranker-v2-m3"
    assert env["RERANK_DEFAULT_MODEL"] == "BAAI/bge-reranker-v2-m3"
    assert env["RERANK_CACHE_DIR"] == "/models"
    assert "HF_HUB_OFFLINE" not in env


def test_build_container_spec_embedding_no_selection_keeps_defaults():
    # 미선택 — 서버 자체 설정의 기본 모델 세트 유지(EMBED_MODELS 미주입), 캐시만 볼륨으로.
    spec = service.build_container_spec(
        "embedding", "argus-rag-embedding-1", DeployContainerRequest(kind="embedding")
    )
    env = spec["environment"]
    assert "EMBED_MODELS" not in env and "EMBED_DEFAULT_MODEL" not in env
    assert env["EMBED_CACHE_DIR"] == "/models"
