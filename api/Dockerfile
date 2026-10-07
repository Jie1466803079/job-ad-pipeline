# The build context is the repository root (see docker-compose.yml).

FROM node:24-slim AS page
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 WEB_DIR=/app/web
WORKDIR /app
COPY api/pyproject.toml ./
COPY api/jobpipe ./jobpipe
RUN pip install --no-cache-dir . && useradd --system --no-create-home jobpipe
COPY --from=page /web/dist ./web
USER jobpipe
EXPOSE 8000
CMD ["uvicorn", "jobpipe.main:app", "--host", "0.0.0.0", "--port", "8000"]
