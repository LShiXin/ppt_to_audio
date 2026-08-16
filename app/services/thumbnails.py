import logging
from pathlib import Path

logger = logging.getLogger(__name__)

THUMB_WIDTH = 640
THUMB_QUALITY = 70


def generate_slide_thumbnails(images_dir: str) -> int:
    """Generate low-res JPEG thumbnails for every slide PNG in images_dir.

    Returns the number of thumbnails created. Original high-res PNGs are
    left untouched (video composition must keep using the originals).
    """
    root = Path(images_dir)
    if not root.exists():
        return 0

    thumb_dir = root / "thumbs"
    thumb_dir.mkdir(parents=True, exist_ok=True)

    created = 0
    for png in sorted(root.glob("slide_*.png")):
        thumb_path = thumb_dir / f"{png.stem}.jpg"
        if thumb_path.exists():
            continue
        try:
            from PIL import Image
            with Image.open(png) as img:
                if img.width > THUMB_WIDTH:
                    ratio = THUMB_WIDTH / img.width
                    img = img.resize(
                        (THUMB_WIDTH, max(1, int(img.height * ratio))),
                        Image.LANCZOS,
                    )
                img.convert("RGB").save(
                    thumb_path, format="JPEG", quality=THUMB_QUALITY, optimize=True
                )
            created += 1
        except Exception as e:
            logger.warning("缩略图生成失败 %s: %s", png.name, e)

    return created
