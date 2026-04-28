FROM node:22-bookworm-slim AS frontend-build

WORKDIR /app/presentation-ui

COPY presentation-ui/package.json presentation-ui/package-lock.json ./
RUN npm ci

COPY presentation-ui ./
RUN npm run build


FROM python:3.11-slim AS app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md /app/
COPY src /app/src
COPY --from=frontend-build /app/presentation-ui/dist /app/presentation-ui/dist

RUN pip install --upgrade pip setuptools wheel && \
    pip install -e .

EXPOSE 8876

CMD ["python", "-m", "play_book_studio.cli", "ui", "--no-browser", "--host", "0.0.0.0", "--port", "8876"]


FROM nginx:1.27-alpine AS web

COPY deploy/nginx/default.conf /etc/nginx/conf.d/default.conf
COPY --from=frontend-build /app/presentation-ui/dist /usr/share/nginx/html

EXPOSE 80
