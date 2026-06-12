import os
import subprocess
import sys
import time
import socket
from urllib.parse import urlparse


def run(command: list[str], *, retries: int = 0, delay_seconds: int = 2, env: dict[str, str] | None = None) -> None:
    for attempt in range(1, retries + 1):
        try:
            subprocess.run(command, check=True, env=env)
            return
        except subprocess.CalledProcessError as exc:
            if attempt >= retries:
                print(f"[render_start] Falha persistente ao correr: {' '.join(command)}")
                raise

            print(f"[render_start] Falha temporária ao correr {' '.join(command)} (tentativa {attempt}/{retries})")
            print(f"[render_start] Código de saída: {exc.returncode}. A repetir dentro de {delay_seconds}s...")
            time.sleep(delay_seconds)
            delay_seconds = min(delay_seconds * 2, 30)


def host_resolvable(hostname: str | None) -> bool:
    if not hostname:
        return False
    try:
        socket.gethostbyname(hostname)
        return True
    except socket.gaierror:
        return False


def main() -> None:
    port = os.environ.get("PORT", "10000")
    candidates: list[str] = []
    for key in ("RENDER_DATABASE_URL", "CARFAST_DATABASE_URL", "DATABASE_URL_FALLBACK", "DATABASE_URL"):
        value = os.environ.get(key)
        if value and value not in candidates:
            candidates.append(value)

    if not candidates:
        print("[render_start] Nenhuma DATABASE_URL definida antes do arranque.")
    else:
        print(f"[render_start] Candidatos de base: {len(candidates)}")
        for index, candidate in enumerate(candidates, start=1):
            parsed = urlparse(candidate)
            print(
                f"[render_start] candidato_{index}: backend={parsed.scheme or 'n/a'} host={parsed.hostname or 'n/a'} "
                f"port={parsed.port or 5432}"
            )

    if not candidates:
        raise RuntimeError("A variável DATABASE_URL (ou equivalente) não está definida.")

    candidate_used = False
    last_error: Exception | None = None
    for index, database_url in enumerate(candidates, start=1):
        env = os.environ.copy()
        env["DATABASE_URL"] = database_url
        parsed = urlparse(database_url)
        if not host_resolvable(parsed.hostname):
            print(f"[render_start] candidato_{index} ignorado: host={parsed.hostname} não resolve.")
            continue
        candidate_used = True
        try:
            print(f"[render_start] A correr migracoes no candidato_{index}")
            run([sys.executable, "-m", "alembic", "upgrade", "head"], retries=5, delay_seconds=2, env=env)
            print(f"[render_start] Migracoes aplicadas com sucesso no candidato_{index}")
            break
        except subprocess.CalledProcessError as exc:
            last_error = exc
            print(f"[render_start] Candidato_{index} falhou: {exc}")
            if index < len(candidates):
                continue
            raise
    else:
        if not candidate_used:
            raise RuntimeError("Todos os candidatos de base foram ignorados (hosts sem resolução DNS). Verificar credenciais/hosts.")
        if last_error is not None:
            raise last_error

    if os.environ.get("CARFAST_ADMIN_EMAIL") and os.environ.get("CARFAST_ADMIN_PASSWORD"):
        run([sys.executable, "scripts/create_admin.py"])
    one_off_reassign = os.environ.get("CARFAST_ONE_OFF_202605_ANDRE_TASKS_TO_CREATORS", "").strip().lower()
    if one_off_reassign in {"dry-run", "apply"}:
        command = [sys.executable, "scripts/reassign_andre_tasks_to_creators.py"]
        if one_off_reassign == "apply":
            command.append("--apply")
        run(command)
    run([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", port])


if __name__ == "__main__":
    main()
