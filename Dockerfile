FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml alembic.ini ./
COPY app ./app
COPY migrations ./migrations
COPY .git ./.git

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && git config --global --add safe.directory /app \
    && pip install --no-cache-dir . \
    && apt-get purge -y --auto-remove git \
    && rm -rf .git /var/lib/apt/lists/*

RUN mkdir -p /app/data
VOLUME ["/app/data"]

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
