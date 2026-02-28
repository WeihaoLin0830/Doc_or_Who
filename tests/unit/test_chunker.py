from __future__ import annotations

from backend.chunker import chunk_text_document
from backend.config import get_settings


def test_chunker_respects_size_and_offsets(isolated_environment):
    settings = get_settings()
    paragraph = "Aurora planning text " * 80
    text = "\n\n".join(
        [f"SECTION {index}\n{paragraph}{index}" for index in range(1, 12)]
    )

    chunks = chunk_text_document(text)

    assert len(chunks) >= 2
    for chunk in chunks:
        assert chunk.token_count <= settings.chunk_max_tokens
        assert 0 <= chunk.char_start < chunk.char_end <= len(text)
    for previous, current in zip(chunks, chunks[1:]):
        assert current.char_start < previous.char_end
        assert current.char_end > current.char_start
