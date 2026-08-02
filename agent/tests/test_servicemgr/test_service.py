"""Tests for servicemgr service - systemd unit lifecycle."""

from unittest.mock import AsyncMock, patch

import pytest

from app.servicemgr import service
from app.servicemgr.schemas import ServiceSpec

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SHOW_OUTPUT = "\n".join(
    [
        "LoadState=loaded",
        "ActiveState=active",
        "SubState=running",
        "UnitFileState=enabled",
        "MainPID=12345",
        "ExecMainStatus=0",
        "MemoryCurrent=10485760",
        "ActiveEnterTimestamp=Thu 2026-06-19 10:00:00 UTC",
    ]
)


@pytest.fixture
def systemd_dir(tmp_path, monkeypatch):
    """Redirect SYSTEMD_DIR to a temp directory."""
    monkeypatch.setattr(service, "SYSTEMD_DIR", tmp_path)
    return tmp_path


def _spec(**kw) -> ServiceSpec:
    base = dict(
        name="argus-rag-worker-1",
        description="Argus RAG worker #1",
        exec_start="/opt/venv/bin/python -m app.worker_main",
        working_directory="/opt/argus-rag/backend",
        user="argus",
        environment={"ARGUS_DB_URL": "postgresql://x", "ARGUS_WORKER": "true"},
        kind="worker",
        version="0.4.2",
    )
    base.update(kw)
    return ServiceSpec(**base)


# ---------------------------------------------------------------------------
# validate_name
# ---------------------------------------------------------------------------


def test_validate_name_ok():
    service.validate_name("argus-rag-worker-1")


def test_validate_name_rejects_missing_prefix():
    with pytest.raises(ValueError, match="must start with"):
        service.validate_name("nginx")


def test_validate_name_rejects_path_traversal():
    with pytest.raises(ValueError, match="invalid unit name"):
        service.validate_name("argus-rag-worker-../../etc/passwd")


def test_validate_name_rejects_space_injection():
    with pytest.raises(ValueError, match="invalid unit name"):
        service.validate_name("argus-rag-worker-x; rm -rf /")


def test_validate_name_rejects_agent_self_unit():
    # 에이전트 자신(argus-rag-studio-agent)은 worker 접두사가 아니라 관리 대상에서 제외된다.
    with pytest.raises(ValueError, match="must start with"):
        service.validate_name("argus-rag-studio-agent")


# ---------------------------------------------------------------------------
# render_unit
# ---------------------------------------------------------------------------


def test_render_unit_contains_core_directives():
    text = service.render_unit(_spec())
    assert "[Unit]" in text and "[Service]" in text and "[Install]" in text
    assert "Description=Argus RAG worker #1" in text
    assert "ExecStart=/opt/venv/bin/python -m app.worker_main" in text
    assert "WorkingDirectory=/opt/argus-rag/backend" in text
    assert "User=argus" in text
    assert "Restart=on-failure" in text
    assert "RestartSec=5" in text
    assert "WantedBy=multi-user.target" in text


def test_render_unit_includes_metadata_comments():
    text = service.render_unit(_spec())
    assert "# X-Argus-Kind=worker" in text
    assert "# X-Argus-Version=0.4.2" in text


def test_render_unit_environment_entries():
    text = service.render_unit(_spec())
    assert 'Environment="ARGUS_DB_URL=postgresql://x"' in text
    assert 'Environment="ARGUS_WORKER=true"' in text


def test_render_unit_escapes_quotes_in_env():
    text = service.render_unit(_spec(environment={"K": 'a"b\\c'}))
    assert 'Environment="K=a\\"b\\\\c"' in text


def test_render_unit_omits_optional_fields_when_none():
    text = service.render_unit(
        _spec(user=None, group=None, working_directory=None, limit_nofile=None, version=None)
    )
    assert "User=" not in text
    assert "Group=" not in text
    assert "WorkingDirectory=" not in text
    assert "LimitNOFILE=" not in text
    assert "X-Argus-Version" not in text


def test_render_unit_includes_limit_nofile_when_set():
    text = service.render_unit(_spec(limit_nofile=65536))
    assert "LimitNOFILE=65536" in text


