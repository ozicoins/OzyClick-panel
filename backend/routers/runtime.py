from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from auth import get_current_user
from services.runtime_config import get_dry_run, set_dry_run

router = APIRouter()


class RunModePatch(BaseModel):
    dry_run: bool


@router.get("/run-mode")
async def get_run_mode(request: Request, _user: dict = Depends(get_current_user)):
    return {"dry_run": await get_dry_run(request.app.state.redis)}


@router.put("/run-mode")
async def set_run_mode(
    patch: RunModePatch,
    request: Request,
    _user: dict = Depends(get_current_user),
):
    value = await set_dry_run(request.app.state.redis, patch.dry_run)
    return {"dry_run": value}
