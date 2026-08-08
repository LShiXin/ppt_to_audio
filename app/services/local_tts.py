import asyncio
import gc
import io
import logging
import re
import time
import uuid
from typing import Optional

import numpy as np
import soundfile as sf
import torch
from pydub import AudioSegment

from app.config import (
    OUTPUTS_DIR,
    TTS_BASE_MODEL_PATH,
    TTS_CUSTOM_VOICE_MODEL_PATH,
    TTS_DEVICE,
    TTS_DTYPE,
)

logger = logging.getLogger(__name__)

_custom_voice_model = None
_base_model = None
_model_load_lock = asyncio.Lock()
_inference_lock = asyncio.Lock()
_voice_clone_prompt_cache: dict = {}

_last_inference_time = 0.0

_MAX_BATCH_SEGMENTS = 12
_MAX_CHARS_PER_BATCH = 500
_CLONE_MAX_SEGMENTS = 4
_CLONE_MAX_CHARS = 200


def _get_dtype():
    if TTS_DTYPE == "float16":
        return torch.float16
    return torch.bfloat16


def _build_load_kwargs() -> dict:
    return {
        "device_map": TTS_DEVICE,
        "dtype": _get_dtype(),
    }


def _force_cuda_cleanup():
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.synchronize()
        torch.cuda.empty_cache()
        torch.cuda.ipc_collect()


def _force_cuda_cleanup_light():
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.synchronize()
        torch.cuda.empty_cache()


def _unload_model(model_name: str):
    global _custom_voice_model, _base_model, _voice_clone_prompt_cache

    target = None
    if model_name == "custom_voice" and _custom_voice_model is not None:
        target = _custom_voice_model
        _custom_voice_model = None
    elif model_name == "base" and _base_model is not None:
        target = _base_model
        _base_model = None

    if target is not None:
        logger.info("Unloading %s model", model_name)
        del target

    _voice_clone_prompt_cache.clear()
    _force_cuda_cleanup()
    torch.cuda.reset_peak_memory_stats()
    torch.cuda.reset_accumulated_memory_stats()


def unload_all_models():
    global _custom_voice_model, _base_model, _voice_clone_prompt_cache
    logger.info("Unloading all TTS models")

    _base_model = None
    _custom_voice_model = None
    _voice_clone_prompt_cache.clear()
    _force_cuda_cleanup()
    torch.cuda.reset_peak_memory_stats()
    torch.cuda.reset_accumulated_memory_stats()
    logger.info("All TTS models unloaded")


def is_model_loaded() -> bool:
    return _base_model is not None or _custom_voice_model is not None


def _load_custom_voice_model():
    global _custom_voice_model, _base_model
    if _custom_voice_model is None:
        if _base_model is not None:
            _unload_model("base")
        from qwen_tts import Qwen3TTSModel
        logger.info("Loading CustomVoice model from %s", TTS_CUSTOM_VOICE_MODEL_PATH)
        _custom_voice_model = Qwen3TTSModel.from_pretrained(
            TTS_CUSTOM_VOICE_MODEL_PATH,
            **_build_load_kwargs(),
        )
        logger.info("CustomVoice model loaded on %s", TTS_DEVICE)
    return _custom_voice_model


def _load_base_model():
    global _base_model, _custom_voice_model
    if _base_model is None:
        if _custom_voice_model is not None:
            _unload_model("custom_voice")
        from qwen_tts import Qwen3TTSModel
        logger.info("Loading Base model from %s", TTS_BASE_MODEL_PATH)
        _base_model = Qwen3TTSModel.from_pretrained(
            TTS_BASE_MODEL_PATH,
            **_build_load_kwargs(),
        )
        logger.info("Base model loaded on %s", TTS_DEVICE)
    return _base_model


def clear_tts_cache():
    _force_cuda_cleanup_light()
    logger.info("TTS cache cleared")


