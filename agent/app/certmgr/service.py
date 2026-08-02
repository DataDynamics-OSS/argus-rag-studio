"""Certificate management service - CA upload, host certificate generation."""

import asyncio
import logging
from pathlib import Path

from app.certmgr.schemas import (
    CaInfo,
    HostCertFiles,
    HostCertInfo,
    HostCertRequest,
    OperationResult,
)
from app.core.config import settings

logger = logging.getLogger(__name__)


def _ca_dir() -> Path:
    """Return the CA certificate directory, derived from settings."""
    return settings.cert_base_dir / "ca"


def _cert_dir() -> Path:
    """Return the host certificate directory, derived from settings."""
    return settings.cert_base_dir


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _run(cmd: str) -> tuple[int, str, str]:
    """Run a shell command and return (exit_code, stdout, stderr)."""
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return (
        proc.returncode or 0,
        stdout.decode(errors="replace").strip(),
        stderr.decode(errors="replace").strip(),
    )


async def _parse_cert_info(cert_path: Path) -> dict:
    """Parse certificate subject, issuer, dates using openssl."""
    info: dict[str, str | None] = {
        "subject": None,
        "issuer": None,
        "not_before": None,
        "not_after": None,
    }
    if not cert_path.is_file():
        return info

    _, out, _ = await _run(
        f"openssl x509 -in {cert_path} -noout -subject -issuer -startdate -enddate"
    )
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("subject="):
            info["subject"] = line[len("subject=") :].strip()
        elif line.startswith("issuer="):
            info["issuer"] = line[len("issuer=") :].strip()
        elif line.startswith("notBefore="):
            info["not_before"] = line[len("notBefore=") :].strip()
        elif line.startswith("notAfter="):
            info["not_after"] = line[len("notAfter=") :].strip()

    return info


# ---------------------------------------------------------------------------
# 1. CA certificate upload
# ---------------------------------------------------------------------------


async def upload_ca(key_content: str, crt_content: str) -> OperationResult:
    """Upload CA key and certificate files."""
    ca_dir = _ca_dir()
    ca_dir.mkdir(parents=True, exist_ok=True)

    ca_key = ca_dir / "ca.key"
    ca_crt = ca_dir / "ca.crt"

    try:
        ca_key.write_text(key_content, encoding="utf-8")
        ca_key.chmod(0o400)
        ca_crt.write_text(crt_content, encoding="utf-8")
        ca_crt.chmod(0o444)
        logger.info("CA certificate uploaded to %s", ca_dir)

        # Validate the uploaded CA
        exit_code, _, stderr = await _run(f"openssl x509 -in {ca_crt} -noout -text")
        if exit_code != 0:
            return OperationResult(
                success=False,
                message=f"Uploaded CA certificate is invalid: {stderr}",
            )

        # Validate that key matches cert
        _, key_md5, _ = await _run(
            f"openssl rsa -in {ca_key} -noout -modulus 2>/dev/null | openssl md5"
        )
        _, crt_md5, _ = await _run(
            f"openssl x509 -in {ca_crt} -noout -modulus 2>/dev/null | openssl md5"
        )
        if key_md5 != crt_md5:
            return OperationResult(
                success=False,
                message="CA key and certificate do not match",
            )

        return OperationResult(
            success=True,
            message=f"CA certificate uploaded to {ca_dir}",
        )
    except OSError as e:
        return OperationResult(success=False, message=str(e))


# ---------------------------------------------------------------------------
# 2. CA certificate info
# ---------------------------------------------------------------------------


async def get_ca_info() -> CaInfo:
    """Get CA certificate information."""
    ca_key = _ca_dir() / "ca.key"
    ca_crt = _ca_dir() / "ca.crt"

    if not ca_crt.is_file() or not ca_key.is_file():
        return CaInfo(exists=False)

    info = await _parse_cert_info(ca_crt)
    return CaInfo(
        exists=True,
        key_path=str(ca_key),
        crt_path=str(ca_crt),
        **info,
    )


# ---------------------------------------------------------------------------
# 3. CA certificate delete
# ---------------------------------------------------------------------------


def delete_ca() -> OperationResult:
    """Delete all files in the CA directory."""
    ca_dir = _ca_dir()
    if not ca_dir.is_dir():
        return OperationResult(
            success=True,
            message="CA directory does not exist, nothing to delete",
        )

    try:
        removed = []
        for f in ca_dir.iterdir():
            if f.is_file():
                removed.append(f.name)
                f.unlink()
        logger.info("Deleted CA files: %s", removed)
        return OperationResult(
            success=True,
            message=f"Deleted CA files: {', '.join(removed)}" if removed else "No files to delete",
        )
    except OSError as e:
        return OperationResult(success=False, message=str(e))


# ---------------------------------------------------------------------------
# 4. Host certificate generation
# ---------------------------------------------------------------------------


