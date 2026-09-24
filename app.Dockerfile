# syntax=docker/dockerfile:1.27
# Runtime image (builder → runner); the devcontainer image is the
# base-owned `Dockerfile`'s `develop` stage.

# renovate: datasource=python-version depName=python
ARG PYTHON_VERSION=3.14.7
ARG DEBIAN_VERSION=trixie

# renovate: datasource=github-releases depName=astral-sh/uv
ARG UV_VERSION=0.12.17

ARG APP_UID=1000

ARG SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
ARG SSL_CERT_DIR=/etc/ssl/certs

########################################
# builder — installs dependencies into a venv and installs the app
########################################
FROM python:${PYTHON_VERSION}-slim-${DEBIAN_VERSION} AS builder
ARG UV_VERSION
ARG SSL_CERT_FILE
ARG SSL_CERT_DIR

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    SSL_CERT_FILE=${SSL_CERT_FILE} \
    SSL_CERT_DIR=${SSL_CERT_DIR} \
    REQUESTS_CA_BUNDLE=${SSL_CERT_FILE} \
    CURL_CA_BUNDLE=${SSL_CERT_FILE}

COPY scripts/builder.sh /tmp/builder.sh
RUN bash /tmp/builder.sh "$UV_VERSION"

WORKDIR /build
COPY pyproject.toml uv.lock ./
COPY scripts/builder-sync-deps.sh /tmp/builder-sync-deps.sh
RUN --mount=type=cache,target=/root/.cache/uv \
    bash /tmp/builder-sync-deps.sh

COPY src ./src
COPY scripts/builder-sync-app.sh /tmp/builder-sync-app.sh
RUN --mount=type=cache,target=/root/.cache/uv \
    bash /tmp/builder-sync-app.sh

########################################
# runner — minimal runtime image: just the venv, installed non-editable.
# Runs under an arbitrary UID (e.g. OpenShift's restricted SCC) as well as
# a fixed one — see runner-setup.sh and the --chown/--chmod below.
########################################
FROM python:${PYTHON_VERSION}-slim-${DEBIAN_VERSION} AS runner
ARG APP_UID
ARG SSL_CERT_FILE
ARG SSL_CERT_DIR

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:${PATH}" \
    HOME=/home/appuser \
    SSL_CERT_FILE=${SSL_CERT_FILE} \
    SSL_CERT_DIR=${SSL_CERT_DIR} \
    REQUESTS_CA_BUNDLE=${SSL_CERT_FILE} \
    CURL_CA_BUNDLE=${SSL_CERT_FILE} \
    MODE=production

COPY scripts/runner.sh /usr/local/bin/runner.sh
# Group 0, not the numeric owner, is what an arbitrary UID actually gets
# under OpenShift's restricted SCC — see runner-setup.sh's comment. Set
# here rather than with a recursive RUN chmod, which would be slow over a
# whole venv.
COPY --from=builder --chown=${APP_UID}:0 --chmod=750 /opt/venv /opt/venv
WORKDIR /app

# alembic.ini/alembic/ aren't part of the installed app package (see src/README.md's
# "Don't put fixtures/sample data/documentation here"), so they need copying in
# explicitly for app.main's lifespan hook to find at its CWD-relative "alembic.ini"
# and auto-apply pending migrations on startup -- see CLAUDE.md's "Alembic" section.
COPY alembic.ini ./
COPY alembic ./alembic/

COPY scripts/runner-setup.sh /tmp/runner-setup.sh
RUN bash /tmp/runner-setup.sh "$APP_UID"

USER $APP_UID
EXPOSE 8000
ENTRYPOINT ["runner.sh"]
