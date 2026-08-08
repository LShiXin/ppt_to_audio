import json
import logging
from pathlib import Path
from typing import Optional
from app.config import VOICES_DIR

logger = logging.getLogger(__name__)


async def create_voice_clone(
    name: str,
    audio_bytes: bytes,
    prompt_text: str,
    description: str = "",
    audio_url: str = "",
    request=None,
) -> dict:
    voice_dir = VOICES_DIR / name
    voice_dir.mkdir(parents=True, exist_ok=True)

    ref_audio_path = ""
    if audio_bytes:
        ref_path = voice_dir / "reference.wav"
        ref_path.write_bytes(audio_bytes)
        ref_audio_path = str(ref_path.relative_to(VOICES_DIR.parent))

    if not audio_bytes and not audio_url:
        raise ValueError("语音克隆需要提供音频文件")

    metadata = {
        "name": name,
        "description": description,
        "prompt_text": prompt_text,
        "voice_id": name,
        "model": "Qwen3-TTS-12Hz-1.7B-Base",
        "audio_url": audio_url,
        "ref_audio_path": ref_audio_path,
    }
    (voice_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False))

    return {"name": name, "description": description, "prompt_text": prompt_text, "voice_id": name, "ref_audio_path": ref_audio_path, "id": name}


def load_voice_prompt(name: str) -> Optional[dict]:
    meta_path = VOICES_DIR / name / "metadata.json"
    if not meta_path.exists():
        return None
    metadata = json.loads(meta_path.read_text())
    return {
        "voice_id": metadata.get("voice_id", ""),
        "audio_url": metadata.get("audio_url", ""),
        "prompt_text": metadata.get("prompt_text", ""),
        "ref_audio_path": metadata.get("ref_audio_path", ""),
    }


def list_voices() -> list[dict]:
    voices = []
    if not VOICES_DIR.exists():
        return voices
    for d in VOICES_DIR.iterdir():
        if d.is_dir():
            meta_path = d / "metadata.json"
            if meta_path.exists():
                voices.append(json.loads(meta_path.read_text()))
    return voices


def delete_voice(name: str) -> bool:
    voice_dir = VOICES_DIR / name
    if voice_dir.exists():
        import shutil
        shutil.rmtree(voice_dir)
        return True
    return False


def load_default_voice_prompt() -> Optional[dict]:
    if not VOICES_DIR.exists():
        return None
    for d in VOICES_DIR.iterdir():
        if d.is_dir():
            meta_path = d / "metadata.json"
            if meta_path.exists():
                metadata = json.loads(meta_path.read_text())
                return {
                    "voice_id": metadata.get("voice_id", ""),
                    "audio_url": metadata.get("audio_url", ""),
                    "prompt_text": metadata.get("prompt_text", ""),
                    "ref_audio_path": metadata.get("ref_audio_path", ""),
                }
    return None
