from pathlib import Path

from app.core.config import settings


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def persistent_storage_root() -> Path:
    configured = str(settings.document_archive_root or "").strip()
    root = Path(configured).expanduser() if configured else PROJECT_ROOT / "uploads" / "documents"
    if not root.is_absolute():
        root = PROJECT_ROOT / root
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def persistent_import_storage_root(namespace: str) -> Path:
    safe_namespace = "".join(
        character if character.isalnum() or character in {"-", "_"} else "_"
        for character in namespace.strip()
    ).strip("_")
    if not safe_namespace:
        raise ValueError("O namespace de armazenamento é obrigatório.")
    root = persistent_storage_root() / "_imports" / safe_namespace
    root.mkdir(parents=True, exist_ok=True)
    return root
