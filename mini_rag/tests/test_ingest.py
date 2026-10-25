from ingest import chunk_text, load_chunks


def test_chunk_text_respects_limit_and_keeps_all_text():
    text = "\n\n".join(f"paragraph number {i} " * 3 for i in range(10))
    pieces = chunk_text(text, max_chars=100)
    assert len(pieces) > 1
    assert all(len(p) <= 100 for p in pieces)
    assert "".join(pieces).replace("\n", "").replace(" ", "") == text.replace("\n", "").replace(" ", "")


def test_load_chunks_has_unique_ids_and_titles():
    chunks = load_chunks()
    assert len({c.id for c in chunks}) == len(chunks)
    assert all(c.text.startswith(c.title) for c in chunks)
