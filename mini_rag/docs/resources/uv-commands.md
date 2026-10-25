# uv commands (template + example)

`uv` replaces `pip`, `venv` and `python` for this project. Never use `pip`.
Angle brackets `<...>` are placeholders you fill in.

## Project setup

| Goal | Template | Example |
|---|---|---|
| Create a new project | `uv init --bare --name <project-name> --python <version>` | `uv init --bare --name mini-rag --python 3.12` |
| Add a library | `uv add <package> [<package> ...]` | `uv add streamlit httpx numpy fastembed` |
| Add a dev-only library | `uv add --dev <package>` | `uv add --dev pytest` |
| Remove a library | `uv remove <package>` | `uv remove numpy` |
| Install everything from `pyproject.toml` / `uv.lock` | `uv sync` | `uv sync` |

## Running things

| Goal | Template | Example |
|---|---|---|
| Run a Python file | `uv run python <file.py>` | `uv run python ingest.py` |
| Run a Streamlit app | `uv run streamlit run <app.py>` | `uv run streamlit run app.py` |
| Run tests | `uv run pytest [<path>]` | `uv run pytest tests/` |
| Run a one-off tool without installing it | `uvx <tool> [args]` | `uvx ruff check .` |

## Inspecting

| Goal | Template | Example |
|---|---|---|
| List installed libraries | `uv pip list` | `uv pip list` |
| Show the dependency tree | `uv tree` | `uv tree` |

## Files uv manages

- `pyproject.toml`: the shopping list (what the project needs). Commit it.
- `uv.lock`: the exact versions installed. Commit it.
- `.venv/`: the installed libraries. Do not commit it.
