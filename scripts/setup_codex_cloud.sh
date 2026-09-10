#!/usr/bin/env bash
set -euo pipefail

REPOSITORY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPOSITORY_ROOT"

python_command="python"
python_minor="$($python_command -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"

if [[ "$python_minor" != "3.13" ]]; then
    if ! command -v uv >/dev/null 2>&1; then
        echo "Python 3.13 is required. Pin Python 3.13 in the Codex Cloud environment settings." >&2
        exit 2
    fi

    uv python install 3.13
    if [[ ! -x .venv/bin/python ]] || [[ "$(.venv/bin/python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')" != "3.13" ]]; then
        uv venv --python 3.13 .venv
    fi
    uv pip install --python .venv/bin/python -r requirements-dev.txt
    python_command=".venv/bin/python"
else
    "$python_command" -m pip install --upgrade pip
    "$python_command" -m pip install -r requirements-dev.txt
fi

"$python_command" -c 'import sys; assert sys.version_info[:2] == (3, 13); print(sys.version.split()[0])'
echo "CarFast Codex Cloud dependencies are ready. Python command: $python_command"
