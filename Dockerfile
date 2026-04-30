FROM node:22-bookworm-slim AS frontend-build

WORKDIR /app/presentation-ui

COPY presentation-ui/package.json presentation-ui/package-lock.json ./
RUN npm ci

COPY presentation-ui ./
RUN npm run build


FROM python:3.11-slim AS app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md /app/

# Install heavyweight runtime dependencies from pyproject before copying source,
# course data, manifests, or frontend assets so those changes do not invalidate
# the expensive dependency layer. Do not upgrade pip/setuptools/wheel globally:
# the base image and PEP 517 build isolation provide the required tooling.
RUN python -c "import subprocess, sys, tomllib; deps = tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']; subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--no-cache-dir', *deps])"

COPY src /app/src
COPY db /app/db
RUN pip install --no-cache-dir --no-deps -e .

COPY data/course_pbs /app/data/course_pbs
COPY manifests/course_qa_cases*.jsonl manifests/course_ops_learning_golden_cases.jsonl /app/manifests/
COPY --from=frontend-build /app/presentation-ui/dist /app/presentation-ui/dist

EXPOSE 8765 8770

CMD ["python", "-m", "play_book_studio.cli", "ui", "--no-browser", "--host", "0.0.0.0", "--port", "8765"]


FROM nginx:1.27-alpine AS web

COPY deploy/nginx/default.conf /etc/nginx/conf.d/default.conf
COPY --from=frontend-build /app/presentation-ui/dist /usr/share/nginx/html

EXPOSE 80
