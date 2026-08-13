"""Credential at-rest şifreleme (opsiyonel, Fernet).

Anahtar `settings.credential_key` üzerinden gelir. Production'da bu anahtar
runtime'da (secret manager / docker secret / env) inject edilmeli, DİSKE
yazılmamalıdır — aksi halde şifreli dosya ile anahtar aynı diskte olur ve
koruma sağlamaz.

Anahtar boşsa şifreleme devre dışıdır (gmail.csv düz metin okunur).
"""
from cryptography.fernet import Fernet
from config import settings


def is_enabled() -> bool:
    return bool(settings.credential_key)


def _cipher() -> Fernet:
    if not settings.credential_key:
        raise RuntimeError(
            "CREDENTIAL_KEY ayarlı değil — şifreli credential dosyası çözülemiyor."
        )
    return Fernet(settings.credential_key.encode())


def decrypt_bytes(data: bytes) -> bytes:
    return _cipher().decrypt(data)


def encrypt_bytes(data: bytes) -> bytes:
    return _cipher().encrypt(data)


def generate_key() -> str:
    return Fernet.generate_key().decode()
