import asyncio
import io
import logging
import time
import uuid
from pathlib import Path
from typing import Optional

import requests
import soundfile as sf
from pydub import AudioSegment

from app.config import (
    OUTPUTS_DIR,
    TTS_CUSTOM_VOICE_SPEAKERS,
    VLLM_OMNI_BASE_URL,
    VLLM_OMNI_VOICE_NAME,
    VLLM_OMNI_GPU_COOLDOWN,
    VLLM_OMNI_MODEL,
)

logger = logging.getLogger(__name__)

SPEECH_ENDPOINT = f"{VLLM_OMNI_BASE_URL}/v1/audio/speech"
VOICES_ENDPOINT = f"{VLLM_OMNI_BASE_URL}/v1/audio/voices"
REQUEST_TIMEOUT = 120
WARMUP_TEXT = "初始化。"
WARMUP_TIMEOUT = 300

_inference_lock = asyncio.Lock()
_voice_clone_state: dict[str, str] = {}
_last_inference_time = 0.0
_SEGMENT_MAX_CHARS = 80


def _is_base_model() -> bool:
    from app.services.vllm_process import get_current_model
    return get_current_model() == "base"


def _segment_text(text: str) -> list[str]:
    parts = text.replace("\n", "。").replace("！", "。").replace("？", "。").split("。")
    parts = [p.strip() for p in parts if p.strip()]
    if not parts:
        return [text.strip()]
    result = []
    for p in parts:
        if len(p) > _SEGMENT_MAX_CHARS:
            subs = p.replace("，", "，").replace("：", "，").split("，")
            subs = [s.strip() for s in subs if s.strip()]
            result.extend(subs)
        else:
            result.append(p)
    return result


def is_model_loaded() -> bool:
    try:
        resp = requests.get(f"{VLLM_OMNI_BASE_URL}/health", timeout=5)
        return resp.status_code == 200
    except Exception:
        return False


def unload_all_models():
    pass


def clear_tts_cache():
    pass


