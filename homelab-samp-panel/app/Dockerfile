FROM python:3.11-slim
WORKDIR /app
RUN pip install flask psutil --no-cache-dir
COPY app.py .
ENV FLASK_ENV=production
EXPOSE 5750
CMD ["python", "-u", "app.py"]
