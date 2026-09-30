# RAJAR Pulse for Snowpark Container Services (build for linux/amd64)

# 1. Build the React frontend on the build machine's own platform (static files are platform-independent,
#    and esbuild crashes under amd64 emulation on Apple Silicon)
FROM --platform=$BUILDPLATFORM node:22-slim AS frontend
WORKDIR /build
COPY app/frontend/package.json app/frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY app/frontend/ ./
RUN npm run build

# 2. Python API that also serves the built frontend
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv
COPY app/spcs/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY app/__init__.py app/__init__.py
COPY app/backend/ app/backend/
COPY semantic/offline/rajar_analytics_semantic_layer.yaml semantic/offline/rajar_analytics_semantic_layer.yaml
COPY --from=frontend /build/dist app/frontend/dist
RUN useradd --create-home pulse && mkdir -p app/.cache && chown -R pulse /srv
USER pulse
EXPOSE 8000
CMD ["uvicorn", "app.backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
