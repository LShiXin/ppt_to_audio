import uuid
from fastapi import APIRouter
from app.services.vllm_process import (
    get_current_model,
    get_switch_status,
    is_ready,
    switch_model,
)

router = APIRouter(prefix="/api/model", tags=["model"])


@router.get("/status")
async def model_status():
    return {
        "model": get_current_model(),
        "ready": is_ready(),
        "switch": get_switch_status(),
    }


@router.post("/switch")
async def switch_model_endpoint(data: dict):
    target = data.get("model", "")
    if target not in ("base", "customvoice"):
        return {"ok": False, "message": f"无效的模型类型: {target}"}

    result = await switch_model(target)
    if result == "already_switching":
        return {"ok": False, "message": "正在切换中，请稍后"}
    if result == "same_model":
        return {"ok": True, "message": f"已经是 {target} 模型，无需切换"}
    return {"ok": True, "task_id": result, "message": f"开始切换到 {target} 模型"}