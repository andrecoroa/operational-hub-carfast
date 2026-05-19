import os
import subprocess
import sys


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def main() -> None:
    port = os.environ.get("PORT", "10000")
    run([sys.executable, "-m", "alembic", "upgrade", "head"])
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
