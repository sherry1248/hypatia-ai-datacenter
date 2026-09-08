FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8000 \
    SCENARIO=NORMAL_BURST \
    LOG_LEVEL=INFO

RUN groupadd --system app && useradd --system --gid app --home-dir /app app
WORKDIR /app

RUN pip install --no-cache-dir prometheus-client==0.20.0

COPY --chown=app:app satgenpy/ai_datacenter /app/satgenpy/ai_datacenter
COPY --chown=app:app satgenpy/demo_data /app/satgenpy/demo_data

USER app
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/ready', timeout=2)"

CMD ["python", "-m", "satgenpy.ai_datacenter.metrics_server"]
