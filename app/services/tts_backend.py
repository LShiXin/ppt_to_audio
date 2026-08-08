import logging
from app.config import TTS_BACKEND

logger = logging.getLogger(__name__)

_backend = None


def _get_backend():
    global _backend
    if _backend is None:
        if TTS_BACKEND == "vllm_omni":
            from app.services import vllm_omni_tts as mod
            _backend = mod
            logger.info("TTS backend: vllm_omni (%s/tts)", TTS_BACKEND)
        else:
            from app.services import local_tts as mod
            _backend = mod
            logger.info("TTS backend: local (qwen-tts)")
    return _backend


def generate_audio_with_segmentation(*args, **kwargs):
    return _get_backend().generate_audio_with_segmentation(*args, **kwargs)


def generate_audio_custom_voice(*args, **kwargs):
    return _get_backend().generate_audio_custom_voice(*args, **kwargs)


def generate_audio_voice_clone(*args, **kwargs):
    return _get_backend().generate_audio_voice_clone(*args, **kwargs)


def clear_tts_cache(*args, **kwargs):
    return _get_backend().clear_tts_cache(*args, **kwargs)


def unload_all_models(*args, **kwargs):
    return _get_backend().unload_all_models(*args, **kwargs)


def is_model_loaded(*args, **kwargs):
    return _get_backend().is_model_loaded(*args, **kwargs)