def _numpy_to_audiosegment(wav: np.ndarray, sr: int) -> AudioSegment:
    audio_bytes = (wav * 32767).astype(np.int16).tobytes()
    return AudioSegment(
        data=audio_bytes,
        sample_width=2,
        frame_rate=sr,
        channels=1,
    )


def _generate_custom_voice_sync(
    text: str,
    speaker: str,
    language: str = "Auto",
    instruct: str = "",
    temperature: float = 1.0,
    speed: float = 1.0,
) -> bytes:
    model = _load_custom_voice_model()
    kwargs = {
        "text": text,
        "language": language,
        "speaker": speaker,
        "temperature": temperature,
    }
    if instruct:
        kwargs["instruct"] = instruct
    with torch.inference_mode():
        wavs, sr = model.generate_custom_voice(**kwargs)
    buf = io.BytesIO()
    sf.write(buf, wavs[0], sr, format="WAV")
    return buf.getvalue()


def _generate_custom_voice_batch_sync(
    texts: list[str],
    speaker: str,
    language: str = "Auto",
    instruct: str = "",
    temperature: float = 1.0,
    speed: float = 1.0,
) -> tuple[list[np.ndarray], int]:
    model = _load_custom_voice_model()
    kwargs = {
        "text": texts,
        "language": language,
        "speaker": speaker,
        "temperature": temperature,
    }
    if instruct:
        kwargs["instruct"] = instruct
    with torch.inference_mode():
        wavs, sr = model.generate_custom_voice(**kwargs)
    _force_cuda_cleanup_light()
    return list(wavs), sr


def _get_or_create_clone_prompt(ref_audio: str, ref_text: str):
    global _voice_clone_prompt_cache
    cache_key = ref_audio
    if cache_key not in _voice_clone_prompt_cache:
        model = _load_base_model()
        with torch.inference_mode():
            _voice_clone_prompt_cache[cache_key] = model.create_voice_clone_prompt(
                ref_audio=ref_audio,
                ref_text=ref_text,
                x_vector_only_mode=False,
            )
        logger.info("Created voice clone prompt for %s", ref_audio)
    return _voice_clone_prompt_cache[cache_key]


def _generate_voice_clone_sync(
    text: str,
    voice_clone_prompt_items,
    language: str = "Auto",
    temperature: float = 1.0,
    speed: float = 1.0,
) -> bytes:
    model = _load_base_model()
    with torch.inference_mode():
        wavs, sr = model.generate_voice_clone(
            text=text,
            language=language,
            voice_clone_prompt=voice_clone_prompt_items,
            temperature=temperature,
        )
    buf = io.BytesIO()
    sf.write(buf, wavs[0], sr, format="WAV")
    return buf.getvalue()


def _generate_voice_clone_batch_sync(
    texts: list[str],
    voice_clone_prompt_items,
    language: str = "Auto",
    temperature: float = 1.0,
    speed: float = 1.0,
) -> tuple[list[np.ndarray], int]:
    model = _load_base_model()
    with torch.inference_mode():
        wavs, sr = model.generate_voice_clone(
            text=texts,
            language=language,
            voice_clone_prompt=voice_clone_prompt_items,
            temperature=temperature,
        )
    _force_cuda_cleanup_light()
    return list(wavs), sr


_PRIMARY_SEP = "。！？\n"
_SECONDARY_SEP = "，："
_SEGMENT_MAX_CHARS = 80


def _segment_text_smart(text: str) -> list[str]:
    if not text.strip():
        return []

    parts = re.split(rf"(?<=[{re.escape(_PRIMARY_SEP)}])", text)
    parts = [p.strip() for p in parts if p.strip()]
    if not parts:
        return [text.strip()]

    result = []
    for p in parts:
        if len(p) > _SEGMENT_MAX_CHARS:
            sub = re.split(rf"(?<=[{re.escape(_SECONDARY_SEP)}])", p)
            sub = [s.strip() for s in sub if s.strip()]
            result.extend(sub)
        else:
            result.append(p)
    return result


