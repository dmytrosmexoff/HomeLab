FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    procps curl && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir flask psutil requests gunicorn

COPY app.py .

RUN mkdir -p /data /server

EXPOSE 4850

CMD ["gunicorn", "--bind", "0.0.0.0:4850", "--workers", "2", "--timeout", "120", "app:app"]
