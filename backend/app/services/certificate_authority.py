from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


@dataclass(frozen=True)
class SignedAgentCertificate:
    certificate_pem: str
    fingerprint: str


class DashboardCertificateAuthority:
    def __init__(self, ca_key=None, ca_certificate=None) -> None:  # noqa: ANN001
        if ca_key is None or ca_certificate is None:
            ca_key, ca_certificate = _generate_ca()
        self._ca_key = ca_key
        self._ca_certificate = ca_certificate

    def sign_agent_csr(self, csr_pem: str) -> SignedAgentCertificate:
        csr = x509.load_pem_x509_csr(csr_pem.encode("utf-8"))
        now = datetime.now(UTC)
        certificate = (
            x509.CertificateBuilder()
            .subject_name(csr.subject)
            .issuer_name(self._ca_certificate.subject)
            .public_key(csr.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(days=365))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(
                x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH, ExtendedKeyUsageOID.SERVER_AUTH]),
                critical=False,
            )
            .sign(private_key=self._ca_key, algorithm=hashes.SHA256())
        )
        certificate_pem = certificate.public_bytes(serialization.Encoding.PEM).decode("ascii")
        return SignedAgentCertificate(
            certificate_pem=certificate_pem,
            fingerprint=certificate_fingerprint(certificate_pem),
        )

    def ca_certificate_pem(self) -> str:
        return self._ca_certificate.public_bytes(serialization.Encoding.PEM).decode("ascii")


def certificate_fingerprint(certificate_pem: str) -> str:
    certificate = x509.load_pem_x509_certificate(certificate_pem.encode("utf-8"))
    digest = hashlib.sha256(certificate.public_bytes(serialization.Encoding.DER)).hexdigest()
    return f"sha256:{digest}"


def _generate_ca():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(UTC)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "web-xray-dashboard CA")])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(private_key=private_key, algorithm=hashes.SHA256())
    )
    return private_key, certificate
