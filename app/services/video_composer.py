import subprocess
import uuid
import os
from pathlib import Path
from typing import Callable
from pydub import AudioSegment
from app.config import OUTPUTS_DIR, UPLOADS_DIR


def _get_audio_duration(path: str) -> float:
    audio = AudioSegment.from_file(path)
    return len(audio) / 1000.0


def compose_video(
    slide_images: list[str],
    audio_paths: list[str],
    slide_gap: float = 0.5,
    output_filename: str | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> str:
    if output_filename is None:
        output_filename = f"project_{uuid.uuid4().hex[:8]}.mp4"

    output_dir = OUTPUTS_DIR / "video"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / output_filename

    tmp_dir = output_dir / f"tmp_{uuid.uuid4().hex[:8]}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    try:
        concat_lines = []
        segment_index = 0

        for i, (img_path, aud_path) in enumerate(zip(slide_images, audio_paths)):
            is_last = (i == len(slide_images) - 1)
            duration = _get_audio_duration(aud_path)

            seg_video = tmp_dir / f"seg_{segment_index:04d}.mp4"
            cmd = [
                "ffmpeg", "-y", "-loop", "1", "-i", img_path,
                "-i", aud_path,
                "-c:v", "h264_nvenc", "-preset", "p4",
                "-t", str(duration + (0 if is_last else slide_gap)),
                "-pix_fmt", "yuv420p",
                "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2",
                "-c:a", "aac", "-b:a", "192k",
                "-shortest",
                str(seg_video),
            ]
            subprocess.run(cmd, check=True, capture_output=True)

            concat_lines.append(f"file '{seg_video}'")
            segment_index += 1
            if progress_callback:
                progress_callback(i + 1, len(slide_images))

        concat_file = tmp_dir / "concat.txt"
        concat_file.write_text("\n".join(concat_lines))

        concat_cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(concat_file),
            "-c", "copy",
            str(output_path),
        ]
        subprocess.run(concat_cmd, check=True, capture_output=True)

    finally:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return str(output_path.relative_to(OUTPUTS_DIR))


def build_video_from_slides(
    slides: list[dict],
    project_id: int,
    progress_callback: Callable[[int, int], None] | None = None,
) -> str:
    slide_images = []
    audio_paths = []

    images_dir = UPLOADS_DIR / str(project_id) / "slide_images"
    for s in slides:
        img_path = images_dir / f"slide_{s['slide_number']}.png"
        if not img_path.exists():
            raise FileNotFoundError(f"幻灯片图片不存在: {img_path}")
        slide_images.append(str(img_path))

        if not s.get("narration_audio"):
            raise ValueError(f"第 {s['slide_number']} 页音频未生成，请先生成音频")
        audio_paths.append(str(OUTPUTS_DIR / s["narration_audio"]))

    return compose_video(slide_images, audio_paths, progress_callback=progress_callback)
