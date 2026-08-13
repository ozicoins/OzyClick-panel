#!/usr/bin/env python3
"""
gmail.csv → gmail.csv.enc (Fernet ile şifreler).

Amaç: Gmail kimlik bilgilerini diskte DÜZ METİN tutmamak.

Kullanım:
    # 1) Anahtar üret (bir kez) ve GÜVENLİ yerde sakla:
    python3 encrypt_csv.py --genkey

    # 2) Anahtarı ortam değişkeni olarak verip şifrele:
    CREDENTIAL_KEY="<anahtar>" python3 encrypt_csv.py

    # 3) Düz metin gmail.csv'yi SİLİN; yalnızca gmail.csv.enc kalsın.
    # 4) Uygulamayı çalıştırırken CREDENTIAL_KEY'i runtime'da inject edin
    #    (docker secret / secret manager) — diske YAZMAYIN.

Uygulama, gmail.csv yoksa otomatik olarak gmail.csv.enc dosyasını CREDENTIAL_KEY
ile çözüp okur.
"""
import argparse
import os
import sys

try:
    from cryptography.fernet import Fernet
except ImportError:
    sys.exit("cryptography kurulu değil. Çalıştırın: pip install cryptography")

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "gmail.csv")
DST = os.path.join(ROOT, "gmail.csv.enc")
ENV = os.path.join(ROOT, ".env")


def _key_from_env_file() -> str | None:
    """CREDENTIAL_KEY'i .env dosyasından okur (ortam değişkeni yoksa)."""
    if not os.path.exists(ENV):
        return None
    with open(ENV, "r") as f:
        for line in f:
            line = line.strip()
            if line.startswith("CREDENTIAL_KEY="):
                val = line.split("=", 1)[1].strip()
                return val or None
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--genkey", action="store_true", help="Yeni Fernet anahtarı üret ve çık")
    ap.add_argument("--keep", action="store_true", help="Şifreledikten sonra düz metni SİLME")
    args = ap.parse_args()

    if args.genkey:
        print(Fernet.generate_key().decode())
        print("↑ Bu anahtarı CREDENTIAL_KEY olarak güvenli şekilde saklayın.", file=sys.stderr)
        return

    key = os.environ.get("CREDENTIAL_KEY") or _key_from_env_file()
    if not key:
        sys.exit("CREDENTIAL_KEY yok (ne ortamda ne .env'de). Önce: python3 encrypt_csv.py --genkey")

    if not os.path.exists(SRC):
        sys.exit(f"Bulunamadı: {SRC}")

    with open(SRC, "rb") as f:
        plaintext = f.read()

    # Yazmadan önce round-trip doğrula (veri kaybını önler).
    cipher = Fernet(key.encode())
    token = cipher.encrypt(plaintext)
    assert cipher.decrypt(token) == plaintext, "Round-trip doğrulaması başarısız"

    with open(DST, "wb") as f:
        f.write(token)
    os.chmod(DST, 0o600)
    print(f"✓ Şifrelendi + doğrulandı → {DST} (chmod 600)")

    if args.keep:
        print(f"Düz metin korundu. Hazır olunca silin:  rm {SRC}")
    else:
        os.remove(SRC)
        print(f"✓ Düz metin silindi: {SRC}")
    print("Uygulama CREDENTIAL_KEY ile gmail.csv.enc'i otomatik çözer.")


if __name__ == "__main__":
    main()
