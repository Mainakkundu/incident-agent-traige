FROM python:3.14-slim

WORKDIR /app
RUN pip install --no-cache-dir fastapi httpx uvicorn
COPY services /app/services

ENV PYTHONPATH=/app
