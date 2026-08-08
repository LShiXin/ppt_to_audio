import asyncio
import logging
import os
import uuid
from typing import Optional, List, Dict
from app.config import (
    OUTPUTS_DIR,
    DASHSCOPE_API_KEY, TTS_API_MODEL, TTS_API_VOICE,
)

os.environ["DASHSCOPE_API_KEY"] = DASHSCOPE_API_KEY

import dashscope
dashscope.api_key = DASHSCOPE_API_KEY
dashscope.base_websocket_api_url = "wss://dashscope.aliyuncs.com/api-ws/v1/inference"
dashscope.base_http_api_url = "https://dashscope.aliyuncs.com/api/v1"

from dashscope.audio.tts_v2 import SpeechSynthesizer

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY = 1


async def _call_tts(
    text: str,
    voice: str,
    model: str = None,
    speech_rate: float = 1.0,
    seed: int = 0,
    additional_params: dict = None,
) -> bytes:
    loop = asyncio.get_running_loop()

    def _do():
        synthesizer = SpeechSynthesizer(
            model=model or TTS_API_MODEL,
            voice=voice,
            speech_rate=speech_rate,
            seed=seed,
            additional_params=additional_params,
        )
        return synthesizer.call(text)

    try:
        audio = await loop.run_in_executor(None, _do)
        if audio is None:
            raise RuntimeError("TTS 返回空结果，请检查声线名称或模型是否正确")
        return audio
    except RuntimeError:
        raise
    except TimeoutError:
        pass

    for attempt in range(1, MAX_RETRIES):
        logger.warning("TTS WebSocket 连接超时，重试 %d/%d", attempt + 1, MAX_RETRIES)
        await asyncio.sleep(RETRY_DELAY)
        try:
            audio = await loop.run_in_executor(None, _do)
            if audio is not None:
                return audio
            raise RuntimeError("TTS 返回空结果，请检查声线名称或模型是否正确")
        except RuntimeError:
            raise
        except TimeoutError:
            continue

    raise RuntimeError(f"TTS WebSocket 连接超时（已重试 {MAX_RETRIES} 次），请检查网络或稍后重试")


def _resolve_voice_and_model(
    speaker: str,
    voice: str,
    voice_clone_prompt,
    model: str,
) -> tuple[str, str, dict]:
    """Resolve voice, model, and additional_params from clone prompt."""
    extra_params = None

    if voice_clone_prompt:
        if isinstance(voice_clone_prompt, dict):
            clone_model = model or "cosyvoice-v3.5-plus"
            clone_voice = "longxiaochun"
            extra_params = {}
            if voice_clone_prompt.get("voice_id"):
                clone_voice = voice_clone_prompt["voice_id"]
            else:
                clone_voice = "_clone"
            if voice_clone_prompt.get("audio_url"):
                extra_params["prompt_audio_url"] = voice_clone_prompt["audio_url"]
                extra_params["prompt_text"] = voice_clone_prompt.get("prompt_text", "")
            return speaker or voice or clone_voice, clone_model, extra_params
        elif isinstance(voice_clone_prompt, str):
            return speaker or voice or voice_clone_prompt, model or "cosyvoice-v3.5-plus", None
        elif isinstance(voice_clone_prompt, list) and len(voice_clone_prompt) > 0:
            return speaker or voice or voice_clone_prompt[0], model or "cosyvoice-v3.5-plus", None

    if model and "cosyvoice-v3.5-plus" in model:
        logger.warning("cosyvoice-v3.5-plus 需配合自定义声线使用，已回退到 cosyvoice-v1")
        model = "cosyvoice-v1"

    return speaker or voice or TTS_API_VOICE, model or TTS_API_MODEL, None


async def generate_audio(
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
) -> str:
    if output_filename is None:
        output_filename = f"{uuid.uuid4().hex}.mp3"

    output_dir = OUTPUTS_DIR / "audio"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / output_filename

    api_voice, api_model, extra_params = _resolve_voice_and_model(
        speaker, voice, voice_clone_prompt, model,
    )

    rate = speed if speed is not None else 1.0
    s = seed if seed is not None else 0

    logger.info("TTS voice=%s model=%s text_len=%d speed=%.1f seed=%d extra=%s",
                api_voice, api_model or TTS_API_MODEL, len(text), rate, s,
                bool(extra_params))

    audio_bytes = await _call_tts(
        text=text, voice=api_voice, model=api_model,
        speech_rate=rate, seed=s, additional_params=extra_params,
    )
    output_path.write_bytes(audio_bytes)
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
) -> str:
    from app.services.tts_engine import segment_text

    segments = segment_text(text)
    if not segments or len(segments) <= 1:
        return await generate_audio(
            text=text,
            output_filename=output_filename,
            speaker=speaker,
            voice=voice,
            speed=speed,
            model=model,
            voice_clone_prompt=voice_clone_prompt,
            seed=seed,
        )

    if output_filename is None:
        output_filename = f"{uuid.uuid4().hex}.mp3"

    output_dir = OUTPUTS_DIR / "audio"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / output_filename

    api_voice, api_model, extra_params = _resolve_voice_and_model(
        speaker, voice, voice_clone_prompt, model,
    )

    rate = speed if speed is not None else 1.0
    s = seed if seed is not None else 0

    logger.info("TTS (segmented) voice=%s model=%s segments=%d speed=%.1f",
                api_voice, api_model or TTS_API_MODEL, len(segments), rate)

    import io
    from pydub import AudioSegment

    segments_audio: list[AudioSegment] = []
    for i, seg in enumerate(segments):
        logger.debug("TTS segment %d/%d: %s", i + 1, len(segments), seg[:50])
        seg_bytes = await _call_tts(
            text=seg, voice=api_voice, model=api_model,
            speech_rate=rate, seed=s, additional_params=extra_params,
        )
        segments_audio.append(AudioSegment.from_file(io.BytesIO(bytes(seg_bytes))))

    silence = AudioSegment.silent(duration=300)
    combined = segments_audio[0]
    for aud in segments_audio[1:]:
        combined += silence + aud

    combined.export(str(output_path), format="mp3", bitrate="192k")
    return str(output_path.relative_to(OUTPUTS_DIR))