def test_render_unit_rejects_newline_in_exec_start():
    with pytest.raises(ValueError, match="exec_start"):
        service.render_unit(_spec(exec_start="foo\nExecStartPre=/bin/evil"))


def test_render_unit_rejects_newline_in_env_value():
    with pytest.raises(ValueError, match="environment"):
        service.render_unit(_spec(environment={"K": "v\nRestart=always"}))


def test_render_unit_rejects_bad_env_key():
    with pytest.raises(ValueError, match="environment key"):
        service.render_unit(_spec(environment={"bad key": "v"}))


def test_render_unit_rejects_bad_name():
    with pytest.raises(ValueError, match="must start with"):
        service.render_unit(_spec(name="evil"))


# ---------------------------------------------------------------------------
# parsing helpers
# ---------------------------------------------------------------------------


def test_parse_show():
    parsed = service._parse_show(SHOW_OUTPUT)
    assert parsed["ActiveState"] == "active"
    assert parsed["MainPID"] == "12345"


def test_int_or_none():
    assert service._int_or_none("12345") == 12345
    assert service._int_or_none("0") is None
    assert service._int_or_none("[not set]") is None
    assert service._int_or_none(None) is None
    assert service._int_or_none("") is None


def test_read_metadata(systemd_dir):
    (systemd_dir / "argus-rag-worker-1.service").write_text(
        "# X-Argus-Kind=embedding\n# X-Argus-Version=1.2.3\n[Unit]\n"
    )
    kind, version = service._read_metadata("argus-rag-worker-1")
    assert kind == "embedding"
    assert version == "1.2.3"


def test_read_metadata_missing_file(systemd_dir):
    assert service._read_metadata("argus-rag-nope") == (None, None)


# ---------------------------------------------------------------------------
# unit_exists
# ---------------------------------------------------------------------------


def test_unit_exists(systemd_dir):
    assert service.unit_exists("argus-rag-worker-1") is False
    (systemd_dir / "argus-rag-worker-1.service").write_text("x")
    assert service.unit_exists("argus-rag-worker-1") is True


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


async def test_status_parses_systemctl_show(systemd_dir):
    (systemd_dir / "argus-rag-worker-1.service").write_text(
        "# X-Argus-Kind=worker\n# X-Argus-Version=0.4.2\n"
    )
    with patch.object(service, "_run", new_callable=AsyncMock) as run:
        run.return_value = (0, SHOW_OUTPUT, "")
        st = await service.status("argus-rag-worker-1")

    assert st.exists is True
    assert st.load_state == "loaded"
    assert st.active_state == "active"
    assert st.sub_state == "running"
    assert st.enabled is True
    assert st.pid == 12345
    assert st.memory_bytes == 10485760
    assert st.exit_code == 0
    assert st.kind == "worker"
    assert st.version == "0.4.2"


async def test_status_disabled_mapping(systemd_dir):
    (systemd_dir / "argus-rag-worker-1.service").write_text("x")
    with patch.object(service, "_run", new_callable=AsyncMock) as run:
        run.return_value = (0, "UnitFileState=disabled\nActiveState=inactive", "")
        st = await service.status("argus-rag-worker-1")
    assert st.enabled is False
    assert st.active_state == "inactive"


async def test_status_systemctl_failure_sets_message():
    with patch.object(service, "_run", new_callable=AsyncMock) as run:
        run.return_value = (1, "", "Failed to connect to bus")
        st = await service.status("argus-rag-worker-1")
    assert st.message == "Failed to connect to bus"


# ---------------------------------------------------------------------------
# create_or_update
# ---------------------------------------------------------------------------


async def test_create_or_update_writes_file_and_reloads(systemd_dir):
    with patch.object(service, "_run", new_callable=AsyncMock) as run:
        run.return_value = (0, SHOW_OUTPUT, "")
        st = await service.create_or_update(_spec())

    unit = systemd_dir / "argus-rag-worker-1.service"
    assert unit.is_file()
    assert "ExecStart=" in unit.read_text()

    calls = [c.args[0] for c in run.call_args_list]
    assert "systemctl daemon-reload" in calls
    assert "systemctl enable argus-rag-worker-1" in calls
    assert "systemctl restart argus-rag-worker-1" in calls
    assert st.name == "argus-rag-worker-1"


