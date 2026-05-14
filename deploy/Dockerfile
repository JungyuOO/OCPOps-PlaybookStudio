FROM node:22-bookworm-slim AS frontend-build

WORKDIR /app/apps/web

COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci

COPY apps/web ./
RUN npm run build


FROM python:3.11-slim AS app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    build-essential \
    ca-certificates \
    curl \
    git \
    gzip \
    tar \
    && rm -rf /var/lib/apt/lists/*

ARG OC_CLIENT_ARCHIVE_URL=https://mirror.openshift.com/pub/openshift-v4/clients/ocp/stable/openshift-client-linux.tar.gz
RUN curl -fsSL "${OC_CLIENT_ARCHIVE_URL}" -o /tmp/openshift-client-linux.tar.gz \
    && tar -xzf /tmp/openshift-client-linux.tar.gz -C /usr/local/bin oc kubectl \
    && chmod +x /usr/local/bin/oc /usr/local/bin/kubectl \
    && rm -f /tmp/openshift-client-linux.tar.gz

COPY pyproject.toml README.md /app/

# Install heavyweight runtime dependencies from pyproject before copying source
# or frontend assets so those changes do not invalidate the expensive dependency
# layer. Do not upgrade pip/setuptools/wheel globally:
# the base image and PEP 517 build isolation provide the required tooling.
RUN python -c "import subprocess, sys, tomllib; deps = tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']; subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--no-cache-dir', *deps])"

COPY src /app/src
COPY db /app/db
COPY corpus /app/corpus
COPY deploy/scripts /app/scripts
RUN chmod +x /app/scripts/*.sh
RUN pip install --no-cache-dir --no-deps -e .

COPY --from=frontend-build /app/apps/web/dist /app/apps/web/dist

EXPOSE 8765 8770

CMD ["python", "-m", "play_book_studio.cli", "ui", "--no-browser", "--host", "0.0.0.0", "--port", "8765"]


FROM nginx:1.27-alpine AS web

COPY deploy/nginx/default.conf /etc/nginx/conf.d/default.conf
COPY --from=frontend-build /app/apps/web/dist /usr/share/nginx/html
RUN chgrp -R 0 /var/cache/nginx /var/run /var/log/nginx /etc/nginx/conf.d /usr/share/nginx/html \
    && chmod -R g=u /var/cache/nginx /var/run /var/log/nginx /etc/nginx/conf.d /usr/share/nginx/html

EXPOSE 8080


FROM registry.access.redhat.com/ubi9/ubi-minimal AS sandbox

ARG OC_CLIENT_ARCHIVE_URL=https://mirror.openshift.com/pub/openshift-v4/clients/ocp/stable/openshift-client-linux.tar.gz

RUN microdnf install -y \
    bash \
    ca-certificates \
    findutils \
    grep \
    gzip \
    jq \
    less \
    procps-ng \
    tar \
    vim-minimal \
    && microdnf clean all \
    && rm -rf /var/cache/yum

RUN curl -fsSL "${OC_CLIENT_ARCHIVE_URL}" -o /tmp/openshift-client-linux.tar.gz \
    && tar -xzf /tmp/openshift-client-linux.tar.gz -C /usr/local/bin oc kubectl \
    && chmod +x /usr/local/bin/oc /usr/local/bin/kubectl \
    && rm -f /tmp/openshift-client-linux.tar.gz

RUN mkdir -p /home/learner /home/learner/.kube /etc/skel \
    && echo 'learner:x:1001:0:learner:/home/learner:/bin/bash' >> /etc/passwd \
    && printf '%s\n' \
      'export HOME=/home/learner' \
      'export KUBECONFIG=${KUBECONFIG:-/home/learner/.kube/config}' \
      'alias ll="ls -la"' \
      'PS1="[learner@\h \W]\\$ "' \
      > /etc/skel/.bashrc \
    && cp /etc/skel/.bashrc /home/learner/.bashrc \
    && chgrp -R 0 /home/learner /etc/skel \
    && chmod -R g=u /home/learner /etc/skel

ENV HOME=/home/learner \
    SHELL=/bin/bash \
    KUBECONFIG=/home/learner/.kube/config

WORKDIR /home/learner
USER 1001

CMD ["/bin/bash", "-lc", "sleep infinity"]
