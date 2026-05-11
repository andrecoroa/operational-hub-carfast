import os
import subprocess
import sys


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def main() -> None:
    port = os.environ.get("PORT", "10000")
    run([sys.executable, "-m", "alembic", "upgrade", "head"])
    run([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", port])


if __name__ == "__main__":
    main()
