"""Tests for containermgr service - Docker/Podman lifecycle."""

from unittest.mock import AsyncMock, patch

import pytest

from app.containermgr import service
from app.containermgr.schemas import ContainerSpec

INSPECT_OK = "\t".join(
    [
        "abcdef0123456789",  # Id
        "argus/embedding-server:latest",  # Image
        "running",  # State.Status
        "0",  # ExitCode
        "2026-06-20T01:00:00Z",  # StartedAt
        "embedding",  # argus.kind
        "0.4.2",  # argus.version
        "0",  # RestartCount
        '{"8080/tcp":[{"HostIp":"0.0.0.0","HostPort":"8090"},{"HostIp":"::","HostPort":"8090"}]}',
        '["vllm","serve","Qwen/Qwen2-VL-7B-Instruct","--served-model-name","qwen2-vl-7b"]',
    ]
)


def _spec(**kw) -> ContainerSpec:
    base = dict(
        name="argus-rag-embedding-1",
        image="argus/embedding-server:latest",
        environment={"EMBED_PORT": "8080", "EMBED_DEFAULT_MODEL": "bge-m3"},
        ports=["8080:8080"],
        volumes=["argus-embed-models:/models"],
        gpus="all",
        kind="embedding",
        version="0.4.2",
    )
    base.update(kw)
    return ContainerSpec(**base)


# ---------------------------------------------------------------------------
# validate_name
# ---------------------------------------------------------------------------


def test_validate_name_ok():
    service.validate_name("argus-rag-embedding-1")


def test_validate_name_rejects_missing_prefix():
    with pytest.raises(ValueError, match="must start with"):
        service.validate_name("nginx")


def test_validate_name_rejects_bad_chars():
    with pytest.raises(ValueError, match="invalid container name"):
        service.validate_name("argus-rag-x;rm -rf /")


# ---------------------------------------------------------------------------
# render_run_args (pure)
# ---------------------------------------------------------------------------


def test_render_run_args_core():
    args = service.render_run_args(_spec())
    assert args[0] == "run" and "-d" in args
    assert "--name" in args and "argus-rag-embedding-1" in args
    assert "--restart" in args and "unless-stopped" in args
    # 이미지는 옵션 뒤, command 앞에 위치
    assert args[-1] == "argus/embedding-server:latest"


def test_render_run_args_ports_env_volumes_gpu_labels():
    args = service.render_run_args(_spec(command=["--workers", "2"]))
    joined = " ".join(args)
    assert "-p 8080:8080" in joined
    assert "-e EMBED_PORT=8080" in joined
    assert "-v argus-embed-models:/models" in joined
    assert "--gpus all" in joined
    assert "--label argus.kind=embedding" in joined
    assert "--label argus.version=0.4.2" in joined
    # command 는 이미지 뒤에 온다
    assert args[-3:] == ["argus/embedding-server:latest", "--workers", "2"]


def test_render_ipc_host():
    # vLLM 등 공유메모리 요구 워크로드 — --ipc host. 미지정이면 생략.
    assert "--ipc host" in " ".join(service.render_run_args(_spec(ipc="host")))
    assert "--ipc" not in " ".join(service.render_run_args(_spec()))


def test_render_create_action_no_detach():
    args = service.render_run_args(_spec(), action="create")
    assert args[0] == "create"
    assert "-d" not in args


def test_render_omits_gpu_network_when_unset():
    args = service.render_run_args(_spec(gpus=None, network=None))
    assert "--gpus" not in args
    assert "--network" not in args
    assert "--add-host" not in args


def test_render_network_and_extra_hosts():
    args = service.render_run_args(
        _spec(network="host", extra_hosts=["studio-db:192.0.2.10", "host.docker.internal:host-gateway"])
    )
    joined = " ".join(args)
    assert "--network host" in joined
    assert "--add-host studio-db:192.0.2.10" in joined
    assert "--add-host host.docker.internal:host-gateway" in joined


def test_render_rejects_bad_name():
    with pytest.raises(ValueError, match="must start with"):
        service.render_run_args(_spec(name="evil"))


def test_render_rejects_bad_env_key():
    with pytest.raises(ValueError, match="environment key"):
        service.render_run_args(_spec(environment={"bad key": "v"}))


def test_render_rejects_bad_action():
    with pytest.raises(ValueError, match="invalid action"):
        service.render_run_args(_spec(), action="exec")


# ---------------------------------------------------------------------------
# parsing
# ---------------------------------------------------------------------------


def test_parse_inspect():
    f = service._parse_inspect(INSPECT_OK)
    assert f["image"] == "argus/embedding-server:latest"
    assert f["state"] == "running"
    assert f["kind"] == "embedding"
    assert f["version"] == "0.4.2"


