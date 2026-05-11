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
    run([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", port])


if __name__ == "__main__":
    main()
