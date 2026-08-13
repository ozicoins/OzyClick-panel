import orjson
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from services.keyword_manager import KeywordManager
from auth import get_current_user

router = APIRouter()
km = KeywordManager()
CUSTOM_KEY = "keywords:custom"

MAX_KEYWORDS = 100
MAX_KEYWORD_LEN = 100


class CustomKeywordRequest(BaseModel):
    sector: str = Field(..., min_length=1, max_length=100)
    keywords: list[str] = Field(..., max_length=MAX_KEYWORDS)

    @field_validator("keywords")
    @classmethod
    def _validate_keywords(cls, v: list[str]) -> list[str]:
        cleaned = [k.strip() for k in v if k.strip()]
        if any(len(k) > MAX_KEYWORD_LEN for k in cleaned):
            raise ValueError(f"Her keyword en fazla {MAX_KEYWORD_LEN} karakter olabilir")
        return cleaned


@router.get("/keywords/{sector}")
async def get_keywords(sector: str, _user: dict = Depends(get_current_user)):
    if len(sector) > 100:
        raise HTTPException(status_code=400, detail="Geçersiz sektör")
    keywords = km.get_keywords(sector)
    return {"sector": sector, "keywords": keywords}


@router.put("/keywords/custom")
async def set_custom_keywords(
    req: CustomKeywordRequest,
    request: Request,
    _user: dict = Depends(get_current_user),
):
    km.set_custom_keywords(req.sector, req.keywords)
    # Redis'e kalıcı yaz → restart'ta korunur, engine+scheduler paylaşılan sınıf-dict'ten okur.
    try:
        await request.app.state.redis.set(CUSTOM_KEY, orjson.dumps(km.dump_custom()))
    except Exception:
        pass
    return {"sector": req.sector, "keywords": req.keywords, "status": "updated"}
