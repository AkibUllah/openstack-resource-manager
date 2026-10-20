# syntax=docker/dockerfile:1
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    OSRM_BACKEND=fake

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

COPY pyproject.toml README.md ./
COPY src ./src
# Install with the real OpenStack backend; drop "[openstack]" for a fixtures-only image.
RUN pip install --upgrade pip && pip install ".[openstack]"

USER app
# Mount clouds.yaml at /home/app/.config/openstack/clouds.yaml and set OS_CLOUD + OSRM_BACKEND=openstack.
ENTRYPOINT ["osrm"]
CMD ["--help"]
