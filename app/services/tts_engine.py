import re
from typing import List


def segment_text(text: str, separators: str = "。；!?！？\n") -> List[str]:
    """
    Split text by sentence-ending punctuation for parallel batch generation.
    Each segment will include its trailing separator (except the last).
    If a segment is still too long (>300 chars), further split by comma.
    """
    if not text.strip():
        return []

    parts = re.split(rf"(?<=[{re.escape(separators)}])", text)
    parts = [p.strip() for p in parts if p.strip()]

    result = []
    for p in parts:
        if len(p) > 300:
            sub_parts = re.split(rf"(?<=[,，])", p)
            sub_parts = [s.strip() for s in sub_parts if s.strip()]
            result.extend(sub_parts)
        else:
            result.append(p)

    return result
