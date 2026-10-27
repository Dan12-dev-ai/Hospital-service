# Endod hospital service. Build from backend-hospital/:
#   docker build -t endod-hospital backend-hospital
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./
# /data/files holds record files (a volume in deploy/docker-compose.yml; a new
# volume takes this directory's owner, so the app user can write to it).
RUN useradd --create-home --uid 10002 hospital && mkdir -p /data/files   && chown -R hospital /app /data/files && chmod 700 /data/files
USER hospital
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"
# Migrations run separately, as the owner (the `migrate` service in
# deploy/docker-compose.yml); the API connects as the app role.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