def _chunk_segments(segments: list[str], is_clone: bool = False) -> list[list[str]]:
    max_segs = _CLONE_MAX_SEGMENTS if is_clone else _MAX_BATCH_SEGMENTS
    max_chars = _CLONE_MAX_CHARS if is_clone else _MAX_CHARS_PER_BATCH

    chunks = []
    current_chunk = []
    current_chars = 0

    for seg in segments:
        if len(current_chunk) >= max_segs or (
            current_chunk and current_chars + len(seg) > max_chars
        ):
            chunks.append(current_chunk)
            current_chunk = []
            current_chars = 0
        current_chunk.append(seg)
        current_chars += len(seg)

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


async def _generate_batched_segments(
    segments: list[str],
    speaker: str,
    voice_clone_prompt,
    language: str,
    instruct: str,
    temp: float,
    spd: float,
    is_clone: bool = False,
) -> tuple[list[np.ndarray], int]:
    global _last_inference_time
    loop = asyncio.get_running_loop()

    chunks = _chunk_segments(segments, is_clone=is_clone)

    all_wavs = []
    sr = 0

    for batch_idx, chunk in enumerate(chunks):
        logger.debug("Processing batch %d/%d: %d segments, %d chars",
                      batch_idx + 1, len(chunks), len(chunk),
                      sum(len(s) for s in chunk))

        if is_clone:
            try:
                wavs, sr = await loop.run_in_executor(
                    None,
                    lambda c=chunk: _generate_voice_clone_batch_sync(
                        c, voice_clone_prompt, language, temp, spd),
                )
            except RuntimeError as e:
                if "Sizes of tensors must match" in str(e):
                    logger.warning("Batch inference failed, falling back to sequential for chunk")
                    wavs = []
                    sr = 0
                    for seg in chunk:
                        wav_bytes = await loop.run_in_executor(
                            None,
                            lambda s=seg: _generate_voice_clone_sync(
                                s, voice_clone_prompt, language, temp, spd),
                        )
                        w, r = sf.read(io.BytesIO(wav_bytes))
                        wavs.append(w)
                        sr = r
                        _force_cuda_cleanup_light()
                else:
                    raise
        else:
            spk = speaker or "vivian"
            try:
                wavs, sr = await loop.run_in_executor(
                    None,
                    lambda c=chunk: _generate_custom_voice_batch_sync(
                        c, spk, language, instruct, temp, spd),
                )
            except RuntimeError as e:
                if "Sizes of tensors must match" in str(e):
                    logger.warning("Batch inference failed, falling back to sequential for chunk")
                    wavs = []
                    sr = 0
                    for seg in chunk:
                        wav_bytes = await loop.run_in_executor(
                            None,
                            lambda s=seg: _generate_custom_voice_sync(
                                s, spk, language, instruct, temp, spd),
                        )
                        w, r = sf.read(io.BytesIO(wav_bytes))
                        wavs.append(w)
                        sr = r
                        _force_cuda_cleanup_light()
                else:
                    raise

        all_wavs.extend(wavs)

    _last_inference_time = time.time()
    return all_wavs, sr


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

    segments = _segment_text_smart(text)
    if not segments:
        segments = [text]

    if len(segments) <= 1:
        async with _inference_lock:
            return await _generate_single(
                text=text,
                output_filename=output_filename,
                speaker=speaker,
                voice_clone_prompt=voice_clone_prompt,
                temperature=temp,
                speed=spd,
                language=language,
                instruct=instruct,
            )

    if output_filename is None:
        output_filename = f"{uuid.uuid4().hex}.wav"

    output_dir = OUTPUTS_DIR / "audio"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / output_filename

    is_clone = voice_clone_prompt and isinstance(voice_clone_prompt, dict)
    logger.info("Local TTS (batch segments) segments=%d speaker=%s temp=%.2f text_len=%d",
                len(segments), speaker, temp, len(text))

    if is_clone:
        ref_audio = voice_clone_prompt.get("ref_audio_path", "")
        ref_text = voice_clone_prompt.get("prompt_text", "")
        from app.config import BASE_DIR
        full_audio_path = str(BASE_DIR / ref_audio)
        prompt_items = _get_or_create_clone_prompt(full_audio_path, ref_text)
    else:
        prompt_items = None

    async with _inference_lock:
        wavs, sr = await _generate_batched_segments(
            segments=segments,
            speaker=speaker or "vivian",
            voice_clone_prompt=prompt_items if is_clone else voice_clone_prompt,
            language=language,
            instruct=instruct,
            temp=temp,
            spd=spd,
            is_clone=is_clone,
        )

    segments_audio: list[AudioSegment] = []
    for wav in wavs:
        segments_audio.append(_numpy_to_audiosegment(wav, sr))

    silence = AudioSegment.silent(duration=300)
    combined = AudioSegment.empty()
    for i, aud in enumerate(segments_audio):
        if i > 0:
            combined += silence
        combined += aud

    combined.export(str(output_path), format="wav")
    return str(output_path.relative_to(OUTPUTS_DIR))


