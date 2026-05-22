# syntax=docker/dockerfile:1
FROM python:3.12-slim

# Don't write .pyc files; don't buffer stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py ./

# Cloud Run Jobs execute the ENTRYPOINT to completion and exit.
# No server / port binding needed.
ENTRYPOINT ["python", "main.py"]
