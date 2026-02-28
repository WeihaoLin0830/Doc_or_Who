from __future__ import annotations

import re
from bisect import bisect_left

from backend.config import get_settings
from backend.types import ChunkPayload, ExtractionResult

TOKEN_RE = re.compile(r"\S+")
HEADING_RE = re.compile(r"^(?:#{1,6}\s+.+|[A-Z0-9][A-Z0-9 \-:]{3,}|(?:\d+\.|\d+\))\s+.+)$")


def tokenize_with_offsets(text: str) -> list[tuple[str, int, int]]:
    return [(match.group(0), match.start(), match.end()) for match in TOKEN_RE.finditer(text)]


def approximate_token_count(text: str) -> int:
    return len(TOKEN_RE.findall(text))


def _heading_positions(text: str) -> list[tuple[int, str]]:
    headings: list[tuple[int, str]] = []
    cursor = 0
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if stripped and len(stripped) <= 140 and HEADING_RE.match(stripped):
            headings.append((cursor, stripped.lstrip("#").strip()))
        cursor += len(line)
    return headings


def _boundary_token_indices(text: str, token_starts: list[int]) -> list[int]:
    boundaries: set[int] = set()
    for match in re.finditer(r"\n\s*\n+", text):
        boundaries.add(bisect_left(token_starts, match.end()))
    for position, _title in _heading_positions(text):
        boundaries.add(bisect_left(token_starts, position))
    return sorted(boundaries)


def _section_for_token(token_index: int, heading_tokens: list[tuple[int, str]]) -> str | None:
    current = None
    for heading_index, title in heading_tokens:
        if heading_index <= token_index:
            current = title
        else:
            break
    return current


def chunk_text_document(text: str) -> list[ChunkPayload]:
    settings = get_settings()
    tokens = tokenize_with_offsets(text)
    if not tokens:
        return []
    if len(tokens) <= settings.chunk_max_tokens:
        return [
            ChunkPayload(
                chunk_index=0,
                text=text,
                token_count=len(tokens),
                char_start=0,
                char_end=len(text),
                section_title=_heading_positions(text)[0][1] if _heading_positions(text) else None,
            )
        ]

    token_starts = [start for _token, start, _end in tokens]
    boundaries = _boundary_token_indices(text, token_starts)
    heading_tokens = [(bisect_left(token_starts, position), title) for position, title in _heading_positions(text)]
    chunks: list[ChunkPayload] = []
    start_index = 0
    chunk_index = 0
    while start_index < len(tokens):
        min_end = min(len(tokens), start_index + settings.chunk_min_tokens)
        target_end = min(len(tokens), start_index + settings.chunk_target_tokens)
        max_end = min(len(tokens), start_index + settings.chunk_max_tokens)
        boundary_candidates = [candidate for candidate in boundaries if min_end <= candidate <= max_end]
        if boundary_candidates:
            end_index = min(boundary_candidates, key=lambda candidate: abs(candidate - target_end))
        else:
            end_index = max_end
        if end_index <= start_index:
            end_index = min(len(tokens), start_index + settings.chunk_target_tokens)
        char_start = tokens[start_index][1]
        char_end = tokens[end_index - 1][2]
        chunks.append(
            ChunkPayload(
                chunk_index=chunk_index,
                text=text[char_start:char_end].strip(),
                token_count=end_index - start_index,
                char_start=char_start,
                char_end=char_end,
                section_title=_section_for_token(start_index, heading_tokens),
            )
        )
        if end_index >= len(tokens):
            break
        start_index = max(0, end_index - settings.chunk_overlap_tokens)
        chunk_index += 1
    return chunks


def _summarize_rows(rows: list[dict[str, str]], label: str) -> str:
    lines = [f"{label} ({len(rows)} rows)"]
    for row in rows[:20]:
        lines.append(" | ".join(f"{key}: {value}" for key, value in row.items()))
    return "\n".join(lines)


def chunk_tabular_document(extraction: ExtractionResult) -> list[ChunkPayload]:
    rows = extraction.table_rows
    if not rows:
        return chunk_text_document(extraction.text)
    chunks: list[ChunkPayload] = []
    for index, row in enumerate(rows):
        row_text = " | ".join(f"{key}: {value}" for key, value in row.items())
        start, end = extraction.row_spans[index] if index < len(extraction.row_spans) else (0, len(extraction.text))
        chunks.append(
            ChunkPayload(
                chunk_index=len(chunks),
                text=row_text,
                token_count=approximate_token_count(row_text),
                char_start=start,
                char_end=end,
                section_title=f"Row {index}",
            )
        )

    group_key = extraction.table_group_key
    if group_key:
        grouped: dict[str, list[tuple[int, dict[str, str]]]] = {}
        for index, row in enumerate(rows):
            group_value = row.get(group_key, "unknown")
            grouped.setdefault(group_value, []).append((index, row))
        for group_value, grouped_rows in grouped.items():
            content = _summarize_rows([row for _index, row in grouped_rows], f"{group_key}: {group_value}")
            start = extraction.row_spans[grouped_rows[0][0]][0]
            end = extraction.row_spans[grouped_rows[-1][0]][1]
            chunks.append(
                ChunkPayload(
                    chunk_index=len(chunks),
                    text=content,
                    token_count=approximate_token_count(content),
                    char_start=start,
                    char_end=end,
                    section_title=f"{group_key}: {group_value}",
                )
            )

    summary = _summarize_rows(rows, f"Document summary for {extraction.path.name}")
    chunks.append(
        ChunkPayload(
            chunk_index=len(chunks),
            text=summary,
            token_count=approximate_token_count(summary),
            char_start=0,
            char_end=len(extraction.text),
            section_title="Document summary",
        )
    )
    return chunks


class Chunker:
    def chunk(self, _document, text: str, extraction: ExtractionResult | None = None) -> list[ChunkPayload]:
        if extraction and extraction.table_rows:
            return chunk_tabular_document(extraction)
        return chunk_text_document(text)
