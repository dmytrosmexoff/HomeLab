FROM python:3.11-slim

# Объявляем переменную для отслеживания архитектуры (автоматически передается buildx)
ARG TARGETARCH

WORKDIR /app

# Установка системных зависимостей
RUN if [ "$TARGETARCH" = "amd64" ]; then \
        dpkg --add-architecture i386 && \
        apt-get update && \
        apt-get install -y --no-install-recommends \
            procps; \
    else \
        # Для arm64 (ставим только то, что доступно)
        apt-get update && \
        apt-get install -y --no-install-recommends \
            procps; \
    fi && \
    rm -rf /var/lib/apt/lists/*

# Установка Python-пакетов
RUN pip install --no-cache-dir flask

# Копирование исходного кода
COPY app.py .

# Создание необходимых директорий
RUN mkdir -p /data /server

EXPOSE 5750

CMD ["python", "app.py"]
