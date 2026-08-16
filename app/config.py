import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

MODELS_DIR = BASE_DIR / "models"
VOICES_DIR = BASE_DIR / "voices"
UPLOADS_DIR = BASE_DIR / "uploads"
OUTPUTS_DIR = BASE_DIR / "outputs"
DB_PATH = BASE_DIR / "data.db"

MODELS_DIR.mkdir(parents=True, exist_ok=True)
VOICES_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

TTS_BASE_MODEL_PATH = str(MODELS_DIR / "Qwen3-TTS-12Hz-0.6B-Base")
TTS_CUSTOM_VOICE_MODEL_PATH = str(MODELS_DIR / "Qwen3-TTS-12Hz-1.7B-CustomVoice")
TTS_DEVICE = os.environ.get("TTS_DEVICE", "cuda")
TTS_DTYPE = os.environ.get("TTS_DTYPE", "bfloat16")
TTS_IDLE_TIMEOUT = int(os.environ.get("TTS_IDLE_TIMEOUT", "300"))

TTS_BACKEND = os.environ.get("TTS_BACKEND", "local")
VLLM_OMNI_BASE_URL = os.environ.get("VLLM_OMNI_BASE_URL", "http://localhost:8000")
VLLM_PORT = int(os.environ.get("VLLM_PORT", "8000"))
VLLM_OMNI_VOICE_NAME = os.environ.get("VLLM_OMNI_VOICE_NAME", "clone")
VLLM_OMNI_GPU_COOLDOWN = float(os.environ.get("VLLM_OMNI_GPU_COOLDOWN", "0"))
VLLM_OMNI_MODEL = os.environ.get("VLLM_OMNI_MODEL", "base")
VLLM_BASE_MODEL_PATH = str(MODELS_DIR / "Qwen3-TTS-12Hz-0.6B-Base")
VLLM_CUSTOMVOICE_MODEL_PATH = str(MODELS_DIR / "Qwen3-TTS-12Hz-1.7B-CustomVoice")

TTS_CUSTOM_VOICE_SPEAKERS = [
    {"name": "vivian", "description": "明亮略带锋芒的年轻女声", "language": "Chinese"},
    {"name": "serena", "description": "温暖柔和的年轻女声", "language": "Chinese"},
    {"name": "uncle_fu", "description": "低沉醇厚的成熟男声", "language": "Chinese"},
    {"name": "dylan", "description": "清亮自然的北京男声", "language": "Chinese", "dialect": "beijing_dialect"},
    {"name": "eric", "description": "活泼略带沙哑的成都男声", "language": "Chinese", "dialect": "sichuan_dialect"},
    {"name": "ryan", "description": "节奏感强的动感男声", "language": "English"},
    {"name": "aiden", "description": "阳光清亮的美式男声", "language": "English"},
    {"name": "ono_anna", "description": "轻快灵动的日本女声", "language": "Japanese"},
    {"name": "sohee", "description": "温暖富有情感的韩国女声", "language": "Korean"},
]

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "my_api_key")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")

SUPPORTED_REFERENCE_FORMATS = {".txt", ".md", ".pdf", ".docx"}
MAX_UPLOAD_SIZE_MB = 100
