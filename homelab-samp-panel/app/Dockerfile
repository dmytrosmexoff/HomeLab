FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    wine \
    wine32 \
    lib32gcc-s1 \
    procps \
    --no-install-recommends && \
    rm -rf /var/lib/apt/lists/*

RUN pip install flask --no-cache-dir

COPY app.py .

RUN mkdir -p /data /server

EXPOSE 5750

CMD ["python", "app.py"]
