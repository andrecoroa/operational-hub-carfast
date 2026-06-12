import os
import socket
import subprocess
import sys
import time
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


def main() -> None:
    port = os.environ.get("PORT", "10000")
    database_url = choose_database_url()
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
