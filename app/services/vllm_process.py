import asyncio
import logging
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Optional

import requests

from app.config import (
    VLLM_BASE_MODEL_PATH,
    VLLM_CUSTOMVOICE_MODEL_PATH,
    VLLM_OMNI_BASE_URL,
    VLLM_PORT,
)

logger = logging.getLogger(__name__)

_VLLM_PID: Optional[int] = None
_current_model: str = "base"
_switch_task: Optional[asyncio.Task] = None
_switch_status: dict = {"status": "idle", "progress": 0, "message": ""}

STAGE_CONFIG = str(
    Path(os.environ.get(
        "CONDA_PREFIX",
        os.path.expanduser("~/miniconda3/envs/ppt2video"),
    ))
    / "lib/python3.12/site-packages/vllm_omni/deploy/qwen3_tts.yaml"
)

VLLM_BIN = str(
    Path(os.environ.get(
        "CONDA_PREFIX",
        os.path.expanduser("~/miniconda3/envs/ppt2video"),
    ))
    / "bin/vllm"
)


def _get_model_path(model_type: str) -> str:
    if model_type == "base":
        return VLLM_BASE_MODEL_PATH
    return VLLM_CUSTOMVOICE_MODEL_PATH


def get_current_model() -> str:
    return _current_model


def get_switch_status() -> dict:
    return dict(_switch_status)


def is_ready() -> bool:
    try:
        resp = requests.get(f"{VLLM_OMNI_BASE_URL}/health", timeout=5)
        return resp.status_code == 200
    except Exception:
        return False


def _kill_vllm():
    global _VLLM_PID
    if _VLLM_PID is not None:
        try:
            os.kill(_VLLM_PID, signal.SIGTERM)
        except OSError:
            pass
        try:
            os.kill(_VLLM_PID, signal.SIGKILL)
        except OSError:
            pass
        _VLLM_PID = None
    subprocess.run(["pkill", "-9", "-f", "StageEngineCoreProc"], capture_output=True)
    subprocess.run(["pkill", "-9", "-f", "resource_tracker"], capture_output=True)
    time.sleep(2)


def start_vllm(model_type: str) -> bool:
    global _VLLM_PID, _current_model

    _kill_vllm()

    model_path = _get_model_path(model_type)
    logger.info("Starting vLLM-Omni: model=%s path=%s port=%s", model_type, model_path, VLLM_PORT)

    log_path = Path(__file__).resolve().parent.parent.parent / "logs" / "vllm_omni.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    with open(str(log_path), "a") as log_file:
        proc = subprocess.Popen(
            [
                VLLM_BIN, "serve", model_path,
                "--omni",
                "--port", str(VLLM_PORT),
                "--host", "0.0.0.0",
                "--stage-configs-path", STAGE_CONFIG,
            ],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    _VLLM_PID = proc.pid
    logger.info("vLLM-Omni PID: %d", _VLLM_PID)

    max_wait = 600
    waited = 0
    while waited < max_wait:
        if is_ready():
            _current_model = model_type
            logger.info("vLLM-Omni ready (waited %ds, model=%s)", waited, model_type)
            return True
        if proc.poll() is not None:
            logger.error("vLLM-Omni exited early with code %d", proc.returncode)
            return False
        time.sleep(5)
        waited += 5

    logger.error("vLLM-Omni startup timed out after %ds", max_wait)
    return False


def stop_vllm():
    _kill_vllm()


async def switch_model(model_type: str) -> str:
    global _switch_task, _switch_status

    if _switch_task and not _switch_task.done():
        return "already_switching"

    if model_type == _current_model and is_ready():
        return "same_model"

    if not is_ready() and model_type == _current_model:
        logger.warning("vLLM-Omni not ready, restarting same model %s", model_type)

    _switch_status = {"status": "switching", "progress": 0, "message": f"正在切换到 {model_type} 模型..."}

    async def _do_switch():
        global _switch_status
        try:
            _switch_status["progress"] = 20
            _switch_status["message"] = f"正在停止当前模型..."
            loop = asyncio.get_running_loop()
            success = await loop.run_in_executor(None, lambda: start_vllm(model_type))
            if success:
                _switch_status = {"status": "completed", "progress": 100, "message": f"模型已切换为 {model_type}"}
            else:
                _switch_status = {"status": "failed", "progress": 0, "message": "模型启动失败，请检查日志"}
        except Exception as e:
            logger.exception("Model switch failed")
            _switch_status = {"status": "failed", "progress": 0, "message": str(e)}

    _switch_task = asyncio.create_task(_do_switch())
    return "started"