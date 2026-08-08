from fastapi import APIRouter

router = APIRouter(prefix="/api/digital-human", tags=["digital_human"])


@router.get("/status")
async def digital_human_status():
    return {
        "available": False,
        "message": "数字人功能尚未集成。预计使用 MuseTalk 模型实现。",
        "model": "TMElyralab/MuseTalk",
        "plan": "上传驱动音频 + 数字人形象 → 生成口型同步视频",
    }


@router.post("/generate")
async def generate_digital_human():
    return {
        "status": "not_implemented",
        "message": "数字人功能预留接口，待后期集成 MuseTalk 后可用。"
    }
