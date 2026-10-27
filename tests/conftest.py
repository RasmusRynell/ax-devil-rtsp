"""Shared fixtures: a throwaway self-signed certificate for the HTTPS fake camera."""

from __future__ import annotations

import datetime
import ipaddress
from collections.abc import Iterator
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

import fake_camera


@pytest.fixture(scope="session")
def tls_certificate(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Write a one-day self-signed certificate and key for 127.0.0.1 to a pytest temp dir."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    now = datetime.datetime.now(datetime.timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
        .sign(key, hashes.SHA256())
    )
    path = tmp_path_factory.mktemp("tls") / "localhost.pem"
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        + certificate.public_bytes(serialization.Encoding.PEM)
    )
    return path


@pytest.fixture(scope="session", autouse=True)
def _fake_camera_certificate(tls_certificate: Path) -> Iterator[None]:
    fake_camera.CERTIFICATE = tls_certificate
    yield
    fake_camera.CERTIFICATE = None
