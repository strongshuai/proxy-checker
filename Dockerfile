FROM public.ecr.aws/docker/library/python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    CHROME_BIN=/usr/bin/chromium \
    CHROMIUM_PATH=/usr/bin/chromium

WORKDIR /opt/proxy-checker

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        fonts-liberation \
        fonts-noto-cjk \
        nodejs \
        rsync \
        tini \
        tzdata \
        xvfb \
        chromium \
    && ln -sf /usr/bin/chromium /usr/bin/google-chrome \
    && ln -sf /usr/bin/chromium /usr/bin/chromium-browser \
    && rm -rf /var/lib/apt/lists/*

COPY "requirements.txt" "/opt/proxy-checker/requirements.txt"

RUN python -m pip install --upgrade pip \
    && python -m pip install -r "/opt/proxy-checker/requirements.txt" \
    && python -m playwright install --with-deps chromium

COPY . "/opt/proxy-checker/"

RUN chmod +x "/opt/proxy-checker/docker-entrypoint.sh"

WORKDIR /app

EXPOSE 8888

ENTRYPOINT ["/usr/bin/tini", "--", "/opt/proxy-checker/docker-entrypoint.sh"]
CMD ["python", "server.py"]
