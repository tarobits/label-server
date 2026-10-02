FROM node:22-slim AS frontend
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /srv/labels
COPY pyproject.toml requirements.lock ./
COPY app ./app
RUN pip install --no-cache-dir -c requirements.lock . \
    && useradd --uid 10001 --create-home labels \
    && mkdir /srv/labels/data \
    && chown labels:labels /srv/labels/data
COPY alembic.ini ./
COPY migrations ./migrations
COPY --from=frontend /ui/dist ./frontend/dist
USER labels
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000"]
