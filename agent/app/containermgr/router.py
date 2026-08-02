"""Container management API routes (Docker/Podman)."""

import json

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.containermgr import service
from app.containermgr.schemas import (
    MANAGED_PREFIX,
    ContainerLogs,
    ContainerSpec,
    ContainerStatus,
    OperationResult,
)

router = APIRouter(prefix="/container", tags=["container"])


@router.post("/stream")
async def create_stream(spec: ContainerSpec) -> StreamingResponse:
    """create_or_run 의 NDJSON 스트림 버전 — pull 레이어 진행 + run 결과를 줄단위 이벤트로."""
    if not spec.name.startswith(MANAGED_PREFIX):
        raise HTTPException(
            status_code=403, detail=f"managed container must start with '{MANAGED_PREFIX}'"
        )

    async def gen():
        try:
            async for ev in service.create_or_run_stream(spec):
                yield json.dumps(ev, ensure_ascii=False) + "\n"
        except ValueError as e:
            yield json.dumps({"phase": "error", "status": "error", "detail": str(e)}) + "\n"
        except Exception as e:  # noqa: BLE001 — 스트림은 에러 이벤트로 전달
            yield json.dumps({"phase": "error", "status": "error", "detail": str(e)}) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")


def _guard(name: str) -> None:
    """Reject non-managed container names early (403)."""
    if not name.startswith(MANAGED_PREFIX):
        raise HTTPException(
            status_code=403, detail=f"managed container must start with '{MANAGED_PREFIX}'"
        )


async def _require_exists(name: str) -> ContainerStatus:
    """Raise 404 if the container does not exist; otherwise return its status."""
    st = await service.status(name)
    if not st.exists:
        raise HTTPException(status_code=404, detail=f"container not found: {name}")
    return st


@router.post("", response_model=ContainerStatus)
async def create(spec: ContainerSpec) -> ContainerStatus:
    """Create/run a managed container (pull + replace same-name + run/create)."""
    _guard(spec.name)
    try:
        return await service.create_or_run(spec)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/{name}/start", response_model=ContainerStatus)
async def start(name: str) -> ContainerStatus:
    """Start a managed container."""
    _guard(name)
    await _require_exists(name)
    return await service.start(name)


@router.post("/{name}/stop", response_model=ContainerStatus)
async def stop(name: str) -> ContainerStatus:
    """Stop a managed container."""
    _guard(name)
    await _require_exists(name)
    return await service.stop(name)


@router.post("/{name}/restart", response_model=ContainerStatus)
async def restart(name: str) -> ContainerStatus:
    """Restart a managed container."""
    _guard(name)
    await _require_exists(name)
    return await service.restart(name)


@router.get("/{name}", response_model=ContainerStatus)
async def get_status(name: str) -> ContainerStatus:
    """Query a managed container's status."""
    _guard(name)
    return await _require_exists(name)


@router.get("", response_model=list[ContainerStatus])
async def list_containers() -> list[ContainerStatus]:
    """List all containermgr-managed containers."""
    return await service.list_managed()


@router.get("/{name}/logs", response_model=ContainerLogs)
async def container_logs(name: str, tail: int = Query(200, ge=1, le=5000)) -> ContainerLogs:
    """Return the last N lines of a container's logs."""
    _guard(name)
    await _require_exists(name)
    return ContainerLogs(name=name, logs=await service.logs(name, tail=tail))


@router.delete("/{name}", response_model=OperationResult)
async def remove(name: str) -> OperationResult:
    """Stop and remove a managed container."""
    _guard(name)
    await _require_exists(name)
    return await service.remove(name)
