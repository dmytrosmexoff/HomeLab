# Этот образ НЕ скачивает сервер RAGE:MP — официальные файлы сервера раздаются
# только после принятия условий на rage.mp, автоматизировать это нельзя.
# Образ даёт только окружение для запуска уже скачанных вами файлов сервера
# (они монтируются через volume, см. docker-compose.yml).
FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl libcurl4 zlib1g libssl3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /server
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 22005/udp 22005/tcp
ENTRYPOINT ["/entrypoint.sh"]
