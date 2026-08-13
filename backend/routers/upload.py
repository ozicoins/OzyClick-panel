from fastapi import APIRouter, File, UploadFile, HTTPException, Depends, Request
from pydantic import BaseModel, Field, field_validator

from services.csv_parser import CSVParserService
from services import account_store
from auth import get_current_user
from config import settings

router = APIRouter()
csv_service = CSVParserService()


class ManualAccount(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    password: str = Field(..., min_length=1, max_length=256)
    totp_secret: str = Field("", max_length=128)
    proxy_ip: str = Field("", max_length=512)
    # Kurtarma e-postası: 2FA'sız ama login sonrası "kurtarma adresini onayla" isteyen hesaplar için.
    recovery_email: str = Field("", max_length=254)

    @field_validator("email")
    @classmethod
    def _v_email(cls, v: str) -> str:
        v = v.strip()
        # Kontrol karakterleri (\r\n\t) reddedilir → log injection önlenir.
        if "@" not in v or any(c in v for c in " \r\n\t"):
            raise ValueError("Geçerli bir e-posta girin")
        return v


class BulkText(BaseModel):
    text: str = Field(..., max_length=4_000_000)


@router.get("/accounts/flags")
async def account_flags(request: Request, _user: dict = Depends(get_current_user)):
    """Cihaz-onaylı 2FA (telefon 'evet') tespit edilen hesaplar — otomatikleşmez, silinmeli.
    Ayrıca hesap başına bugün üretilen profil sayısı (aşırı-farmlama takibi)."""
    redis = request.app.state.redis
    device_prompt = await account_store.get_device_prompt_flags(redis)
    daily = {}
    try:
        for a in await account_store.get_accounts(redis):
            daily[a["email"]] = await account_store.get_daily_count(redis, a["email"])
    except Exception:
        pass
    return {"device_prompt": device_prompt, "daily": daily, "daily_limit": settings.per_account_daily_limit}


@router.post("/accounts/bulk")
async def add_accounts_bulk(
    payload: BulkText,
    request: Request,
    _user: dict = Depends(get_current_user),
):
    """Toplu hesap ekle — panele YAPIŞTIRILAN metinden. Her satır bir hesap, format:
        email|password|totp_secret|recovery_email|proxy
    Son 3 kolon opsiyonel. Dosya yüklemeye gerek yok."""
    parsed = csv_service.parse(payload.text.encode("utf-8"))
    if not parsed:
        raise HTTPException(
            status_code=400,
            detail="Geçerli satır bulunamadı. Format: email|password|totp|recovery|proxy (her satır bir hesap)",
        )
    merged = await account_store.merge_accounts(request.app.state.redis, parsed)
    return {
        "message": f"{len(parsed)} hesap eklendi. Havuzda toplam {len(merged)}.",
        "accounts": account_store.strip_sensitive(merged),
        "added": len(parsed),
    }


@router.post("/upload-csv")
async def upload_gmail_csv(
    request: Request,
    file: UploadFile = File(...),
    _user: dict = Depends(get_current_user),
):
    if not file.filename or not file.filename.lower().endswith((".csv", ".txt")):
        raise HTTPException(status_code=400, detail="Lütfen geçerli bir .csv veya .txt dosyası yükleyin.")

    max_bytes = settings.max_upload_bytes
    content = await file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Dosya çok büyük (maksimum {max_bytes // (1024 * 1024)} MB)",
        )

    parsed = csv_service.parse(content)
    # Havuza ekle (mevcut manuel/önceki hesapları KORU — dedup email'e göre).
    merged = await account_store.merge_accounts(request.app.state.redis, parsed)
    return {
        "message": f"{len(parsed)} hesap aktarıldı. Havuzda toplam {len(merged)}.",
        "accounts": account_store.strip_sensitive(merged),
    }


@router.post("/accounts")
async def add_account_manual(
    acc: ManualAccount,
    request: Request,
    _user: dict = Depends(get_current_user),
):
    """Tek hesabı elle ekle (txt'e bağımlı olmadan)."""
    account = account_store.make_account(
        acc.email, acc.password, acc.totp_secret.strip(), acc.proxy_ip.strip(),
        recovery_email=acc.recovery_email.strip(),
    )
    merged = await account_store.add_account(request.app.state.redis, account)
    return {
        "message": f"{acc.email} eklendi.",
        "accounts": account_store.strip_sensitive(merged),
    }


@router.delete("/accounts")
async def delete_account(
    request: Request,
    email: str,
    _user: dict = Depends(get_current_user),
):
    remaining = await account_store.remove_account(request.app.state.redis, email)
    return {"accounts": account_store.strip_sensitive(remaining)}


@router.get("/accounts")
async def get_loaded_accounts(request: Request, _user: dict = Depends(get_current_user)):
    accounts = await account_store.get_accounts(request.app.state.redis)
    return {"accounts": accounts}


@router.get("/accounts/reveal")
async def reveal_account(
    request: Request,
    email: str,
    _user: dict = Depends(get_current_user),
):
    """Tek hesabın gizli alanlarını (parola/2fa/proxy) admin'e AÇIKÇA gösterir.
    Yalnızca istenen hesap için, açık talep üzerine (liste yanıtı hâlâ maskeli)."""
    cred = await account_store.get_credentials(request.app.state.redis, email)
    if not cred:
        raise HTTPException(status_code=404, detail="Hesap bulunamadı")
    return {
        "email": cred.get("email", ""),
        "password": cred.get("password", ""),
        "totp_secret": cred.get("totp_secret", ""),
        "proxy_ip": cred.get("proxy_ip", ""),
        "recovery_email": cred.get("recovery_email", ""),
    }
