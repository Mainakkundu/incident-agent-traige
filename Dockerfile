FROM python:3.14-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

WORKDIR /app

RUN groupadd --system agent && useradd --system --gid agent --home /app agent

COPY requirements-api.txt ./
RUN pip install --no-cache-dir --requirement requirements-api.txt

COPY config ./config
COPY runbooks ./runbooks
COPY src ./src
COPY goldens.yaml ./goldens.yaml

RUN chown -R agent:agent /app
USER agent

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '8000') + '/health', timeout=3)"

CMD ["sh", "-c", "exec uvicorn src.runtime:create_app --factory --host 0.0.0.0 --port ${PORT:-8000}"]
