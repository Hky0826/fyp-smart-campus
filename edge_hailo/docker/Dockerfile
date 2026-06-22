ARG BASE_IMAGE=python:3.11-slim
FROM ${BASE_IMAGE}

ARG HAILORT_WHEEL=edge_hailo/docker/no-hailort-wheel.txt

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libglib2.0-0 libgl1 curl \
    && rm -rf /var/lib/apt/lists/*

COPY edge_hailo/requirements.txt /app/edge_hailo/requirements.txt
RUN pip install --no-cache-dir -r /app/edge_hailo/requirements.txt

COPY ${HAILORT_WHEEL} /tmp/hailort-wheel
RUN case "$HAILORT_WHEEL" in \
      *.whl) pip install --no-cache-dir /tmp/hailort-wheel ;; \
      *) echo "No HailoRT wheel supplied; image requires a HailoRT-enabled base image or wheel." ;; \
    esac

COPY edge_hailo /app/edge_hailo

EXPOSE 8080
CMD ["uvicorn", "edge_hailo.src.api.main:app", "--host", "0.0.0.0", "--port", "8080"]
