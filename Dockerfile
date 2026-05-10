FROM node:22-bookworm AS frontend-build

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl ffmpeg nodejs npm \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir yt-dlp yt-dlp-ejs

ENV DATABASE_URL=sqlite:///./data/app.db
ENV WHISPER_MODEL_SIZE=small
ENV WHISPER_COMPUTE_TYPE=int8
ENV HF_HOME=/app/data/huggingface
ENV HF_HUB_CACHE=/app/data/huggingface/hub
ENV HF_HUB_DISABLE_XET=1
ENV MIMO_TTS_TIMEOUT_SECONDS=600

COPY pyproject.toml ./
COPY backend ./backend
COPY --from=frontend-build /app/frontend/dist ./frontend/dist
RUN pip install --no-cache-dir .

EXPOSE 8000
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
