"""Self-signed LAN certificate so a phone can use the microphone (HTTPS = secure context)."""

from __future__ import annotations

import ipaddress
from datetime import datetime, timedelta, timezone
from pathlib import Path


def cert_paths(data_dir: str | Path) -> tuple[Path, Path]:
    d = Path(data_dir) / "tls"
    return d / "lan.crt", d / "lan.key"


def ensure_lan_cert(data_dir: str | Path, extra_ips: list[str] | None = None) -> tuple[Path, Path]:
    crt, key = cert_paths(data_dir)
    if crt.exists() and key.exists() and crt.stat().st_size > 80 and key.stat().st_size > 80:
        return crt, key
    crt.parent.mkdir(parents=True, exist_ok=True)

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    names: list[x509.GeneralName] = [
        x509.DNSName("localhost"),
        x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
    ]
    seen = {"127.0.0.1"}
    for raw in extra_ips or []:
        text = str(raw).strip()
        if not text or text in seen or text in ("0.0.0.0", "::"):
            continue
        try:
            ip = ipaddress.ip_address(text)
        except ValueError:
            continue
        names.append(x509.IPAddress(ip))
        seen.add(text)

    now = datetime.now(timezone.utc)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Friday LAN")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(private.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=825))
        .add_extension(x509.SubjectAlternativeName(names), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(private, hashes.SHA256())
    )
    key.write_bytes(
        private.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    crt.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return crt, key
