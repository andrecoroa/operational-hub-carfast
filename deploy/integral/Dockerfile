FROM postgres:17-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv python3-pip tini && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN python3 -m venv /opt/carfast-venv && /opt/carfast-venv/bin/pip install --no-cache-dir -r /app/requirements.txt
COPY . /app
RUN groupadd --gid 10001 carfast && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin carfast && chown -R carfast:carfast /app
USER 10001:10001
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/bin/sh", "-c", "umask 077 && exec /opt/carfast-venv/bin/python -m scripts.integral_render_entrypoint"]
