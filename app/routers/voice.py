from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import FileResponse
from app.models.database import get_db
from app.models.schemas import VoiceCreate, VoiceOut
from app.services.voice_clone_service import create_voice_clone, list_voices, delete_voice
from app.config import VOICES_DIR

router = APIRouter(prefix="/api/voices", tags=["voices"])


@router.get("/audio/{name}")
async def get_voice_audio(name: str):
    audio_path = VOICES_DIR / name / "reference.wav"
    if not audio_path.exists():
        raise HTTPException(404, "音频文件不存在")
    return FileResponse(str(audio_path), media_type="audio/wav")


@router.post("/", response_model=VoiceOut)
async def create_voice(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    prompt_text: str = Form(""),
    audio_url: str = Form(""),
    audio: UploadFile = File(None),
):
    if not audio_url and audio is None:
        raise HTTPException(400, "请上传音频文件或提供音频 URL")

    audio_bytes = None
    if audio is not None:
        if not audio.filename or not any(audio.filename.lower().endswith(ext) for ext in [".wav", ".mp3", ".ogg", ".flac"]):
            raise HTTPException(400, "仅支持 wav/mp3/ogg/flac 音频文件")
        audio_bytes = await audio.read()
        if len(audio_bytes) > 10 * 1024 * 1024:
            raise HTTPException(400, "音频文件不能超过 10MB")

    existing = list_voices()
    if any(v["name"] == name for v in existing):
        raise HTTPException(400, f"声音 '{name}' 已存在")

    result = await create_voice_clone(name, audio_bytes, prompt_text, description, audio_url, request)

    db = await get_db()
    await db.execute(
        "INSERT INTO voices (name, description, ref_audio_path, prompt_text) VALUES (?, ?, ?, ?)",
        (result["name"], result["description"], result.get("ref_audio_path", ""), result["prompt_text"]),
    )
    await db.commit()
    return result


@router.get("/", response_model=list[VoiceOut])
async def get_voices():
    voices = list_voices()
    result = []
    for v in voices:
        result.append({
            "id": v.get("voice_id", ""),
            "name": v["name"],
            "description": v.get("description", ""),
            "ref_audio_path": v.get("ref_audio_path", ""),
            "prompt_text": v.get("prompt_text", ""),
            "created_at": "",
        })
    return result


@router.delete("/{name}")
async def remove_voice(name: str):
    if delete_voice(name):
        return {"ok": True}
    raise HTTPException(404, "声音不存在")
