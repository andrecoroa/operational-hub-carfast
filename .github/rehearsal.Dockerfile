FROM postgres:17-bookworm

WORKDIR /workspace
COPY requirements.txt requirements-dev.txt ./
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /opt/carfast-venv \
    && /opt/carfast-venv/bin/pip install --no-cache-dir -r requirements-dev.txt
COPY . .
ENV PATH="/opt/carfast-venv/bin:${PATH}"

CMD ["python", "-m", "scripts.validate_isolated_environment"]