async def test_create_or_update_no_enable_no_start(systemd_dir):
    with patch.object(service, "_run", new_callable=AsyncMock) as run:
        run.return_value = (0, SHOW_OUTPUT, "")
        await service.create_or_update(_spec(enable=False, start=False))

    calls = [c.args[0] for c in run.call_args_list]
    assert "systemctl daemon-reload" in calls
    assert not any("enable" in c for c in calls)
    assert not any("restart" in c for c in calls)


async def test_create_or_update_invalid_spec_raises(systemd_dir):
    with pytest.raises(ValueError):
        await service.create_or_update(_spec(exec_start="a\nb"))
    # 잘못된 스펙은 파일을 남기지 않는다.
    assert not (systemd_dir / "argus-rag-worker-1.service").exists()


# ---------------------------------------------------------------------------
# start / stop / restart
# ---------------------------------------------------------------------------


async def test_start_success(systemd_dir):
    (systemd_dir / "argus-rag-worker-1.service").write_text("x")
    with patch.object(service, "_run", new_callable=AsyncMock) as run:
        run.side_effect = [(0, "", ""), (0, SHOW_OUTPUT, "")]
        st = await service.start("argus-rag-worker-1")
    assert st.active_state == "active"
    assert st.message == ""


async def test_stop_failure_sets_message(systemd_dir):
    (systemd_dir / "argus-rag-worker-1.service").write_text("x")
    with patch.object(service, "_run", new_callable=AsyncMock) as run:
        run.side_effect = [(1, "", "stop boom"), (0, SHOW_OUTPUT, "")]
        st = await service.stop("argus-rag-worker-1")
    assert st.message == "stop boom"


# ---------------------------------------------------------------------------
# set_enabled
# ---------------------------------------------------------------------------


async def test_set_enabled_true():
    with patch.object(service, "_run", new_callable=AsyncMock) as run:
        run.return_value = (0, "", "")
        result = await service.set_enabled("argus-rag-worker-1", True)
    assert result.success is True
    assert run.call_args.args[0] == "systemctl enable argus-rag-worker-1"


async def test_set_enabled_false_failure():
    with patch.object(service, "_run", new_callable=AsyncMock) as run:
        run.return_value = (1, "", "disable boom")
        result = await service.set_enabled("argus-rag-worker-1", False)
    assert result.success is False
    assert "disable boom" in result.message


# ---------------------------------------------------------------------------
# remove
# ---------------------------------------------------------------------------


async def test_remove_success(systemd_dir):
    unit = systemd_dir / "argus-rag-worker-1.service"
    unit.write_text("x")
    with patch.object(service, "_run", new_callable=AsyncMock) as run:
        run.return_value = (0, "", "")
        result = await service.remove("argus-rag-worker-1")
    assert result.success is True
    assert not unit.exists()
    calls = [c.args[0] for c in run.call_args_list]
    assert "systemctl stop argus-rag-worker-1" in calls
    assert "systemctl disable argus-rag-worker-1" in calls
    assert "systemctl daemon-reload" in calls


async def test_remove_missing_file(systemd_dir):
    result = await service.remove("argus-rag-worker-1")
    assert result.success is False
    assert "not found" in result.message


# ---------------------------------------------------------------------------
# list_managed
# ---------------------------------------------------------------------------


async def test_list_managed_only_managed_units(systemd_dir):
    (systemd_dir / "argus-rag-worker-1.service").write_text("# X-Argus-Kind=worker\n")
    (systemd_dir / "argus-rag-worker-2.service").write_text("# X-Argus-Kind=worker\n")
    (systemd_dir / "nginx.service").write_text("x")  # 비관리 서비스
    with patch.object(service, "_run", new_callable=AsyncMock) as run:
        run.return_value = (0, SHOW_OUTPUT, "")
        items = await service.list_managed()

    names = [i.name for i in items]
    assert names == ["argus-rag-worker-1", "argus-rag-worker-2"]


async def test_list_managed_empty_when_dir_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "SYSTEMD_DIR", tmp_path / "nonexistent")
    assert await service.list_managed() == []
