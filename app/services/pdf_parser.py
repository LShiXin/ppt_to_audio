import subprocess
import shutil
import logging
from pathlib import Path
from app.config import UPLOADS_DIR

logger = logging.getLogger(__name__)

OCR_MIN_CHARS = 20


def _detect_ocr_engine() -> str:
    """Detect available OCR engine. Returns 'tesseract', 'easyocr', or ''."""
    if shutil.which("tesseract"):
        try:
            import pytesseract
            return "tesseract"
        except ImportError:
            pass
    try:
        import easyocr
        return "easyocr"
    except ImportError:
        pass
    return ""


def _ocr_with_tesseract(image_path: str) -> str:
    import pytesseract
    return pytesseract.image_to_string(image_path, lang="chi_sim+eng").strip()


_easyocr_reader = None


def _ocr_with_easyocr(image_path: str) -> str:
    global _easyocr_reader
    import easyocr
    if _easyocr_reader is None:
        _easyocr_reader = easyocr.Reader(["ch_sim", "en"], gpu=False)
    results = _easyocr_reader.readtext(image_path)
    lines = [item[1] for item in results if item[2] > 0.3]
    return "\n".join(lines)


def _ocr_page(image_path: str) -> str:
    engine = _detect_ocr_engine()
    if engine == "tesseract":
        return _ocr_with_tesseract(image_path)
    elif engine == "easyocr":
        return _ocr_with_easyocr(image_path)
    return ""


def _needs_ocr(slide: dict) -> bool:
    text = (slide["title"] + slide["content"]).replace("\n", "").replace(" ", "").strip()
    return len(text) < OCR_MIN_CHARS


def enhance_with_ocr(slides: list[dict], images_dir: str) -> list[dict]:
    engine = _detect_ocr_engine()
    if not engine:
        logger.warning("未检测到 OCR 引擎 (tesseract/easyocr)，跳过 OCR 增强")
        logger.warning("安装 tesseract: apt-get install tesseract-ocr tesseract-ocr-chi-sim && pip install pytesseract")
        logger.warning("安装 easyocr: pip install easyocr")
        return slides

    logger.info("使用 %s 进行 OCR 增强，阈值: 少于 %d 字符的页面将被 OCR", engine, OCR_MIN_CHARS)
    images_root = Path(images_dir)
    ocr_count = 0

    for s in slides:
        if _needs_ocr(s):
            img_path = images_root / f"slide_{s['slide_number']}.png"
            if img_path.exists():
                try:
                    ocr_text = _ocr_page(str(img_path))
                    if ocr_text:
                        lines = [l.strip() for l in ocr_text.split("\n") if l.strip()]
                        if lines:
                            s["title"] = lines[0]
                            s["content"] = "\n".join(lines[1:]) if len(lines) > 1 else ""
                            ocr_count += 1
                except Exception as e:
                    logger.warning("OCR 第 %d 页失败: %s", s["slide_number"], e)

    if ocr_count:
        logger.info("OCR 增强了 %d 页", ocr_count)
    return slides


def _parse_with_pdftotext(file_path: str, total_pages: int) -> list[dict]:
    slides_data = []
    for page_num in range(1, total_pages + 1):
        try:
            result = subprocess.run(
                ["pdftotext", "-f", str(page_num), "-l", str(page_num), "-layout", file_path, "-"],
                capture_output=True, text=True, timeout=30,
            )
            page_text = result.stdout.strip()
        except subprocess.TimeoutExpired:
            page_text = ""

        lines = [l.strip() for l in page_text.split("\n") if l.strip()]
        title = lines[0] if lines else f"第{page_num}页"
        content = "\n".join(lines[1:]) if len(lines) > 1 else ""

        slides_data.append({
            "slide_number": page_num,
            "title": title,
            "content": content,
            "notes": "",
        })
    return slides_data


def _parse_with_pymupdf(file_path: str, total_pages: int) -> list[dict]:
    import fitz
    doc = fitz.open(file_path)
    slides_data = []
    for i in range(total_pages):
        page_text = doc[i].get_text().strip()
        lines = [l.strip() for l in page_text.split("\n") if l.strip()]
        title = lines[0] if lines else f"第{i + 1}页"
        content = "\n".join(lines[1:]) if len(lines) > 1 else ""

        slides_data.append({
            "slide_number": i + 1,
            "title": title,
            "content": content,
            "notes": "",
        })
    doc.close()
    return slides_data


def extract_pdf_images(pdf_path: str, output_dir: str) -> list[str]:
    import re
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    if shutil.which("pdftoppm"):
        logger.info("使用 pdftoppm 渲染页面图片")
        stem = out / "slide"
        subprocess.run(
            ["pdftoppm", "-png", "-r", "300", pdf_path, str(stem)],
            capture_output=True, timeout=120,
        )
        raw_paths = list(out.glob("slide-*.png"))
        def _page_num(p: Path) -> int:
            m = re.search(r"slide-0*(\d+)", p.stem)
            return int(m.group(1)) if m else 0
        raw_paths.sort(key=_page_num)
        for p in raw_paths:
            num = _page_num(p)
            new_name = out / f"slide_{num}.png"
            p.rename(new_name)
        result = sorted(out.glob("slide_*.png"), key=_page_num)
        return [str(p.relative_to(out.parent)) for p in result]
    else:
        logger.warning("pdftoppm 未安装，回退使用 PyMuPDF 渲染")
        import fitz
        doc = fitz.open(pdf_path)
        paths = []
        for i in range(len(doc)):
            page = doc[i]
            pix = page.get_pixmap(dpi=300)
            png_path = out / f"slide_{i + 1}.png"
            pix.save(str(png_path))
            paths.append(str(png_path.relative_to(out.parent)))
        doc.close()
        return paths


def parse_pdf(file_path: str, images_dir: str = "") -> list[dict]:
    import fitz
    doc = fitz.open(file_path)
    total_pages = len(doc)
    doc.close()

    if shutil.which("pdftotext"):
        logger.info("使用 pdftotext 提取文本")
        slides = _parse_with_pdftotext(file_path, total_pages)
    else:
        logger.warning("pdftotext 未安装，回退使用 PyMuPDF 提取文本")
        slides = _parse_with_pymupdf(file_path, total_pages)

    if images_dir:
        slides = enhance_with_ocr(slides, images_dir)

    return slides


def save_upload(file_content: bytes, original_filename: str, project_id: int) -> str:
    ext = Path(original_filename).suffix
    unique_name = f"{__import__('uuid').uuid4().hex}{ext}"
    project_dir = UPLOADS_DIR / str(project_id)
    project_dir.mkdir(parents=True, exist_ok=True)
    dest = project_dir / unique_name
    dest.write_bytes(file_content)
    return str(dest.relative_to(UPLOADS_DIR))
