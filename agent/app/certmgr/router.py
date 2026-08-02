"""Certificate management API routes."""

from fastapi import APIRouter

from app.certmgr.schemas import (
    CaInfo,
    CaUploadRequest,
    HostCertFiles,
    HostCertInfo,
    HostCertRequest,
    OperationResult,
)
from app.certmgr.service import (
    delete_ca,
    delete_host_cert,
    generate_host_cert,
    get_ca_info,
    get_host_cert_info,
    list_host_cert_files,
    upload_ca,
)

router = APIRouter(prefix="/cert", tags=["cert"])


# ---------------------------------------------------------------------------
# CA certificate
# ---------------------------------------------------------------------------


@router.post("/ca", response_model=OperationResult)
async def ca_upload(request: CaUploadRequest) -> OperationResult:
    """Upload CA key and certificate."""
    return await upload_ca(request.key_content, request.crt_content)


@router.get("/ca", response_model=CaInfo)
async def ca_info() -> CaInfo:
    """Get CA certificate information."""
    return await get_ca_info()


@router.delete("/ca", response_model=OperationResult)
async def ca_delete() -> OperationResult:
    """Delete all CA certificate files."""
    return delete_ca()


# ---------------------------------------------------------------------------
# Host certificate
# ---------------------------------------------------------------------------


@router.post("/host", response_model=OperationResult)
async def host_cert_generate(request: HostCertRequest) -> OperationResult:
    """Generate host certificate signed by CA."""
    return await generate_host_cert(request)


@router.get("/host", response_model=HostCertInfo)
async def host_cert_info() -> HostCertInfo:
    """Get host certificate information."""
    return await get_host_cert_info()


@router.get("/host/files", response_model=HostCertFiles)
async def host_cert_files() -> HostCertFiles:
    """List host certificate files."""
    return list_host_cert_files()


@router.delete("/host", response_model=OperationResult)
async def host_cert_delete() -> OperationResult:
    """Delete all host certificate files."""
    return delete_host_cert()
