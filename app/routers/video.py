import asyncio
import uuid
from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel
from app.models.database import get_db
from app.config import OUTPUTS_DIR
from app.services.video_composer import build_video_from_slides

router = APIRouter(prefix="/api/video", tags=["video"])

_task_status: dict[str, dict] = {}


class VideoGenerateRequest(BaseModel):
    project_id: int


@router.post("/generate")
async def generate_video(data: VideoGenerateRequest, background_tasks: BackgroundTasks):
    db = await get_db()

    project_row = await db.execute("SELECT * FROM projects WHERE id = ?", (data.project_id,))
    project = await project_row.fetchone()
    if not project:
        raise HTTPException(404, "项目不存在")

    slides_cursor = await db.execute(
        "SELECT * FROM slides WHERE project_id = ? ORDER BY slide_number",
        (data.project_id,),
    )
    slides = [dict(s) for s in await slides_cursor.fetchall()]
    if not slides:
        raise HTTPException(400, "项目没有页面，请先上传PDF")

    missing_audio = [s for s in slides if not s.get("narration_audio")]
    if missing_audio:
        raise HTTPException(400, f"第 {missing_audio[0]['slide_number']} 页等共 {len(missing_audio)} 页音频未生成，请先生成音频")

    task_id = uuid.uuid4().hex
    _task_status[task_id] = {"status": "running", "progress": 0, "message": "正在合成视频..."}

    background_tasks.add_task(_run_video_generation, task_id, slides, data.project_id)

    return {"task_id": task_id, "status": "running", "message": "视频生成已启动"}


async def _run_video_generation(task_id: str, slides: list[dict], project_id: int):
    try:
        db = await get_db()
        total = len(slides)

        def _on_progress(done: int, n: int):
            _task_status[task_id] = {
                "status": "running",
                "progress": int((done / n) * 90),
                "message": f"正在编码第 {done}/{n} 页视频...",
            }

        _task_status[task_id] = {
            "status": "running", "progress": 0, "message": "正在准备视频合成...",
        }
        output_path = await asyncio.to_thread(
            build_video_from_slides, slides, project_id, _on_progress
        )

        _task_status[task_id] = {
            "status": "running", "progress": 95, "message": "正在写入数据库...",
        }
        await db.execute(
            "UPDATE projects SET video_path = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (output_path, project_id),
        )
        await db.commit()
        _task_status[task_id] = {
            "status": "completed", "progress": 100,
            "message": "视频生成完成",
            "result": {"video_path": output_path},
        }
    except Exception as e:
        _task_status[task_id] = {"status": "failed", "progress": 0, "message": str(e)}


@router.get("/task/{task_id}")
async def get_task_status(task_id: str):
    if task_id not in _task_status:
        raise HTTPException(404, "任务不存在")
    return _task_status[task_id]


@router.get("/download/{project_uuid}")
async def download_video(project_uuid: str):
    db = await get_db()
    row = await db.execute("SELECT id, video_path FROM projects WHERE uuid = ?", (project_uuid,))
    project = await row.fetchone()
    if not project or not project["video_path"]:
        raise HTTPException(404, "视频文件不存在")
    video_full = OUTPUTS_DIR / project["video_path"]
    if not video_full.exists():
        raise HTTPException(404, "视频文件已丢失")
    resp = FileResponse(str(video_full), media_type="video/mp4",
                        filename=f"project_{project['id']}.mp4")
    # 禁止缓存：URL 固定不变，重新生成后必须下载新文件
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp
