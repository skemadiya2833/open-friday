from cryptography import x509

from friday.server.tls import ensure_lan_cert


def test_lan_cert_includes_phone_ip(tmp_path):
    crt, key = ensure_lan_cert(tmp_path, ["192.168.1.24", "127.0.0.1"])
    assert crt.exists() and key.exists()
    cert = x509.load_pem_x509_certificate(crt.read_bytes())
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    texts = [str(n) for n in san]
    assert any("192.168.1.24" in t for t in texts)
    assert any("127.0.0.1" in t for t in texts)
    again, _ = ensure_lan_cert(tmp_path, ["10.0.0.1"])
    assert again == crt  # reuse until files are gone
