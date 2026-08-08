import uuid
import asyncio
from fastapi import APIRouter, HTTPException, BackgroundTasks
from app.models.database import get_db
from app.models.schemas import (
    ScriptGenerateRequest, SingleSlideGenerateRequest,
    SlideOut, SlideUpdate,
)
from app.services.script_generator import generate_slide_script, generate_topic

router = APIRouter(prefix="/api/scripts", tags=["scripts"])

_task_status: dict[str, dict] = {}


@router.post("/generate")
async def generate_narration(data: ScriptGenerateRequest, background_tasks: BackgroundTasks):
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
        raise HTTPException(400, "项目没有幻灯片，请先上传PPT")

    refs_cursor = await db.execute(
        "SELECT content FROM reference_files WHERE project_id = ?", (data.project_id,)
    )
    ref_texts = [r["content"] for r in await refs_cursor.fetchall() if r["content"]]

    task_id = uuid.uuid4().hex
    _task_status[task_id] = {"status": "running", "progress": 0, "message": "正在生成讲稿...", "total": len(slides)}

    background_tasks.add_task(
        _run_script_generation,
        task_id, slides, project["topic"] or "", ref_texts,
        data.word_count, data.llm_model, data.project_id,
    )

    return {"task_id": task_id, "status": "running"}


async def _run_script_generation(
    task_id: str, slides: list[dict], topic: str, ref_texts: list[str],
    word_count: str, model: str, project_id: int,
):
    try:
        db = await get_db()
        for i, s in enumerate(slides):
            _task_status[task_id] = {
                "status": "running",
                "progress": int((i / len(slides)) * 100),
                "message": f"正在生成第 {s['slide_number']} 页讲稿 ({i + 1}/{len(slides)})...",
                "total": len(slides),
                "current": i + 1,
            }

            try:
                narration = await generate_slide_script(s, topic, ref_texts, word_count, model)
            except Exception:
                narration = f"第{s['slide_number']}页的内容是：{s.get('title', '')}。{s.get('content', '')[:100]}"

            await db.execute(
                "UPDATE slides SET narration = ?, status = 'scripted' WHERE id = ?",
                (narration, s["id"]),
            )
            await db.commit()

        await db.execute(
            "UPDATE projects SET status = 'scripted', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (project_id,),
        )
        await db.commit()

        _task_status[task_id] = {
            "status": "completed", "progress": 100, "message": "讲稿生成完成",
            "total": len(slides), "current": len(slides),
        }
    except Exception as e:
        _task_status[task_id] = {"status": "failed", "progress": 0, "message": str(e)}


@router.get("/generate/task/{task_id}")
async def get_task_status(task_id: str):
    if task_id not in _task_status:
        raise HTTPException(404, "任务不存在")
    return _task_status[task_id]


@router.post("/slides/{slide_id}/generate", response_model=SlideOut)
async def generate_slide_narration(slide_id: int, data: SingleSlideGenerateRequest):
    db = await get_db()
    slide_row = await db.execute("SELECT * FROM slides WHERE id = ?", (slide_id,))
    slide = await slide_row.fetchone()
    if not slide:
        raise HTTPException(404, "幻灯片不存在")

    project_row = await db.execute("SELECT * FROM projects WHERE id = ?", (slide["project_id"],))
    project = await project_row.fetchone()
    if not project:
        raise HTTPException(404, "项目不存在")

    refs_cursor = await db.execute(
        "SELECT content FROM reference_files WHERE project_id = ?", (slide["project_id"],)
    )
    ref_texts = [r["content"] for r in await refs_cursor.fetchall() if r["content"]]

    try:
        narration = await generate_slide_script(
            dict(slide),
            project["topic"] or "",
            ref_texts,
            data.word_count,
            data.llm_model,
        )
    except Exception as e:
        raise HTTPException(500, f"讲稿生成失败: {e}")

    await db.execute(
        "UPDATE slides SET narration = ?, status = 'scripted' WHERE id = ?",
        (narration, slide_id),
    )
    await db.commit()

    updated = await db.execute("SELECT * FROM slides WHERE id = ?", (slide_id,))
    return dict(await updated.fetchone())


@router.put("/slides/{slide_id}", response_model=SlideOut)
async def update_slide_narration(slide_id: int, data: SlideUpdate):
    db = await get_db()
    if data.narration is not None:
        await db.execute(
            "UPDATE slides SET narration = ? WHERE id = ?",
            (data.narration, slide_id),
        )
        await db.commit()
    row = await db.execute("SELECT * FROM slides WHERE id = ?", (slide_id,))
    slide = await row.fetchone()
    if not slide:
        raise HTTPException(404, "幻灯片不存在")
    return dict(slide)


@router.post("/{project_uuid}/auto-topic")
async def auto_generate_topic(project_uuid: str):
    db = await get_db()
    row = await db.execute("SELECT id FROM projects WHERE uuid = ?", (project_uuid,))
    project = await row.fetchone()
    if not project:
        raise HTTPException(404, "项目不存在")
    project_id = project["id"]
    slides_cursor = await db.execute(
        "SELECT * FROM slides WHERE project_id = ? ORDER BY slide_number",
        (project_id,),
    )
    slides = [dict(s) for s in await slides_cursor.fetchall()]
    if not slides:
        raise HTTPException(400, "项目没有幻灯片")

    topic = await generate_topic(slides)
    await db.execute(
        "UPDATE projects SET topic = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (topic, project_id),
    )
    await db.commit()
    return {"topic": topic}
