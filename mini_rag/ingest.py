from dataclasses import dataclass
from pathlib import Path

DOCS_DIR = Path(__file__).parent / "docs" / "company"
MAX_CHARS = 400  # ponytail: character limit, switch to token-aware sizes if chunks look off


@dataclass(frozen=True)
class Chunk:
    id: str  # "<doc>#<n>", used later for citations
    doc: str
    title: str
    text: str


def chunk_text(text: str, max_chars: int = MAX_CHARS) -> list[str]:
    """Split on blank lines (paragraphs), then pack paragraphs together up to max_chars."""
    chunks, current = [], ""
    for para in (p.strip() for p in text.split("\n\n")):
        if not para:
            continue
        if current and len(current) + len(para) + 2 > max_chars:
            chunks.append(current)
            current = para
        else:
            current = f"{current}\n\n{para}" if current else para
    if current:
        chunks.append(current)
    return chunks


def load_chunks(docs_dir: Path = DOCS_DIR) -> list[Chunk]:
    chunks = []
    for path in sorted(docs_dir.glob("*.md")):
        title, _, body = path.read_text().partition("\n")
        title = title.lstrip("# ").strip()
        for n, piece in enumerate(chunk_text(body)):
            # prefix the title so a chunk still says what it belongs to when seen alone
            chunks.append(Chunk(f"{path.stem}#{n}", path.stem, title, f"{title}\n{piece}"))
    return chunks


if __name__ == "__main__":
    for c in load_chunks():
        print(f"[{c.id}] ({len(c.text)} chars)\n{c.text}\n")