async def generate_host_cert(request: HostCertRequest) -> OperationResult:
    """Generate host certificate signed by the uploaded CA.

    Generates: host.key, host.csr, host.ext, host.crt, host.pem, host-full.pem
    """
    ca_key = _ca_dir() / "ca.key"
    ca_crt = _ca_dir() / "ca.crt"

    if not ca_key.is_file() or not ca_crt.is_file():
        return OperationResult(
            success=False,
            message="CA certificate not found. Upload CA certificate first.",
        )

    cert_dir = _cert_dir()
    cert_dir.mkdir(parents=True, exist_ok=True)

    cert_days = settings.cert_days
    key_bits = settings.cert_key_bits

    host_key = cert_dir / "host.key"
    host_csr = cert_dir / "host.csr"
    host_ext = cert_dir / "host.ext"
    host_crt = cert_dir / "host.crt"
    host_pem = cert_dir / "host.pem"
    host_full = cert_dir / "host-full.pem"

    domain = request.domain

    # Build subject string
    subject_parts = []
    if request.country:
        subject_parts.append(f"C={request.country}")
    if request.state:
        subject_parts.append(f"ST={request.state}")
    if request.locality:
        subject_parts.append(f"L={request.locality}")
    if request.organization:
        subject_parts.append(f"O={request.organization}")
    if request.org_unit:
        subject_parts.append(f"OU={request.org_unit}")
    subject_parts.append(f"CN={domain}")
    subject = "/" + "/".join(subject_parts)

    try:
        # 1. Generate host private key
        exit_code, _, stderr = await _run(f"openssl genrsa -out {host_key} {key_bits}")
        if exit_code != 0:
            return OperationResult(success=False, message=f"Key generation failed: {stderr}")
        host_key.chmod(0o400)

        # 2. Generate CSR
        exit_code, _, stderr = await _run(
            f'openssl req -new -key {host_key} -out {host_csr} -subj "{subject}"'
        )
        if exit_code != 0:
            return OperationResult(success=False, message=f"CSR generation failed: {stderr}")

        # 3. Create X509v3 extension file
        # Get hostname for SAN
        _, hostname, _ = await _run("hostname")
        if not hostname:
            hostname = "localhost"

        ext_content = (
            "authorityKeyIdentifier=keyid,issuer\n"
            "basicConstraints=critical,CA:FALSE\n"
            "keyUsage=critical,digitalSignature,keyEncipherment\n"
            "extendedKeyUsage=serverAuth,clientAuth\n"
            "subjectAltName=@alt_names\n"
            "\n"
            "[alt_names]\n"
            f"DNS.1={domain}\n"
            f"DNS.2={hostname}\n"
            f"DNS.3=*.{domain}\n"
        )
        host_ext.write_text(ext_content, encoding="utf-8")

        # 4. Ensure CA serial file exists
        ca_serial = _ca_dir() / "ca.srl"
        if not ca_serial.is_file():
            ca_serial.write_text("01\n", encoding="utf-8")

        # 5. Sign with CA
        exit_code, _, stderr = await _run(
            f"openssl x509 -req "
            f"-in {host_csr} "
            f"-CA {ca_crt} "
            f"-CAkey {ca_key} "
            f"-CAserial {ca_serial} "
            f"-out {host_crt} "
            f"-days {cert_days} "
            f"-sha256 "
            f"-extfile {host_ext}"
        )
        if exit_code != 0:
            return OperationResult(success=False, message=f"Certificate signing failed: {stderr}")

        # 6. Create chain PEM (host cert + CA cert)
        chain = host_crt.read_text(encoding="utf-8") + ca_crt.read_text(encoding="utf-8")
        host_pem.write_text(chain, encoding="utf-8")

        # 7. Create full PEM (key + host cert + CA cert)
        full = (
            host_key.read_text(encoding="utf-8")
            + host_crt.read_text(encoding="utf-8")
            + ca_crt.read_text(encoding="utf-8")
        )
        host_full.write_text(full, encoding="utf-8")
        host_full.chmod(0o400)

        generated = ["host.key", "host.csr", "host.ext", "host.crt", "host.pem", "host-full.pem"]
        logger.info("Host certificate generated for %s: %s", domain, generated)
        return OperationResult(
            success=True,
            message=f"Host certificate generated for {domain} in {cert_dir}",
        )
    except OSError as e:
        return OperationResult(success=False, message=str(e))


# ---------------------------------------------------------------------------
# 5. Host certificate info
# ---------------------------------------------------------------------------


async def get_host_cert_info() -> HostCertInfo:
    """Get host certificate information."""
    cert_dir = _cert_dir()
    host_crt = cert_dir / "host.crt"

    if not host_crt.is_file():
        return HostCertInfo(exists=False)

    info = await _parse_cert_info(host_crt)

    files = [
        f.name for f in sorted(cert_dir.iterdir()) if f.is_file() and f.name.startswith("host")
    ]

    # Extract domain from subject CN
    domain = None
    if info.get("subject"):
        for part in info["subject"].split(","):
            part = part.strip()
            if part.startswith("CN =") or part.startswith("CN="):
                domain = part.split("=", 1)[1].strip()
                break

    return HostCertInfo(
        exists=True,
        domain=domain,
        files=files,
        **info,
    )


# ---------------------------------------------------------------------------
# 6. Host certificate files listing
# ---------------------------------------------------------------------------


def list_host_cert_files() -> HostCertFiles:
    """List all host certificate files."""
    cert_dir = _cert_dir()
    files = []
    if cert_dir.is_dir():
        files = [
            f.name for f in sorted(cert_dir.iterdir()) if f.is_file() and f.name.startswith("host")
        ]
    return HostCertFiles(cert_dir=str(cert_dir), files=files)


# ---------------------------------------------------------------------------
# 7. Host certificate delete
# ---------------------------------------------------------------------------


def delete_host_cert() -> OperationResult:
    """Delete all host certificate files (host.*)."""
    cert_dir = _cert_dir()
    if not cert_dir.is_dir():
        return OperationResult(
            success=True,
            message="Certificate directory does not exist, nothing to delete",
        )

    try:
        removed = []
        for f in cert_dir.iterdir():
            if f.is_file() and f.name.startswith("host"):
                removed.append(f.name)
                f.unlink()
        logger.info("Deleted host certificate files: %s", removed)
        return OperationResult(
            success=True,
            message=f"Deleted: {', '.join(removed)}" if removed else "No host certificate files",
        )
    except OSError as e:
        return OperationResult(success=False, message=str(e))
