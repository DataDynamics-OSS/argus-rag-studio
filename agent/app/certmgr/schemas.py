"""Certificate management schemas."""

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Common
# ---------------------------------------------------------------------------


class OperationResult(BaseModel):
    """Generic operation result."""

    success: bool
    message: str = ""


# ---------------------------------------------------------------------------
# CA certificate
# ---------------------------------------------------------------------------


class CaUploadRequest(BaseModel):
    """CA certificate upload request (key + crt as base64-encoded content)."""

    key_content: str = Field(..., description="CA private key file content (PEM)")
    crt_content: str = Field(..., description="CA certificate file content (PEM)")


class CaInfo(BaseModel):
    """CA certificate information."""

    exists: bool
    key_path: str | None = None
    crt_path: str | None = None
    subject: str | None = None
    issuer: str | None = None
    not_before: str | None = None
    not_after: str | None = None


# ---------------------------------------------------------------------------
# Host certificate
# ---------------------------------------------------------------------------


class HostCertRequest(BaseModel):
    """Host certificate generation request."""

    domain: str = Field(..., description="Domain name (e.g. example.com)")
    country: str = Field(default="KR", description="Country code (C)")
    state: str = Field(default="", description="State or province (ST)")
    locality: str = Field(default="", description="Locality / city (L)")
    organization: str = Field(default="", description="Organization name (O)")
    org_unit: str = Field(default="", description="Organizational unit (OU)")


class HostCertInfo(BaseModel):
    """Host certificate information."""

    exists: bool
    domain: str | None = None
    files: list[str] = Field(default_factory=list)
    subject: str | None = None
    issuer: str | None = None
    not_before: str | None = None
    not_after: str | None = None


class HostCertFiles(BaseModel):
    """Host certificate file listing."""

    cert_dir: str
    files: list[str] = Field(default_factory=list)
