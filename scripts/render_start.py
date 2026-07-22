import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, urlunparse


DB_ENV_KEYS = (
    "CARFAST_DATABASE_URL",
    "DATABASE_URL",
    "RENDER_DATABASE_URL",
    "DATABASE_URL_FALLBACK",
)


def run(command: list[str], *, retries: int = 0, delay_seconds: int = 2, env: dict[str, str] | None = None) -> None:
    attempts = max(retries, 1)
    for attempt in range(1, attempts + 1):
        try:
            subprocess.run(command, check=True, env=env)
            return
        except subprocess.CalledProcessError as exc:
            if attempt >= attempts:
                print(f"[render_start] Falha persistente ao correr: {' '.join(command)}")
                raise

            print(f"[render_start] Falha ao correr {' '.join(command)} (tentativa {attempt}/{attempts})")
            print(f"[render_start] Código de saída: {exc.returncode}. A repetir dentro de {delay_seconds}s...")
            time.sleep(delay_seconds)
            delay_seconds = min(delay_seconds * 2, 30)


def safe_database_url(database_url: str) -> str:
    parsed = urlparse(database_url)
    if not parsed.password:
        return database_url
    username = parsed.username or ""
    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    netloc = f"{username}:***@{host}{port}"
    return urlunparse(parsed._replace(netloc=netloc))


def host_resolvable(hostname: str | None) -> bool:
    if not hostname:
        return False
    try:
        socket.gethostbyname(hostname)
        return True
    except socket.gaierror:
        return False


def collect_database_urls() -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    seen: set[str] = set()
    for key in DB_ENV_KEYS:
        value = os.environ.get(key)
        if value and value not in seen:
            candidates.append((key, value))
            seen.add(value)
    return candidates


def assert_render_database_url(key: str, database_url: str) -> None:
    parsed = urlparse(database_url)
    host = parsed.hostname or ""
    if not host:
        raise RuntimeError(f"{key} não tem host válido: {safe_database_url(database_url)}")

    if host.startswith("dpg-") and "." not in host:
        raise RuntimeError(
            f"{key} usa host interno curto '{host}', mas este serviço não o consegue resolver. "
            "No Render, ligue a base via Environment > Add from database para DATABASE_URL, "
            "ou copie o External Database URL completo da página da base para CARFAST_DATABASE_URL."
        )

    if not host_resolvable(host):
        raise RuntimeError(
            f"{key} aponta para host sem resolução DNS: '{host}'. "
            "Copie novamente o External Database URL atual do PostgreSQL no Render."
        )


def choose_database_url() -> str:
    candidates = collect_database_urls()
    if not candidates:
        db_keys = [k for k in os.environ.keys() if "DB" in k.upper() or "DATABASE" in k.upper() or "POSTGRES" in k.upper()]
        print("[render_start] Nenhuma variável de base de dados definida.")
        print(f"[render_start] Variáveis DB visíveis: {sorted(db_keys)}")
        raise RuntimeError(
            "Definir DATABASE_URL via Add from database no Render, ou CARFAST_DATABASE_URL com o External Database URL."
        )

    print(f"[render_start] Candidatos de base: {len(candidates)}")
    last_error: Exception | None = None
    for index, (key, database_url) in enumerate(candidates, start=1):
        parsed = urlparse(database_url)
        print(
            f"[render_start] candidato_{index}: key={key} backend={parsed.scheme or 'n/a'} "
            f"host={parsed.hostname or 'n/a'} port={parsed.port or 5432}"
        )
        try:
            assert_render_database_url(key, database_url)
            print(f"[render_start] candidato_{index} selecionado: {key}")
            return database_url
        except RuntimeError as exc:
            last_error = exc
            print(f"[render_start] candidato_{index} inválido: {exc}")

    raise RuntimeError(f"Nenhum candidato de base de dados válido. Último erro: {last_error}")