def _upload_voice(ref_audio_path: str, ref_text: str, voice_name: str) -> bool:
    audio_path = Path(ref_audio_path)
    if not audio_path.exists():
        raise FileNotFoundError(f"Reference audio not found: {ref_audio_path}")

    suffix = audio_path.suffix.lower()
    mime_map = {".wav": "audio/wav", ".mp3": "audio/mpeg", ".flac": "audio/flac"}
    mime_type = mime_map.get(suffix, "audio/wav")

    logger.info("Uploading voice '%s' from %s", voice_name, ref_audio_path)
    with open(audio_path, "rb") as f:
        files = {"audio_sample": (audio_path.name, f, mime_type)}
        data = {"name": voice_name, "consent": "default"}
        if ref_text:
            data["ref_text"] = ref_text
        resp = requests.post(VOICES_ENDPOINT, files=files, data=data, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()

    _warmup_voice(voice_name)
    return True


def _warmup_voice(voice_name: str) -> None:
    payload = {"input": WARMUP_TEXT, "voice": voice_name, "response_format": "wav"}
    resp = requests.post(SPEECH_ENDPOINT, json=payload, timeout=WARMUP_TIMEOUT)
    resp.raise_for_status()
    logger.info("Voice '%s' embedding warmup done (%d bytes)", voice_name, len(resp.content))


def _ensure_voice_uploaded(ref_audio_path: str, ref_text: str, voice_name: str) -> str:
    global _voice_clone_state
    key = f"{ref_audio_path}:{voice_name}"
    if key not in _voice_clone_state:
        _upload_voice(ref_audio_path, ref_text, voice_name)
        _voice_clone_state[key] = voice_name
    return _voice_clone_state[key]


def _call_speech_api(
    text: str,
    voice: str,
    language: str = "Auto",
    instruct: str = "",
    temperature: float = 1.0,
    speed: float = 1.0,
    seed: Optional[int] = None,
) -> bytes:
    global _last_inference_time

    payload = {
        "input": text.strip(),
        "voice": voice,
        "response_format": "wav",
        "speed": speed,
    }
    if language and language != "Auto":
        payload["language"] = language
    if instruct:
        payload["instructions"] = instruct
    if seed is not None:
        payload["seed"] = seed
    if temperature != 1.0:
        payload.setdefault("extra_params", {})["temperature"] = temperature

    try:
        resp = requests.post(SPEECH_ENDPOINT, json=payload, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        detail = ""
        try:
            detail = resp.json()
        except Exception:
            detail = resp.text[:200]
        raise RuntimeError(f"TTS request failed (HTTP {resp.status_code}): {detail}") from e
    _last_inference_time = time.time()
    return resp.content


def _resolve_speaker(speaker: Optional[str]) -> str:
    if speaker:
        speaker_lower = speaker.lower()
        known = {s["name"]: s for s in TTS_CUSTOM_VOICE_SPEAKERS}
        if speaker_lower in known:
            return known[speaker_lower]["name"]
    return "vivian"  # fallback to default preset voice


async def generate_audio_custom_voice(
    text: str,
    output_filename: Optional[str] = None,
    speaker: str = "vivian",
    language: str = "Auto",
    instruct: str = "",
    temperature: float = 1.0,
    speed: float = 1.0,
) -> str:
    if output_filename is None:
        output_filename = f"{uuid.uuid4().hex}.wav"
    output_dir = OUTPUTS_DIR / "audio"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / output_filename

    voice = _resolve_speaker(speaker)
    logger.info("vLLM-Omni CustomVoice: speaker=%s lang=%s temp=%.2f text_len=%d",
                voice, language, temperature, len(text))

    async with _inference_lock:
        loop = asyncio.get_running_loop()
        audio_bytes = await loop.run_in_executor(
            None,
            lambda: _call_speech_api(text, voice, language, instruct, temperature, speed),
        )

    output_path.write_bytes(audio_bytes)
    _gpu_cooldown()
    return str(output_path.relative_to(OUTPUTS_DIR))


async def generate_audio_voice_clone(
    text: str,
    ref_audio_path: str,
    ref_text: str,
    output_filename: Optional[str] = None,
    language: str = "Auto",
    temperature: float = 1.0,
    speed: float = 1.0,
) -> str:
    if output_filename is None:
        output_filename = f"{uuid.uuid4().hex}.wav"
    output_dir = OUTPUTS_DIR / "audio"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / output_filename

    audio_stem = Path(ref_audio_path).stem
    voice_name = f"clone_{audio_stem}"

    logger.info("vLLM-Omni VoiceClone: ref=%s temp=%.2f text_len=%d",
                ref_audio_path, temperature, len(text))

    async with _inference_lock:
        loop = asyncio.get_running_loop()
        voice_name = await loop.run_in_executor(
            None,
            lambda: _ensure_voice_uploaded(ref_audio_path, ref_text, voice_name),
        )
        audio_bytes = await loop.run_in_executor(
            None,
            lambda: _call_speech_api(text, voice_name, language, "", temperature, speed),
        )

    output_path.write_bytes(audio_bytes)
    _gpu_cooldown()
    return str(output_path.relative_to(OUTPUTS_DIR))


async def generate_audio_with_segmentation(
    text: str,
    output_filename: Optional[str] = None,
    speaker: Optional[str] = None,
    voice: Optional[str] = None,
    speed: Optional[float] = None,
    model: Optional[str] = None,
    response_format: Optional[str] = None,
    voice_design: Optional[str] = None,
    voice_clone_prompt=None,
    temperature: Optional[float] = None,
    seed: Optional[int] = None,
    language: str = "Auto",
    instruct: str = "",
) -> str:
    temp = temperature if temperature is not None else 1.0
    spd = speed if speed is not None else 1.0

    segments = _segment_text(text)
    if not segments:
        segments = [text]

    if output_filename is None:
        output_filename = f"{uuid.uuid4().hex}.wav"

    output_dir = OUTPUTS_DIR / "audio"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / output_filename

    is_clone = voice_clone_prompt and isinstance(voice_clone_prompt, dict)
    if is_clone and not _is_base_model():
        logger.warning(
            "vLLM-Omni model=CustomVoice does not support voice clone; "
            "falling back to preset speaker. Set VLLM_OMNI_MODEL=base for voice cloning."
        )
        is_clone = False

    if _is_base_model() and not is_clone:
        from app.services.voice_clone_service import load_default_voice_prompt
        default_prompt = load_default_voice_prompt()
        if default_prompt:
            voice_clone_prompt = default_prompt
            is_clone = True
            logger.info("vLLM-Omni base model: auto-selected default clone voice")

    logger.info("vLLM-Omni TTS: segments=%d speaker=%s clone=%s model=%s temp=%.2f",
                len(segments), speaker, is_clone, VLLM_OMNI_MODEL, temp)

    if is_clone:
        ref_audio = voice_clone_prompt.get("ref_audio_path", "")
        ref_text = voice_clone_prompt.get("prompt_text", "")
        from app.config import BASE_DIR
        full_audio_path = str(BASE_DIR / ref_audio)
        audio_stem = Path(full_audio_path).stem
        voice_name = f"clone_{audio_stem}"
    else:
        full_audio_path = ""
        ref_text = ""
        voice_name = _resolve_speaker(speaker)

    async with _inference_lock:
        loop = asyncio.get_running_loop()

        if is_clone:
            voice_name = await loop.run_in_executor(
                None,
                lambda: _ensure_voice_uploaded(full_audio_path, ref_text, voice_name),
            )

        segments_audio: list[AudioSegment] = []
        sample_rate = 24000

        for idx, seg in enumerate(segments):
            instruct_final = instruct
            if voice_design and idx == 0:
                instruct_final = voice_design

            audio_bytes = await loop.run_in_executor(
                None,
                lambda s=seg, vn=voice_name, ins=instruct_final:
                    _call_speech_api(s, vn, language, ins, temp, spd, seed),
            )

            wav, sr = sf.read(io.BytesIO(audio_bytes))
            sample_rate = sr
            audio_seg = AudioSegment(
                data=(wav * 32767).astype("int16").tobytes(),
                sample_width=2,
                frame_rate=sr,
                channels=1,
            )
            segments_audio.append(audio_seg)
            _gpu_cooldown()

    silence = AudioSegment.silent(duration=300)
    combined = AudioSegment.empty()
    for i, aud in enumerate(segments_audio):
        if i > 0:
            combined += silence
        combined += aud

    combined.export(str(output_path), format="wav")
    return str(output_path.relative_to(OUTPUTS_DIR))


def _gpu_cooldown():
    time.sleep(VLLM_OMNI_GPU_COOLDOWN)
