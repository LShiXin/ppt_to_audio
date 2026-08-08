import os
import json
import uuid
from typing import Optional
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from app.models.database import get_db
from app.models.schemas import ProjectCreate, ProjectUpdate, ProjectOut, SlideOut, ReferenceFileOut
from app.services.ppt_parser import parse_pptx, save_upload, extract_reference_text, extract_slide_images
from app.services.pdf_parser import parse_pdf, extract_pdf_images
from app.config import UPLOADS_DIR, SUPPORTED_REFERENCE_FORMATS
from pathlib import Path

router = APIRouter(prefix="/api/projects", tags=["projects"])


async def _resolve_project_id(db, project_uuid: str) -> int:
    row = await db.execute("SELECT id FROM projects WHERE uuid = ?", (project_uuid,))
    project = await row.fetchone()
    if not project:
        raise HTTPException(404, "项目不存在")
    return project["id"]


@router.post("/", response_model=ProjectOut)
async def create_project(data: ProjectCreate):
    db = await get_db()
    project_uuid = uuid.uuid4().hex
    cursor = await db.execute(
        "INSERT INTO projects (name, topic, uuid) VALUES (?, ?, ?)",
        (data.name, data.topic, project_uuid),
    )
    await db.commit()
    row = await db.execute("SELECT * FROM projects WHERE id = ?", (cursor.lastrowid,))
    project = await row.fetchone()
    return dict(project)


@router.get("/", response_model=list[ProjectOut])
async def list_projects():
    db = await get_db()
    cursor = await db.execute("SELECT * FROM projects ORDER BY updated_at DESC")
    return [dict(row) for row in await cursor.fetchall()]


@router.get("/{project_uuid}", response_model=ProjectOut)
async def get_project(project_uuid: str):
    db = await get_db()
    project_id = await _resolve_project_id(db, project_uuid)
    row = await db.execute("SELECT * FROM projects WHERE id = ?", (project_id,))
    return dict(await row.fetchone())


@router.put("/{project_uuid}", response_model=ProjectOut)
async def update_project(project_uuid: str, data: ProjectUpdate):
    db = await get_db()
    project_id = await _resolve_project_id(db, project_uuid)
    updates = {}
    if data.name is not None:
        updates["name"] = data.name
    if data.topic is not None:
        updates["topic"] = data.topic
    if updates:
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [project_id]
        await db.execute(
            f"UPDATE projects SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            values,
        )
        await db.commit()
    row = await db.execute("SELECT * FROM projects WHERE id = ?", (project_id,))
    return dict(await row.fetchone())


@router.delete("/{project_uuid}")
async def delete_project(project_uuid: str):
    db = await get_db()
    project_id = await _resolve_project_id(db, project_uuid)
    await db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    await db.commit()
    import shutil
    proj_dir = UPLOADS_DIR / str(project_id)
    if proj_dir.exists():
        shutil.rmtree(proj_dir)
    return {"ok": True}


@router.post("/{project_uuid}/upload-pptx")
async def upload_pptx(project_uuid: str, file: UploadFile = File(...)):
    if not file.filename or not file.filename.endswith(".pptx"):
        raise HTTPException(400, "仅支持 .pptx 文件")

    db = await get_db()
    project_id = await _resolve_project_id(db, project_uuid)

    content = await file.read()
    if len(content) > 100 * 1024 * 1024:
        raise HTTPException(400, "文件过大")

    file_path = save_upload(content, file.filename, project_id)
    full_path = UPLOADS_DIR / file_path

    slides = parse_pptx(str(full_path))

    images_dir = UPLOADS_DIR / str(project_id) / "slide_images"
    extract_slide_images(str(full_path), str(images_dir))

    await db.execute(
        "UPDATE projects SET ppt_filename = ?, status = 'parsed', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (file.filename, project_id),
    )
    await db.execute("DELETE FROM slides WHERE project_id = ?", (project_id,))
    for s in slides:
        await db.execute(
            "INSERT INTO slides (project_id, slide_number, title, content, notes) VALUES (?, ?, ?, ?, ?)",
            (project_id, s["slide_number"], s["title"], s["content"], s["notes"]),
        )
    await db.commit()
    return {"slides": slides, "filename": file.filename}


@router.post("/{project_uuid}/upload-pdf")
async def upload_pdf(project_uuid: str, file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "仅支持 .pdf 文件")

    db = await get_db()
    project_id = await _resolve_project_id(db, project_uuid)

    content = await file.read()
    if len(content) > 100 * 1024 * 1024:
        raise HTTPException(400, "文件过大")

    file_path = save_upload(content, file.filename, project_id)
    full_path = UPLOADS_DIR / file_path

    images_dir = UPLOADS_DIR / str(project_id) / "slide_images"
    extract_pdf_images(str(full_path), str(images_dir))

    try:
        slides = parse_pdf(str(full_path), str(images_dir))
    except RuntimeError as e:
        raise HTTPException(400, str(e))

    await db.execute(
        "UPDATE projects SET ppt_filename = ?, status = 'parsed', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (file.filename, project_id),
    )
    await db.execute("DELETE FROM slides WHERE project_id = ?", (project_id,))
    for s in slides:
        await db.execute(
            "INSERT INTO slides (project_id, slide_number, title, content, notes) VALUES (?, ?, ?, ?, ?)",
            (project_id, s["slide_number"], s["title"], s["content"], s["notes"]),
        )
    await db.commit()
    return {"slides": slides, "filename": file.filename}


