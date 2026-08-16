import uuid
from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from app.models.database import get_db
from app.models.schemas import AudioGenerateRequest
from app.services.tts_backend import generate_audio_with_segmentation, clear_tts_cache
from app.services.audio_composer import compose_audio
from app.services.voice_clone_service import load_voice_prompt
from app.config import OUTPUTS_DIR

router = APIRouter(prefix="/api/audio", tags=["audio"])

_task_status: dict[str, dict] = {}


@router.post("/generate")
async def generate_project_audio(data: AudioGenerateRequest, background_tasks: BackgroundTasks):
    db = await get_db()

    project_row = await db.execute("SELECT * FROM projects WHERE id = ?", (data.project_id,))
    project = await project_row.fetchone()
    if not project:
        raise HTTPException(404, "项目不存在")

    if data.slide_id is not None:
        slide_row = await db.execute("SELECT * FROM slides WHERE id = ?", (data.slide_id,))
        slide = await slide_row.fetchone()
        if not slide:
            raise HTTPException(404, "幻灯片不存在")
        if not slide["narration"]:
            raise HTTPException(400, "该幻灯片没有讲稿，请先生成讲稿")
        slides_to_process = [dict(slide)]
    else:
        slides_cursor = await db.execute(
            "SELECT * FROM slides WHERE project_id = ? ORDER BY slide_number",
            (data.project_id,),
        )
        slides = [dict(s) for s in await slides_cursor.fetchall()]
        if not slides:
            raise HTTPException(400, "项目没有幻灯片")
        slides_to_process = [s for s in slides if s["narration"]]
        if not slides_to_process:
            raise HTTPException(400, "没有可生成音频的讲稿，请先生成讲稿")

    voice_clone_prompt = None
    if data.voice_id:
        voice_row = await db.execute("SELECT * FROM voices WHERE name = ?", (data.voice_id,))
        voice = await voice_row.fetchone()
        if voice:
            voice_clone_prompt = load_voice_prompt(voice["name"])

    task_id = uuid.uuid4().hex
    _task_status[task_id] = {
        "status": "running",
        "progress": 0,
        "message": "正在生成音频...",
        "completed_slides": [],
    }

    background_tasks.add_task(
        _run_audio_generation,
        task_id,
        slides_to_process,
        data.speaker,
        data.voice_description,
        voice_clone_prompt,
        data.project_id,
        data.slide_id is not None,
        data.speed,
        data.seed,
        data.model,
        data.temperature,
    )

    return {"task_id": task_id, "status": "running", "message": "音频生成已启动"}


async def _run_audio_generation(
    task_id: str,
    slides: list[dict],
    speaker: str | None,
    voice_description: str | None,
    voice_clone_prompt,
    project_id: int,
    is_single_slide: bool,
    speed: float | None,
    seed: int | None,
    model: str = "",
    temperature: float | None = None,
):
    try:
        db = await get_db()
        total = len(slides)
        audio_paths = []
        completed_slides = []

        for i, slide in enumerate(slides):
            _task_status[task_id] = {
                "status": "running",
                "progress": int((i / total) * 90),
                "message": f"正在生成第 {slide['slide_number']} 页音频...",
                "completed_slides": completed_slides,
            }

            output_name = f"slide_{slide['id']}_{project_id}_{uuid.uuid4().hex[:8]}.wav"
            audio_rel = await generate_audio_with_segmentation(
                text=slide["narration"],
                output_filename=output_name,
                speaker=speaker,
                voice=speaker,
                voice_design=voice_description,
                voice_clone_prompt=voice_clone_prompt,
                speed=speed,
                seed=seed,
                model=model or None,
                temperature=temperature,
            )

            audio_paths.append(str(OUTPUTS_DIR / audio_rel))

            await db.execute(
                "UPDATE slides SET narration_audio = ?, status = 'audio_generated' WHERE id = ?",
                (audio_rel, slide["id"]),
            )
            await db.commit()

            completed_slides.append({
                "slide_id": slide["id"],
                "slide_number": slide["slide_number"],
                "audio_path": audio_rel,
            })

            _task_status[task_id] = {
                "status": "running",
                "progress": int(((i + 1) / total) * 90),
                "message": f"第 {slide['slide_number']} 页音频已完成",
                "completed_slides": completed_slides,
            }

            clear_tts_cache()

        if is_single_slide:
            old_audio = slides[0].get("narration_audio")
            if old_audio:
                old_path = OUTPUTS_DIR / old_audio
                if old_path.exists():
                    old_path.unlink()
            _task_status[task_id] = {
                "status": "completed",
                "progress": 100,
                "message": "音频生成完成",
                "completed_slides": completed_slides,
            }
            return

        _task_status[task_id] = {
            "status": "composing",
            "progress": 92,
            "message": "正在拼接音频...",
            "completed_slides": completed_slides,
        }

        composed = compose_audio(audio_paths, f"project_{project_id}_{uuid.uuid4().hex[:8]}.mp3")
        await db.execute(
            "UPDATE projects SET status = 'completed', composed_audio = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (composed, project_id),
        )
        await db.commit()

        clear_tts_cache()

        _task_status[task_id] = {
            "status": "completed",
            "progress": 100,
            "message": "音频生成完成",
            "completed_slides": completed_slides,
            "result": {"composed_audio": composed},
        }
    except Exception as e:
        clear_tts_cache()
        _task_status[task_id] = {
            "status": "failed",
            "progress": 0,
            "message": str(e),
            "completed_slides": [],
        }


@router.post("/regenerate/{slide_id}")
async def regenerate_slide_audio(slide_id: int, data: AudioGenerateRequest, background_tasks: BackgroundTasks):
    data.slide_id = slide_id
    return await generate_project_audio(data, background_tasks)


@router.get("/task/{task_id}")
async def get_task_status(task_id: str):
    if task_id not in _task_status:
        raise HTTPException(404, "任务不存在")
    return _task_status[task_id]


@router.get("/slide/{slide_id}")
async def get_slide_audio(slide_id: int):
    db = await get_db()
    row = await db.execute("SELECT narration_audio FROM slides WHERE id = ?", (slide_id,))
    slide = await row.fetchone()
    if not slide or not slide["narration_audio"]:
        raise HTTPException(404, "该幻灯片音频未生成")
    return {"audio_path": slide["narration_audio"]}


@router.get("/download/{project_uuid}")
async def download_composed_audio(project_uuid: str):
    db = await get_db()
    row = await db.execute(
        "SELECT id, composed_audio FROM projects WHERE uuid = ?", (project_uuid,)
    )
    project = await row.fetchone()
    if not project or not project["composed_audio"]:
        raise HTTPException(404, "合成音频未生成")
    audio_full = OUTPUTS_DIR / project["composed_audio"]
    if not audio_full.exists():
        raise HTTPException(404, "合成音频文件已丢失")
    resp = FileResponse(
        str(audio_full),
        media_type="audio/mpeg",
        filename=f"project_{project['id']}.mp3",
    )
    # 禁止缓存：URL 固定不变，重新生成后必须下载新文件
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp
