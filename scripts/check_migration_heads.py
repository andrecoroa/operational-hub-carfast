"""Fail when the Alembic graph does not expose exactly one head."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    config = Config(project_root / "alembic.ini")
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()
    if len(heads) != 1:
        formatted = ", ".join(heads) if heads else "none"
        raise SystemExit(f"Expected exactly one Alembic head; found {len(heads)}: {formatted}")
    print(f"Alembic head: {heads[0]}")


if __name__ == "__main__":
    main()
