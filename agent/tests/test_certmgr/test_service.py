"""Tests for certmgr service - CA upload, host certificate generation."""

from unittest.mock import AsyncMock, patch

import pytest

from app.certmgr import service
from app.certmgr.schemas import HostCertRequest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cert_base(tmp_path):
    """Temporary certificates base directory (simulates settings.cert_base_dir)."""
    d = tmp_path / "certificates"
    d.mkdir()
    (d / "ca").mkdir()
    return d


@pytest.fixture(autouse=True)
def _patch_dirs(cert_base):
    """Patch settings.cert_base_dir to use temp directory."""
    with patch("app.certmgr.service.settings") as mock_settings:
        mock_settings.cert_base_dir = cert_base
        mock_settings.cert_days = 825
        mock_settings.cert_key_bits = 2048
        yield


SAMPLE_KEY = "-----BEGIN RSA PRIVATE KEY-----\nMIItest\n-----END RSA PRIVATE KEY-----\n"
SAMPLE_CRT = "-----BEGIN CERTIFICATE-----\nMIItest\n-----END CERTIFICATE-----\n"


# ---------------------------------------------------------------------------
# CA upload tests
# ---------------------------------------------------------------------------


async def test_upload_ca_success(cert_base):
    ca_dir = cert_base / "ca"
    with patch.object(service, "_run", new_callable=AsyncMock) as mock_run:
        mock_run.side_effect = [
            (0, "Certificate: ...", ""),
            (0, "md5hash123", ""),
            (0, "md5hash123", ""),
        ]
        result = await service.upload_ca(SAMPLE_KEY, SAMPLE_CRT)

    assert result.success is True
    assert (ca_dir / "ca.key").is_file()
    assert (ca_dir / "ca.crt").is_file()


