FROM mcr.microsoft.com/devcontainers/python:1-3.13-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        git \
        poppler-utils \
        postgresql-client \
        tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

USER vscode
