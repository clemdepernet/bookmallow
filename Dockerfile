# syntax=docker/dockerfile:1
FROM python:3.14-slim AS base
ARG TARGETARCH
ARG DENO_VERSION=2.9.7
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# ffmpeg converts, gosu drops privileges, deno is the JavaScript runtime yt-dlp needs for YouTube.
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ffmpeg gosu ca-certificates curl unzip; \
    case "${TARGETARCH:-$(dpkg --print-architecture)}" in \
      amd64) DENO_ARCH=x86_64 ;; \
      arm64) DENO_ARCH=aarch64 ;; \
      *) echo "unsupported architecture: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    curl -fsSL -o /tmp/deno.zip "https://github.com/denoland/deno/releases/download/v${DENO_VERSION}/deno-${DENO_ARCH}-unknown-linux-gnu.zip"; \
    unzip -q /tmp/deno.zip -d /usr/local/bin; \
    rm /tmp/deno.zip; \
    chmod +x /usr/local/bin/deno; \
    apt-get purge -y curl unzip; \
    apt-get autoremove -y; \
    rm -rf /var/lib/apt/lists/*; \
    deno --version; \
    ffmpeg -version | head -n 1

WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt
COPY bookmallow ./bookmallow
COPY wsgi.py entrypoint.sh ./
RUN chmod +x /app/entrypoint.sh \
 && useradd --system --uid 1000 --create-home --shell /usr/sbin/nologin bookmallow

# ---- test stage: `docker build --target test .` runs the suite inside the real image ----
FROM base AS test
COPY requirements-dev.txt pyproject.toml ./
COPY tests ./tests
RUN pip install -r requirements-dev.txt && pytest

# ---- runtime ------------------------------------------------------------------------------
FROM base AS runtime
ENV DATA_DIR=/data \
    PUID=1000 \
    PGID=1000
VOLUME ["/data"]
EXPOSE 5000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5000/healthz', timeout=3).status == 200 else 1)"
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "8", "--timeout", "300", "--access-logfile", "-", "wsgi:app"]