async def test_upload_ca_invalid_cert():
    with patch.object(service, "_run", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = (1, "", "unable to load certificate")
        result = await service.upload_ca(SAMPLE_KEY, "bad cert")

    assert result.success is False
    assert "invalid" in result.message.lower()


async def test_upload_ca_key_mismatch():
    with patch.object(service, "_run", new_callable=AsyncMock) as mock_run:
        mock_run.side_effect = [
            (0, "Certificate: ...", ""),
            (0, "md5_key", ""),
            (0, "md5_crt_different", ""),
        ]
        result = await service.upload_ca(SAMPLE_KEY, SAMPLE_CRT)

    assert result.success is False
    assert "match" in result.message.lower()


# ---------------------------------------------------------------------------
# CA info tests
# ---------------------------------------------------------------------------


async def test_get_ca_info_exists(cert_base):
    ca_dir = cert_base / "ca"
    (ca_dir / "ca.key").write_text(SAMPLE_KEY)
    (ca_dir / "ca.crt").write_text(SAMPLE_CRT)

    with patch.object(service, "_run", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = (
            0,
            "subject=CN = Test CA\nissuer=CN = Test CA\n"
            "notBefore=Jan  1 00:00:00 2025 GMT\nnotAfter=Dec 31 23:59:59 2035 GMT",
            "",
        )
        result = await service.get_ca_info()

    assert result.exists is True
    assert result.subject == "CN = Test CA"
    assert result.not_before is not None


async def test_get_ca_info_not_exists(cert_base):
    # Remove ca files to simulate empty state
    ca_dir = cert_base / "ca"
    for f in ca_dir.iterdir():
        f.unlink()
    result = await service.get_ca_info()
    assert result.exists is False


# ---------------------------------------------------------------------------
# CA delete tests
# ---------------------------------------------------------------------------


def test_delete_ca(cert_base):
    ca_dir = cert_base / "ca"
    (ca_dir / "ca.key").write_text(SAMPLE_KEY)
    (ca_dir / "ca.crt").write_text(SAMPLE_CRT)
    (ca_dir / "ca.srl").write_text("01")

    result = service.delete_ca()
    assert result.success is True
    assert not (ca_dir / "ca.key").exists()
    assert not (ca_dir / "ca.crt").exists()


def test_delete_ca_empty_dir():
    result = service.delete_ca()
    assert result.success is True
    assert "No files" in result.message


def test_delete_ca_no_dir(tmp_path):
    with patch("app.certmgr.service.settings") as mock_settings:
        mock_settings.cert_base_dir = tmp_path / "nonexistent"
        result = service.delete_ca()
    assert result.success is True


# ---------------------------------------------------------------------------
# Host certificate generation tests
# ---------------------------------------------------------------------------


async def test_generate_host_cert_no_ca(cert_base):
    # Remove CA files
    ca_dir = cert_base / "ca"
    for f in ca_dir.iterdir():
        f.unlink()

    request = HostCertRequest(domain="example.com")
    result = await service.generate_host_cert(request)
    assert result.success is False
    assert "CA certificate not found" in result.message


async def test_generate_host_cert_success(cert_base):
    ca_dir = cert_base / "ca"
    (ca_dir / "ca.key").write_text(SAMPLE_KEY)
    (ca_dir / "ca.crt").write_text(SAMPLE_CRT)

    request = HostCertRequest(
        domain="example.com",
        country="KR",
        state="Gyeonggi-do",
        locality="Yongin-si",
        organization="Test Org",
        org_unit="Dev",
    )

    host_key = cert_base / "host.key"
    host_csr = cert_base / "host.csr"
    host_crt = cert_base / "host.crt"

    with patch.object(service, "_run", new_callable=AsyncMock) as mock_run:
        mock_run.side_effect = [
            _create_file_and_return(host_key, SAMPLE_KEY, (0, "", "")),
            _create_file_and_return(host_csr, "CSR", (0, "", "")),
            (0, "myhost", ""),  # hostname
            _create_file_and_return(host_crt, SAMPLE_CRT, (0, "", "")),
        ]

        result = await service.generate_host_cert(request)

    assert result.success is True
    assert "example.com" in result.message
    assert (cert_base / "host.key").is_file()
    assert (cert_base / "host.ext").is_file()
    assert (cert_base / "host.pem").is_file()
    assert (cert_base / "host-full.pem").is_file()


def _create_file_and_return(path, content, return_val):
    """Helper: create file and return mock value."""
    path.write_text(content)
    if path.name.endswith(".key"):
        path.chmod(0o400)
    return return_val


async def test_generate_host_cert_genrsa_fails(cert_base):
    ca_dir = cert_base / "ca"
    (ca_dir / "ca.key").write_text(SAMPLE_KEY)
    (ca_dir / "ca.crt").write_text(SAMPLE_CRT)

    request = HostCertRequest(domain="example.com")

    with patch.object(service, "_run", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = (1, "", "genrsa error")
        result = await service.generate_host_cert(request)

    assert result.success is False
    assert "Key generation failed" in result.message


# ---------------------------------------------------------------------------
# Host certificate info tests
# ---------------------------------------------------------------------------


async def test_get_host_cert_info_exists(cert_base):
    (cert_base / "host.crt").write_text(SAMPLE_CRT)
    (cert_base / "host.key").write_text(SAMPLE_KEY)
    (cert_base / "host.pem").write_text(SAMPLE_CRT)

    with patch.object(service, "_run", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = (
            0,
            "subject=CN = example.com\nissuer=CN = Test CA\n"
            "notBefore=Jan  1 00:00:00 2025 GMT\nnotAfter=Mar 31 23:59:59 2027 GMT",
            "",
        )
        result = await service.get_host_cert_info()

    assert result.exists is True
    assert result.domain == "example.com"
    assert len(result.files) >= 2


async def test_get_host_cert_info_not_exists(cert_base):
    result = await service.get_host_cert_info()
    assert result.exists is False


# ---------------------------------------------------------------------------
# Host certificate files listing tests
# ---------------------------------------------------------------------------


def test_list_host_cert_files(cert_base):
    (cert_base / "host.key").write_text(SAMPLE_KEY)
    (cert_base / "host.crt").write_text(SAMPLE_CRT)
    (cert_base / "host.pem").write_text(SAMPLE_CRT)
    (cert_base / "host-full.pem").write_text(SAMPLE_CRT)

    result = service.list_host_cert_files()
    assert len(result.files) == 4
    assert "host.key" in result.files
    assert "host.crt" in result.files


def test_list_host_cert_files_empty():
    result = service.list_host_cert_files()
    assert result.files == []


# ---------------------------------------------------------------------------
# Host certificate delete tests
# ---------------------------------------------------------------------------


def test_delete_host_cert(cert_base):
    (cert_base / "host.key").write_text(SAMPLE_KEY)
    (cert_base / "host.crt").write_text(SAMPLE_CRT)
    (cert_base / "host.pem").write_text(SAMPLE_CRT)
    (cert_base / "host-full.pem").write_text(SAMPLE_CRT)
    (cert_base / "host.csr").write_text("CSR")
    (cert_base / "host.ext").write_text("EXT")

    result = service.delete_host_cert()
    assert result.success is True

    host_files = [f for f in cert_base.iterdir() if f.is_file() and f.name.startswith("host")]
    assert len(host_files) == 0


def test_delete_host_cert_no_files():
    result = service.delete_host_cert()
    assert result.success is True
    assert "No host" in result.message
