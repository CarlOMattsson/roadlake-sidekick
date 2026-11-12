# Two stages. The builder has uv and installs the locked dependencies into a venv; the runtime stage is the same
# digest-pinned python base plus that venv and the app, so the image that runs holds no package manager.
# Tag python:3.13.13-slim, pinned by manifest-list digest (resolved 2026-11-10).
FROM python:3.15.0-slim@sha256:f5b92f2a669a4c347044f29367f31983280b648250ca94dea66f98c53bc87e58 AS builder

# The venv's python is a symlink to the base image's interpreter, so uv must use that one and never fetch its own.
ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy UV_COMPILE_BYTECODE=0
WORKDIR /app
# uv 0.11.8, pinned by manifest-list digest (resolved 2026-11-10; tools/pin-image-digests.sh re-pins).
COPY --from=ghcr.io/astral-sh/uv:0.11.8@sha256:3b7b60a81d3c57ef471703e5c83fd4aaa33abcd403596fb22ab07db85ae91347 /uv /usr/local/bin/uv
COPY backend/pyproject.toml backend/uv.lock ./backend/
# Dependencies first (a cached layer that only changes with the lock file), then the one copy of the source, then the
# project itself as an editable install: the venv gets the console scripts (sidekick-admin, sidekick-backup, the
# workers) and a .pth pointing at /app/backend/src. Editable on purpose: the code finds ./migrations and the build
# info relative to its own path (sidekick.shared.readiness), which a copy inside site-packages would break.
RUN cd backend && uv sync --frozen --no-dev --no-install-project
COPY backend/src ./backend/src
RUN chmod -R a+rX ./backend/src
RUN cd backend && uv sync --frozen --no-dev

# Tag python:3.13.13-slim, pinned by manifest-list digest (resolved 2026-11-10).
FROM python:3.15.0-slim@sha256:f5b92f2a669a4c347044f29367f31983280b648250ca94dea66f98c53bc87e58 AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
# The image is for running an instance, so it defaults to production: the interactive API docs are off
# and Settings refuses development secrets and a missing database URL. A container can override it
# (`-e SIDEKICK_ENVIRONMENT=development`); the compose files set it explicitly anyway.
ENV SIDEKICK_ENVIRONMENT=production
WORKDIR /app

RUN groupadd --system sidekick && useradd --system --gid sidekick --home-dir /app sidekick \
    && install -d -o sidekick -g sidekick -m 0700 /var/lib/sidekick
# The venv keeps its build path (/app/backend/.venv), which its scripts and symlinks point at.
COPY --from=builder /app/backend/.venv ./backend/.venv
# The source comes from the builder (the venv's editable install points at it); the build context is read once.
COPY --from=builder /app/backend/src ./backend/src
COPY migrations ./migrations
# The licenses travel with the image (MIT/BSD/Apache notices, LGPL section 4 and the GPL-3 text, pointers to the
# source of the LGPL wheels and the Debian base): LICENSE.md and THIRD_PARTY_NOTICES.md are generated or kept at the
# repository root, licenses/ holds the license texts and SOURCES.md.
COPY LICENSE.md THIRD_PARTY_NOTICES.md /usr/share/doc/sidekick/
COPY licenses /usr/share/doc/sidekick/licenses
RUN chmod -R a+rX ./backend/src ./migrations /usr/share/doc/sidekick

ARG SIDEKICK_MIGRATION_CLASS=unknown
ARG SIDEKICK_SCHEMA_HEAD=unknown
# Oldest installed version this image can be updated from (update.sh refuses a jump that skips a stepping-stone).
ARG SIDEKICK_MIN_UPGRADE_FROM=unknown
LABEL io.sidekick.migration-class="${SIDEKICK_MIGRATION_CLASS}" \
      io.sidekick.schema-head="${SIDEKICK_SCHEMA_HEAD}" \
      io.sidekick.min-upgrade-from="${SIDEKICK_MIN_UPGRADE_FROM}" \
      org.opencontainers.image.source="https://github.com/CarlOMattsson/roadlake-sidekick" \
      org.opencontainers.image.licenses="LicenseRef-Roadlake-Sidekick-Source-Available"

# The image holds no history, so the build says which commit it is: the app counts the age of the
# code from these two for the update reminder (sidekick.shared.build_info). Empty means unknown.
ARG SIDEKICK_BUILD_COMMIT=
ARG SIDEKICK_BUILD_DATE=
ENV SIDEKICK_BUILD_COMMIT=${SIDEKICK_BUILD_COMMIT} SIDEKICK_BUILD_DATE=${SIDEKICK_BUILD_DATE}

USER sidekick
ENV PATH="/app/backend/.venv/bin:$PATH"
EXPOSE 8000
CMD ["uvicorn", "sidekick.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
# Liveness for the container that serves HTTP (pid 1 is uvicorn): only HTTP 200 from /health/live is healthy. Any
# other status (404, 500, ...), a refused port or a silent port fails. In github_oauth mode the public surface answers
# 404 for /health/*; the compose files define their own healthchecks that know that, so this default is for a plain
# `docker run`. The same image also runs workers and one-shot jobs with no port, so those count as healthy.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request\nif b'uvicorn' not in open('/proc/1/cmdline', 'rb').read():\n    sys.exit(0)\ntry:\n    ok = urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=3).status == 200\nexcept Exception:\n    ok = False\nsys.exit(0 if ok else 1)"]
