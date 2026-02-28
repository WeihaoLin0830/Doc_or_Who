from __future__ import annotations

import re

import ftfy
from langdetect import detect

from backend.config import get_settings

CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")
PAGE_NOISE_RE = re.compile(r"(?:^|\n)\s*(?:page|p[aá]gina)\s+\d+(?:\s+of\s+\d+|\s+de\s+\d+)?\s*(?=\n|$)", re.IGNORECASE)


def clean_text(raw: str) -> str:
    text = ftfy.fix_text(raw)
    text = CONTROL_CHARS_RE.sub(" ", text)
    text = PAGE_NOISE_RE.sub("\n", text)
    lines: list[str] = []
    for line in text.splitlines():
        line = re.sub(r"[ \t]+", " ", line).strip()
        if len(line) > 1200:
            line = line[:1200]
        lines.append(line)
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def detect_language(text: str) -> str:
    if not text.strip():
        return get_settings().default_language
    try:
        return detect(text[:1200])
    except Exception:
        return get_settings().default_language
