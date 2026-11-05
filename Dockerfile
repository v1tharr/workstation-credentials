FROM python:3.12-slim AS builder
WORKDIR /install
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install/deps -r requirements.txt


FROM python:3.12-slim

RUN useradd -m -u 1001 appuser
WORKDIR /app

COPY --from=builder /install/deps /usr/local
COPY app ./app
COPY manage.py .
COPY examples ./examples

# том с БД создаётся с правами appuser, chown на хосте не нужен
RUN mkdir /app/data && chown appuser /app/data

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DB_PATH=/app/data/creds.db

USER appuser
EXPOSE 5000

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--timeout", "60", "app:create_app()"]