async def _generate_single(
    text: str,
    output_filename: Optional[str],
    speaker: Optional[str],
    voice_clone_prompt=None,
    temperature: float = 1.0,
    speed: float = 1.0,
    language: str = "Auto",
    instruct: str = "",
) -> str:
    global _last_inference_time
    if voice_clone_prompt and isinstance(voice_clone_prompt, dict):
        ref_audio = voice_clone_prompt.get("ref_audio_path", "")
        ref_text = voice_clone_prompt.get("prompt_text", "")
        if ref_audio:
            from app.config import BASE_DIR
            full_path = str(BASE_DIR / ref_audio)
            result = await generate_audio_voice_clone(
                text=text,
                ref_audio_path=full_path,
                ref_text=ref_text,
                output_filename=output_filename,
                language=language,
                temperature=temperature,
                speed=speed,
            )
            _last_inference_time = time.time()
            return result

    result = await generate_audio_custom_voice(
        text=text,
        output_filename=output_filename,
        speaker=speaker or "vivian",
        language=language,
        instruct=instruct,
        temperature=temperature,
        speed=speed,
    )
    _last_inference_time = time.time()
    return result


async def generate_audio_custom_voice(
    text: str,
    output_filename: Optional[str] = None,
    speaker: str = "vivian",
    language: str = "Auto",
    instruct: str = "",
    temperature: float = 1.0,
    speed: float = 1.0,
) -> str:
    global _last_inference_time
    if output_filename is None:
        output_filename = f"{uuid.uuid4().hex}.wav"

    output_dir = OUTPUTS_DIR / "audio"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / output_filename

    logger.info("Local TTS CustomVoice: speaker=%s lang=%s temp=%.2f text_len=%d",
                speaker, language, temperature, len(text))

    loop = asyncio.get_running_loop()
    audio_bytes = await loop.run_in_executor(
        None,
        lambda: _generate_custom_voice_sync(text, speaker, language, instruct, temperature, speed),
    )

    _last_inference_time = time.time()
    output_path.write_bytes(audio_bytes)
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
    global _last_inference_time
    if output_filename is None:
        output_filename = f"{uuid.uuid4().hex}.wav"

    output_dir = OUTPUTS_DIR / "audio"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / output_filename

    logger.info("Local TTS VoiceClone: ref=%s temp=%.2f text_len=%d",
                ref_audio_path, temperature, len(text))

    prompt_items = _get_or_create_clone_prompt(ref_audio_path, ref_text)

    loop = asyncio.get_running_loop()
    audio_bytes = await loop.run_in_executor(
        None,
        lambda: _generate_voice_clone_sync(text, prompt_items, language, temperature, speed),
    )

    _last_inference_time = time.time()
    output_path.write_bytes(audio_bytes)
    return str(output_path.relative_to(OUTPUTS_DIR))
