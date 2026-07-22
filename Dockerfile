FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AGENT_DATA_DIR=/data \
    AGENT_DATABASE_PATH=/data/agent_platform.db \
    HOST=0.0.0.0 \
    PORT=8765

RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs npm tesseract-ocr tesseract-ocr-chi-sim \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt package.json package-lock.json ./
RUN pip install --no-cache-dir -r requirements.txt \
    && npm ci --omit=dev \
    && useradd --create-home --uid 10001 agent \
    && mkdir -p /data \
    && chown -R agent:agent /app /data

COPY --chown=agent:agent server ./server
COPY --chown=agent:agent web ./web
COPY --chown=agent:agent scripts ./scripts

USER agent
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import json,urllib.request; data=json.load(urllib.request.urlopen('http://127.0.0.1:8765/api/health',timeout=3)); raise SystemExit(0 if data.get('ok') else 1)"

CMD ["python", "-m", "server"]
