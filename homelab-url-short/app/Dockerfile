FROM python:3.11-slim

WORKDIR /app

RUN pip install flask --no-cache-dir

COPY app.py .

RUN mkdir -p /data

EXPOSE 5656

CMD ["python", "app.py"]
