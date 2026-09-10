FROM postgres:17-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt pyproject.toml ./
RUN python3 -m venv /opt/carfast-venv \
    && /opt/carfast-venv/bin/pip install --no-cache-dir -r requirements.txt
COPY . .
COPY deploy/rehearsal/entrypoint.sh /usr/local/bin/carfast-rehearsal-entrypoint
RUN chmod 0755 /usr/local/bin/carfast-rehearsal-entrypoint
ENTRYPOINT ["/usr/local/bin/carfast-rehearsal-entrypoint"]
