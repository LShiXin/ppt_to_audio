import uuid
from pathlib import Path
from pydub import AudioSegment
from app.config import OUTPUTS_DIR


def compose_audio(audio_paths: list[str], output_filename: str | None = None) -> str:
    if output_filename is None:
        output_filename = f"composed_{uuid.uuid4().hex}.mp3"

    output_dir = OUTPUTS_DIR / "composed"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / output_filename

    combined = AudioSegment.empty()
    silence = AudioSegment.silent(duration=500)

    for i, path in enumerate(audio_paths):
        segment = AudioSegment.from_file(path)
        combined += segment
        if i < len(audio_paths) - 1:
            combined += silence

    combined.export(str(output_path), format="mp3", bitrate="192k")
    return str(output_path.relative_to(OUTPUTS_DIR))
