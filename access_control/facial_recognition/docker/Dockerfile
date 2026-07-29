ARG BASE_IMAGE=python:3.11-slim
FROM ${BASE_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libglib2.0-0 libgl1 curl \
    && rm -rf /var/lib/apt/lists/*

COPY access_control/facial_recognition/requirements.txt /app/access_control/facial_recognition/requirements.txt
RUN pip install --no-cache-dir -r /app/access_control/facial_recognition/requirements.txt

COPY access_control /app/access_control
RUN chmod +x /app/access_control/facial_recognition/docker/entrypoint.sh

EXPOSE 8080
ENTRYPOINT ["/app/access_control/facial_recognition/docker/entrypoint.sh"]
CMD ["uvicorn", "access_control.facial_recognition.src.api.main:app", "--host", "127.0.0.1", "--port", "8080"]
