FROM python:3.11-slim
WORKDIR /app
RUN pip install flask psutil requests --no-cache-dir
COPY app.py .
ENV FLASK_ENV=production
EXPOSE 5680
CMD ["python", "-u", "app.py"]
