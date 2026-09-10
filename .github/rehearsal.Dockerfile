FROM python:3.13-slim

WORKDIR /workspace
COPY requirements.txt requirements-dev.txt ./
RUN python -m pip install --no-cache-dir -r requirements-dev.txt
COPY . .

CMD ["python", "-m", "scripts.validate_isolated_environment"]
