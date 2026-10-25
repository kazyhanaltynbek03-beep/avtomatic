FROM node:22-bookworm-slim AS ui
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run lint
RUN npm run build
FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 FRONTEND_DIST=/srv/frontend UPLOAD_DIR=/srv/uploads
WORKDIR /srv/backend
COPY backend/requirements.lock ./requirements.lock
RUN pip install --no-cache-dir -r requirements.lock && useradd --create-home --uid 10001 app
COPY backend/ ./
COPY --from=ui /build/dist /srv/frontend
RUN mkdir -p /srv/uploads && chown -R app:app /srv
USER app
EXPOSE 8000
CMD ["sh","-c","alembic upgrade head && python -m app.seed && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
