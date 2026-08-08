from pydantic import BaseModel, Field, field_validator
from typing import Optional
from datetime import datetime


def _coerce_none_to_empty(v):
    if v is None:
        return ""
    return v


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    topic: str = ""


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    topic: Optional[str] = None


class ProjectOut(BaseModel):
    id: int
    uuid: str = ""
    name: str
    topic: str
    ppt_filename: str
    status: str
    composed_audio: str
    video_path: str
    created_at: str
    updated_at: str

    _coerce_topic = field_validator("topic", mode="before")(_coerce_none_to_empty)
    _coerce_ppt = field_validator("ppt_filename", mode="before")(_coerce_none_to_empty)
    _coerce_status = field_validator("status", mode="before")(_coerce_none_to_empty)
    _coerce_composed = field_validator("composed_audio", mode="before")(_coerce_none_to_empty)
    _coerce_video = field_validator("video_path", mode="before")(_coerce_none_to_empty)
    _coerce_uuid = field_validator("uuid", mode="before")(_coerce_none_to_empty)


class SlideOut(BaseModel):
    id: int
    project_id: int
    slide_number: int
    title: str
    content: str
    notes: str
    narration: str
    narration_audio: str
    status: str

    _coerce_title = field_validator("title", mode="before")(_coerce_none_to_empty)
    _coerce_content = field_validator("content", mode="before")(_coerce_none_to_empty)
    _coerce_notes = field_validator("notes", mode="before")(_coerce_none_to_empty)
    _coerce_narration = field_validator("narration", mode="before")(_coerce_none_to_empty)
    _coerce_audio = field_validator("narration_audio", mode="before")(_coerce_none_to_empty)
    _coerce_slide_status = field_validator("status", mode="before")(_coerce_none_to_empty)


class SlideUpdate(BaseModel):
    narration: Optional[str] = None


class ScriptGenerateRequest(BaseModel):
    project_id: int
    word_count: str = ""
    llm_model: str = ""


class SingleSlideGenerateRequest(BaseModel):
    word_count: str = ""
    llm_model: str = ""


class ScriptGenerateResponse(BaseModel):
    slides: list[SlideOut]


class AudioGenerateRequest(BaseModel):
    project_id: int
    voice_id: Optional[str] = None
    speaker: Optional[str] = None
    voice_description: Optional[str] = None
    slide_id: Optional[int] = None
    speed: Optional[float] = None
    seed: Optional[int] = None
    model: str = ""
    temperature: Optional[float] = None


class VoiceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = ""
    prompt_text: str = ""


class VoiceOut(BaseModel):
    id: str = ""
    name: str
    description: str
    ref_audio_path: str
    prompt_text: str
    created_at: str = ""

    _coerce_id = field_validator("id", mode="before")(_coerce_none_to_empty)
    _coerce_desc = field_validator("description", mode="before")(_coerce_none_to_empty)
    _coerce_path = field_validator("ref_audio_path", mode="before")(_coerce_none_to_empty)
    _coerce_prompt = field_validator("prompt_text", mode="before")(_coerce_none_to_empty)
    _coerce_created = field_validator("created_at", mode="before")(_coerce_none_to_empty)


class ReferenceFileOut(BaseModel):
    id: int
    project_id: int
    filename: str
    content: str

    _coerce_content = field_validator("content", mode="before")(_coerce_none_to_empty)


class TaskStatus(BaseModel):
    task_id: str
    status: str
    progress: int = 0
    message: str = ""
    result: Optional[dict] = None
