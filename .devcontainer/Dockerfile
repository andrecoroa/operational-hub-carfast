FROM mcr.microsoft.com/devcontainers/python:1-3.13-bookworm

# The upstream devcontainer image currently carries a Yarn APT source whose
# retired signing key can make otherwise unrelated package installation fail.
# CarFast does not use Yarn in this image, so remove only that optional source
# before refreshing the Debian package indexes.
RUN rm -f /etc/apt/sources.list.d/yarn.list /etc/apt/sources.list.d/yarn.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        git \
        poppler-utils \
        postgresql-client \
        tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

USER vscode
