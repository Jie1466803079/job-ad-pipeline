FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml ./
COPY jobpipe ./jobpipe
RUN pip install --no-cache-dir .
EXPOSE 8000
CMD ["uvicorn", "jobpipe.main:app", "--host", "0.0.0.0", "--port", "8000"]
