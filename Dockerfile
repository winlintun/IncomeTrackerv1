FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=3000

WORKDIR /app

RUN groupadd --system appuser \
    && useradd --system --gid appuser --home-dir /app --shell /usr/sbin/nologin appuser

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=appuser:appuser app.py db_init.py extensions.py models.py security.py validators.py ./
COPY --chown=appuser:appuser routes ./routes
COPY --chown=appuser:appuser templates ./templates
COPY --chown=appuser:appuser static ./static

USER appuser

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/api/health/db' % os.getenv('PORT', '3000'), timeout=3)" || exit 1

CMD ["sh", "-c", "exec gunicorn app:app --bind 0.0.0.0:${PORT:-3000} --workers 2 --timeout 120"]