def prepare_document_storage() -> None:
    project_root = Path(__file__).resolve().parents[1]
    project_archive = project_root / "uploads" / "documents"
    configured_root = os.environ.get("DOCUMENT_ARCHIVE_ROOT", "").strip()
    configured_invoice_inbox = os.environ.get("DOCUMENT_INVOICE_INBOX_PATH", "").strip()
    is_production = os.environ.get("APP_ENV", "").strip().lower() == "production"
    allow_ephemeral_bridge = os.environ.get("CARFAST_ALLOW_EPHEMERAL_DOCUMENT_STORAGE", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    require_persistent = (is_production and not allow_ephemeral_bridge) or os.environ.get(
        "CARFAST_REQUIRE_PERSISTENT_DOCUMENT_STORAGE",
        "",
    ).strip().lower() in {
        "1",
        "true",
        "yes",
    }

    candidate_roots: list[tuple[Path, bool]] = []
    if configured_root:
        configured_path = Path(configured_root).expanduser()
        candidate_roots.append((configured_path, not _is_render_ephemeral_path(configured_path, project_root)))
    elif is_production:
        candidate_roots.append((Path("/var/data/carfast_documents"), True))
        if allow_ephemeral_bridge:
            candidate_roots.append((project_archive, False))
    else:
        candidate_roots.append((project_archive, False))

    errors: list[str] = []
    for archive_path, is_persistent_candidate in candidate_roots:
        if require_persistent and not is_persistent_candidate:
            errors.append(f"{archive_path}: caminho nao persistente bloqueado")
            print(
                "[render_start] storage documental bloqueado: "
                f"{archive_path} fica dentro do deploy e pode perder ficheiros."
            )
            continue
        try:
            _ensure_writable_folder(archive_path)
            if configured_invoice_inbox and is_persistent_candidate:
                invoice_inbox = Path(configured_invoice_inbox).expanduser()
            else:
                invoice_inbox = archive_path / "Frota" / "_POR_ASSOCIAR" / "_Entrada_Documental" / "Faturas"
            _ensure_writable_folder(invoice_inbox)
        except OSError as exc:
            errors.append(f"{archive_path}: {exc}")
            print(f"[render_start] storage indisponivel em {archive_path}: {exc}")
            continue

        if is_production and not is_persistent_candidate:
            warning = (
                "[render_start] AVISO: storage persistente indisponivel; "
                f"a usar fallback nao persistente em {archive_path}. "
                "Nao carregar documentacao definitiva ate confirmar o disco do Render."
            )
            if require_persistent:
                raise RuntimeError(f"{warning} Erros anteriores: {' | '.join(errors)}")
            print(warning)

        os.environ["DOCUMENT_ARCHIVE_ROOT"] = str(archive_path)
        os.environ["DOCUMENT_INVOICE_INBOX_PATH"] = str(invoice_inbox)
        print(f"[render_start] DOCUMENT_ARCHIVE_ROOT pronto: {archive_path}")
        print(f"[render_start] DOCUMENT_INVOICE_INBOX_PATH pronto: {invoice_inbox}")
        return

    raise RuntimeError(f"Nenhuma pasta de arquivo documental ficou escrevivel: {' | '.join(errors)}")


def _is_render_ephemeral_path(path: Path, project_root: Path) -> bool:
    absolute_path = path if path.is_absolute() else project_root / path
    try:
        if absolute_path.resolve().is_relative_to(project_root.resolve()):
            return True
    except OSError:
        return False
    return str(absolute_path).replace("\\", "/").startswith("/opt/render/project/")


def _ensure_writable_folder(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    test_file = folder / ".carfast_write_test"
    test_file.write_text("ok", encoding="utf-8")
    test_file.unlink(missing_ok=True)


def main() -> None:
    port = os.environ.get("PORT", "10000")
    database_url = choose_database_url()
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    prepare_document_storage()
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url

    run([sys.executable, "-m", "alembic", "upgrade", "head"], retries=5, delay_seconds=2, env=env)
    if os.environ.get("CARFAST_ADMIN_EMAIL") and os.environ.get("CARFAST_ADMIN_PASSWORD"):
        run([sys.executable, "scripts/create_admin.py"], env=env)
    one_off_reassign = os.environ.get("CARFAST_ONE_OFF_202605_ANDRE_TASKS_TO_CREATORS", "").strip().lower()
    if one_off_reassign in {"dry-run", "apply"}:
        command = [sys.executable, "scripts/reassign_andre_tasks_to_creators.py"]
        if one_off_reassign == "apply":
            command.append("--apply")
        run(command, env=env)
    run([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", port], env=env)


if __name__ == "__main__":
    main()
