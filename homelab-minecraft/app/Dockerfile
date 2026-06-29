FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    openjdk-17-jre-headless wget curl \
    && rm -rf /var/lib/apt/lists/*
RUN pip install flask psutil mcrcon --no-cache-dir
WORKDIR /app
COPY app.py .
EXPOSE 5770
CMD ["python", "-u", "app.py"]
