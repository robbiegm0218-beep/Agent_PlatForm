FROM node:22-alpine AS node-dependencies

WORKDIR /node-dependencies
COPY package.json package-lock.json ./
RUN npm ci --omit=dev


# Pinned after Docker Scout verified this Python 3.13 Alpine manifest has no
# Critical/High CVEs. Refresh intentionally through the image-security task.
FROM python:3.13-alpine@sha256:399babc8b49529dabfd9c922f2b5eea81d611e4512e3ed250d75bd2e7683f4b0

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AGENT_DATA_DIR=/data \
    AGENT_DATABASE_PATH=/data/agent_platform.db \
    HOST=0.0.0.0 \
    PORT=8765

RUN apk add --no-cache \
        nodejs \
        tesseract-ocr \
        tesseract-ocr-data-chi_sim \
        tesseract-ocr-data-eng \
        tesseract-ocr-data-osd

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && adduser -D -u 10001 agent \
    && mkdir -p /data \
    && chown -R agent:agent /app /data

# Alpine's nodejs runtime is installed without npm. Only the application-level
# Excel dependency is copied from the build stage.
COPY --from=node-dependencies --chown=agent:agent /node-dependencies/node_modules ./node_modules
COPY --chown=agent:agent server ./server
COPY --chown=agent:agent web ./web
COPY --chown=agent:agent scripts ./scripts

USER agent
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import json,urllib.request; data=json.load(urllib.request.urlopen('http://127.0.0.1:8765/api/health',timeout=3)); raise SystemExit(0 if data.get('ok') else 1)"

CMD ["python", "-m", "server"]
