import asyncio
import atexit
import logging
import os
import signal
import time
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader

from app.models.database import get_db, close_db
from app.routers import project, script, voice, audio, digital_human, video, model

BASE_DIR = Path(__file__).resolve().parent.parent
logger = logging.getLogger(__name__)

_idle_monitor_task: asyncio.Task | None = None


def _force_cuda_cleanup_impl():
    import torch
    if torch.cuda.is_available():
        torch.cuda.synchronize()
        torch.cuda.empty_cache()
        torch.cuda.ipc_collect()
        torch.cuda.reset_peak_memory_stats()
        torch.cuda.reset_accumulated_memory_stats()


def _cleanup_gpu():
    from app.services.tts_backend import unload_all_models
    import torch
    before = torch.cuda.memory_allocated() / 1024**3 if torch.cuda.is_available() else 0
    logger.warning("Starting GPU cleanup, allocated: %.2f GiB", before)
    unload_all_models()
    _force_cuda_cleanup_impl()
    after = torch.cuda.memory_allocated() / 1024**3 if torch.cuda.is_available() else 0
    logger.warning("GPU cleanup complete, allocated: %.2f GiB", after)


_cleanup_done = False


def _signal_handler(signum, frame):
    global _cleanup_done
    if _cleanup_done:
        return
    _cleanup_done = True
    logger.warning("Received signal %s, cleaning up GPU resources...", signum)
    _cleanup_gpu()
    os.killpg(os.getpgid(0), signal.SIGKILL)


signal.signal(signal.SIGTERM, _signal_handler)
signal.signal(signal.SIGINT, _signal_handler)
atexit.register(_cleanup_gpu)


async def _idle_monitor():
    from app.config import TTS_IDLE_TIMEOUT, TTS_BACKEND
    if TTS_BACKEND == "vllm_omni":
        from app.services.vllm_omni_tts import (
            _last_inference_time,
        )
        from app.services.vllm_process import is_ready
    else:
        from app.services.local_tts import (
            _last_inference_time, unload_all_models, is_model_loaded,
        )
    while True:
        await asyncio.sleep(30)
        try:
            elapsed = time.time() - _last_inference_time
            if TTS_BACKEND == "vllm_omni":
                if is_ready() and elapsed > TTS_IDLE_TIMEOUT:
                    logger.info("Idle timeout reached (%.0fs > %ds), vLLM continues running",
                               elapsed, TTS_IDLE_TIMEOUT)
            elif is_model_loaded() and elapsed > TTS_IDLE_TIMEOUT:
                logger.info("Idle timeout reached (%.0fs > %ds), unloading TTS models",
                           elapsed, TTS_IDLE_TIMEOUT)
                unload_all_models()
        except Exception:
            logger.exception("Idle monitor error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _idle_monitor_task
    await get_db()

    from app.config import TTS_BACKEND
    if TTS_BACKEND == "vllm_omni":
        from app.services.vllm_process import start_vllm, stop_vllm, get_current_model
        loop = asyncio.get_running_loop()
        ok = await loop.run_in_executor(None, lambda: start_vllm(get_current_model()))
        if not ok:
            logger.error("Failed to start vLLM-Omni, continuing anyway")

    _idle_monitor_task = asyncio.create_task(_idle_monitor())
    yield
    if _idle_monitor_task:
        _idle_monitor_task.cancel()
    if TTS_BACKEND == "vllm_omni":
        from app.services.vllm_process import stop_vllm
        stop_vllm()
    await close_db()
    _cleanup_gpu()


app = FastAPI(title="PPT转视频 AI工具", version="1.0.0", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.mount("/outputs", StaticFiles(directory=str(BASE_DIR / "outputs")), name="outputs")

templates = Environment(
    loader=FileSystemLoader(str(BASE_DIR / "templates")),
    autoescape=True,
)


def render(name: str, request: Request, **kwargs) -> HTMLResponse:
    tmpl = templates.get_template(name)
    return HTMLResponse(tmpl.render(request=request, **kwargs))


app.include_router(project.router)
app.include_router(script.router)
app.include_router(voice.router)
app.include_router(audio.router)
app.include_router(digital_human.router)
app.include_router(video.router)
app.include_router(model.router)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return render("index.html", request)


@app.get("/workspace/{project_uuid}", response_class=HTMLResponse)
async def workspace(request: Request, project_uuid: str):
    db = await get_db()
    row = await db.execute("SELECT id FROM projects WHERE uuid = ?", (project_uuid,))
    project = await row.fetchone()
    if not project:
        return HTMLResponse("项目不存在", status_code=404)
    return render("workspace.html", request, project_uuid=project_uuid)


@app.get("/voices", response_class=HTMLResponse)
async def voice_manager(request: Request):
    return render("voice_manager.html", request)