def test_parse_cmd():
    assert service._parse_cmd('["vllm","serve","--x","1"]') == ["vllm", "serve", "--x", "1"]
    assert service._parse_cmd("null") == []
    assert service._parse_cmd("") == []
    assert service._parse_cmd("깨진") == []


def test_parse_ports_dedups_dual_stack_and_skips_unexposed():
    raw = ('{"8080/tcp":[{"HostIp":"0.0.0.0","HostPort":"8090"},{"HostIp":"::","HostPort":"8090"}],'
           '"9090/tcp":null}')
    assert service._parse_ports(raw) == ["8090:8080"]
    assert service._parse_ports("null") == []
    assert service._parse_ports("") == []
    assert service._parse_ports("깨진 json") == []


def test_clean_handles_no_value():
    assert service._clean("<no value>") is None
    assert service._clean("") is None
    assert service._clean(" x ") == "x"


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


async def test_status_running():
    with patch.object(service, "_run", new_callable=AsyncMock) as run:
        run.return_value = (0, INSPECT_OK, "")
        st = await service.status("argus-rag-embedding-1")
    assert st.exists is True
    assert st.state == "running"
    assert st.image == "argus/embedding-server:latest"
    assert st.kind == "embedding"
    assert st.version == "0.4.2"
    assert st.exit_code == 0


async def test_status_not_found():
    with patch.object(service, "_run", new_callable=AsyncMock) as run:
        run.return_value = (1, "", "Error: No such object: argus-rag-x")
        st = await service.status("argus-rag-x")
    assert st.exists is False


# ---------------------------------------------------------------------------
# create_or_run
# ---------------------------------------------------------------------------


async def test_create_or_run_pull_replace_run():
    with patch.object(service, "_run", new_callable=AsyncMock) as run:
        run.return_value = (0, INSPECT_OK, "")
        st = await service.create_or_run(_spec())

    calls = [c.args[0] for c in run.call_args_list]
    assert ["pull", "argus/embedding-server:latest"] in calls
    assert ["rm", "-f", "argus-rag-embedding-1"] in calls
    assert any(c[0] == "run" for c in calls)
    assert st.exists is True


async def test_create_no_start_uses_create():
    with patch.object(service, "_run", new_callable=AsyncMock) as run:
        run.return_value = (0, INSPECT_OK, "")
        await service.create_or_run(_spec(start=False, pull=False))
    calls = [c.args[0] for c in run.call_args_list]
    assert not any(c[0] == "pull" for c in calls)
    assert any(c[0] == "create" for c in calls)
    assert not any(c[0] == "run" for c in calls)


async def test_create_invalid_spec_raises():
    with pytest.raises(ValueError):
        await service.create_or_run(_spec(name="evil"))


async def test_create_run_failure_sets_message():
    async def fake(args):
        if args[0] in ("run", "create"):
            return (125, "", "docker: image not found")
        return (0, "", "")

    with patch.object(service, "_run", side_effect=fake):
        st = await service.create_or_run(_spec(pull=False))
    assert st.exists is False
    assert "image not found" in st.message


# ---------------------------------------------------------------------------
# start / stop / restart / remove / list
# ---------------------------------------------------------------------------


async def test_start_success():
    with patch.object(service, "_run", new_callable=AsyncMock) as run:
        run.side_effect = [(0, "", ""), (0, INSPECT_OK, "")]
        st = await service.start("argus-rag-embedding-1")
    assert st.state == "running"
    assert st.message == ""


async def test_remove_success():
    with patch.object(service, "_run", new_callable=AsyncMock) as run:
        run.return_value = (0, "", "")
        result = await service.remove("argus-rag-embedding-1")
    assert result.success is True
    assert run.call_args.args[0] == ["rm", "-f", "argus-rag-embedding-1"]


async def test_remove_failure():
    with patch.object(service, "_run", new_callable=AsyncMock) as run:
        run.return_value = (1, "", "no such container")
        result = await service.remove("argus-rag-embedding-1")
    assert result.success is False


async def test_list_managed_filters_prefix():
    async def fake(args):
        if args[0] == "ps":
            return (0, "argus-rag-embedding-1\nargus-rag-reranker-1", "")
        return (0, INSPECT_OK, "")

    with patch.object(service, "_run", side_effect=fake):
        items = await service.list_managed()
    assert [i.name for i in items] == ["argus-rag-embedding-1", "argus-rag-reranker-1"]


async def test_list_managed_empty():
    with patch.object(service, "_run", new_callable=AsyncMock) as run:
        run.return_value = (0, "", "")
        assert await service.list_managed() == []
