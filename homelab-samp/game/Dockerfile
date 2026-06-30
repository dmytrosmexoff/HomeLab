# Универсальный рантайм для SA-MP / open.mp серверов (32-бит).
# Сам бинарник сервера НЕ встраивается в образ — он скачивается и выбирается
# пользователем через веб-панель (вкладка «Менеджер серверов») и хранится
# в volume ${APP_DATA_DIR}/data, который монтируется в /server/data.
FROM debian:bookworm-slim

RUN dpkg --add-architecture i386 && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates gettext-base \
        libc6:i386 libstdc++6:i386 libgcc-s1:i386 zlib1g:i386 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /server
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 7777/udp
ENTRYPOINT ["/entrypoint.sh"]
