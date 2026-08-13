import os
import orjson
from fastapi import APIRouter, Query, HTTPException, Depends
from fastapi.responses import ORJSONResponse
from config import settings
from auth import get_current_user

router = APIRouter()


def _sanitize_email(email: str) -> str:
    if "/" in email or "\\" in email or ".." in email or "\x00" in email:
        raise HTTPException(status_code=400, detail="Geçersiz email")
    return email.replace("@", "_at_").replace(".", "_")


def _safe_join(email: str, *parts: str) -> str:
    """Email'den türetilen yolun cookies_output_dir içinde kaldığını doğrular."""
    sanitized = _sanitize_email(email)
    base_real = os.path.realpath(settings.cookies_output_dir)
    full = os.path.realpath(os.path.join(base_real, sanitized, *parts))
    if full != base_real and not full.startswith(base_real + os.sep):
        raise HTTPException(status_code=400, detail="Geçersiz yol")
    return full


@router.get("/session/inspector")
async def cookie_inspector(
    email: str = Query(...),
    profile_index: int = Query(1, ge=1),
    _user: dict = Depends(get_current_user),
):
    output_dir = _safe_join(email)
    if not os.path.isdir(output_dir):
        return ORJSONResponse(content={"cookies": [], "origins": []})

    target_file = f"profile_{profile_index:05d}.json"
    path = os.path.join(output_dir, target_file)

    if not os.path.exists(path):
        profiles = sorted([
            f for f in os.listdir(output_dir) if f.startswith("profile_") and f.endswith(".json")
        ])
        if not profiles:
            return ORJSONResponse(content={"cookies": [], "origins": []})
        path = os.path.join(output_dir, profiles[0])

    with open(path, "rb") as f:
        data = orjson.loads(f.read())

    if "storage_state" in data:
        st = data["storage_state"]
        content = {
            "profile_index": data.get("profile_index"),
            "session_id": data.get("session_id"),
            "email": data.get("email"),
            "proxy_ip": data.get("proxy_ip"),
            "user_agent": data.get("user_agent"),
            "device": data.get("device"),
            "created_at": data.get("created_at"),
            "expires_at": data.get("expires_at"),
            "cookie_count": data.get("cookie_count"),
            "cookies": st.get("cookies", []),
            "origins": st.get("origins", []),
        }
    else:
        content = data

    return ORJSONResponse(content=content)


@router.get("/session/health")
async def session_health(
    email: str = Query(...),
    _user: dict = Depends(get_current_user),
):
    output_dir = _safe_join(email)
    if not os.path.isdir(output_dir):
        return {
            "email": email,
            "total_profiles": 0,
        }

    profile_files = [
        f for f in os.listdir(output_dir) if f.startswith("profile_") and f.endswith(".json")
    ]
    return {
        "email": email,
        "total_profiles": len(profile_files),
    }
