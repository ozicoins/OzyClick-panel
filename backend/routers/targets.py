from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from auth import get_current_user
from services.target_config import get_targets, set_targets, MAX_TARGETS, DEFAULT_TARGETS

router = APIRouter()


class TargetsPatch(BaseModel):
    sites: list[str] = Field(default_factory=list, max_length=MAX_TARGETS)


@router.get("/target-sites")
async def list_targets(request: Request, _user: dict = Depends(get_current_user)):
    return {
        "sites": await get_targets(request.app.state.redis),
        "defaults": DEFAULT_TARGETS,
    }


@router.put("/target-sites")
async def update_targets(
    patch: TargetsPatch,
    request: Request,
    _user: dict = Depends(get_current_user),
):
    return {"sites": await set_targets(request.app.state.redis, patch.sites)}