@router.get("/{project_uuid}/pdf-file")
async def get_pdf_file(project_uuid: str):
    db = await get_db()
    project_id = await _resolve_project_id(db, project_uuid)
    project_dir = UPLOADS_DIR / str(project_id)
    pdf_files = sorted(
        project_dir.glob("*.pdf"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not pdf_files:
        raise HTTPException(404, "PDF文件不存在")
    return FileResponse(str(pdf_files[0]), media_type="application/pdf")


@router.post("/{project_uuid}/reparse")
async def reparse_slides(project_uuid: str):
    db = await get_db()
    project_id = await _resolve_project_id(db, project_uuid)
    project_row = await db.execute("SELECT * FROM projects WHERE id = ?", (project_id,))
    project = await project_row.fetchone()
    if not project["ppt_filename"]:
        raise HTTPException(400, "项目未上传PPT/PDF文件")

    ppt_files = list((UPLOADS_DIR / str(project_id)).glob("*.pptx"))
    pdf_files = list((UPLOADS_DIR / str(project_id)).glob("*.pdf"))
    all_files = ppt_files + pdf_files
    if not all_files:
        raise HTTPException(400, "文件不存在，请重新上传")

    full_path = str(all_files[0])
    ext = Path(full_path).suffix.lower()
    if ext == ".pdf":
        images_dir = str(UPLOADS_DIR / str(project_id) / "slide_images")
        slides = parse_pdf(full_path, images_dir)
    else:
        slides = parse_pptx(full_path)

    await db.execute("DELETE FROM slides WHERE project_id = ?", (project_id,))
    for s in slides:
        await db.execute(
            "INSERT INTO slides (project_id, slide_number, title, content, notes) VALUES (?, ?, ?, ?, ?)",
            (project_id, s["slide_number"], s["title"], s["content"], s["notes"]),
        )
    await db.execute(
        "UPDATE projects SET status = 'parsed', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (project_id,),
    )
    await db.commit()
    return {"slides": slides}


@router.get("/{project_uuid}/slides", response_model=list[SlideOut])
async def get_slides(project_uuid: str):
    db = await get_db()
    project_id = await _resolve_project_id(db, project_uuid)
    cursor = await db.execute(
        "SELECT * FROM slides WHERE project_id = ? ORDER BY slide_number", (project_id,)
    )
    return [dict(row) for row in await cursor.fetchall()]


@router.get("/{project_uuid}/resume", response_model=ProjectOut)
async def resume_project(project_uuid: str):
    db = await get_db()
    project_id = await _resolve_project_id(db, project_uuid)
    await db.execute(
        "UPDATE projects SET status = 'draft', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (project_id,),
    )
    await db.commit()
    row = await db.execute("SELECT * FROM projects WHERE id = ?", (project_id,))
    return dict(await row.fetchone())


@router.post("/{project_uuid}/reference-files")
async def upload_reference(project_uuid: str, file: UploadFile = File(...)):
    ext = Path(file.filename).suffix.lower()
    if ext not in SUPPORTED_REFERENCE_FORMATS:
        raise HTTPException(400, f"不支持的文件格式: {ext}，仅支持 {SUPPORTED_REFERENCE_FORMATS}")

    db = await get_db()
    project_id = await _resolve_project_id(db, project_uuid)

    content = await file.read()
    file_path = save_upload(content, file.filename, project_id)
    full_path = UPLOADS_DIR / file_path

    ref_text = extract_reference_text(str(full_path))

    await db.execute(
        "INSERT INTO reference_files (project_id, filename, file_path, content) VALUES (?, ?, ?, ?)",
        (project_id, file.filename, file_path, ref_text),
    )
    await db.commit()
    return {"filename": file.filename, "content_preview": ref_text[:200]}


@router.get("/{project_uuid}/reference-files", response_model=list[ReferenceFileOut])
async def list_references(project_uuid: str):
    db = await get_db()
    project_id = await _resolve_project_id(db, project_uuid)
    cursor = await db.execute(
        "SELECT * FROM reference_files WHERE project_id = ?", (project_id,)
    )
    return [dict(row) for row in await cursor.fetchall()]


@router.delete("/{project_uuid}/reference-files/{file_id}")
async def delete_reference(project_uuid: str, file_id: int):
    db = await get_db()
    project_id = await _resolve_project_id(db, project_uuid)
    row = await db.execute(
        "SELECT file_path FROM reference_files WHERE id = ? AND project_id = ?",
        (file_id, project_id),
    )
    ref = await row.fetchone()
    if ref:
        full_path = UPLOADS_DIR / ref["file_path"]
        if full_path.exists():
            full_path.unlink()
        await db.execute("DELETE FROM reference_files WHERE id = ?", (file_id,))
        await db.commit()
    return {"ok": True}


@router.get("/{project_uuid}/slide-image/{slide_number}")
async def get_slide_image(project_uuid: str, slide_number: int):
    db = await get_db()
    project_id = await _resolve_project_id(db, project_uuid)
    image_path = UPLOADS_DIR / str(project_id) / "slide_images" / f"slide_{slide_number}.png"
    if not image_path.exists():
        raise HTTPException(404, "幻灯片图片不存在")
    return FileResponse(str(image_path), media_type="image/png")