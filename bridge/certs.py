"""Generate a CA and server certificate for the OpenGarden bridge."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def ensure_certificates(
    certs_dir: Path, hostname: str
) -> tuple[Path, Path, Path]:
    """Return (ca_cert, server_cert, server_key) paths, generating if absent."""
    certs_dir.mkdir(parents=True, exist_ok=True)

    ca_cert_path = certs_dir / "ca.pem"
    ca_key_path = certs_dir / "ca-key.pem"
    server_cert_path = certs_dir / "server.pem"
    server_key_path = certs_dir / "server-key.pem"

    if ca_cert_path.exists() and server_cert_path.exists():
        return ca_cert_path, server_cert_path, server_key_path

    now = datetime.now(timezone.utc)

    # --- CA ---
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "OpenGarden"),
        x509.NameAttribute(NameOID.COMMON_NAME, "OpenGarden Local CA"),
    ])
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(
            x509.BasicConstraints(ca=True, path_length=0), critical=True
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_cert_sign=True,
                crl_sign=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )
    _write_key(ca_key_path, ca_key)
    ca_cert_path.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))

    # --- Server cert signed by the CA ---
    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    # SAN: the exact hostname the garden connects to, plus the wildcard the
    # vendor cert carries.
    domain = hostname.split(".", 1)[1] if "." in hostname else hostname
    server_cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "OpenGarden"),
            x509.NameAttribute(NameOID.COMMON_NAME, hostname),
        ]))
        .issuer_name(ca_name)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName(hostname),
                x509.DNSName(f"*.{domain}"),
            ]),
            critical=False,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=True,
                content_commitment=False,
                key_cert_sign=False,
                crl_sign=False,
                data_encipherment=False,
                key_agreement=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )
    _write_key(server_key_path, server_key)
    server_cert_path.write_bytes(
        server_cert.public_bytes(serialization.Encoding.PEM)
    )

    return ca_cert_path, server_cert_path, server_key_path


def _write_key(path: Path, key: rsa.RSAPrivateKey) -> None:
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    path.chmod(0o600)
