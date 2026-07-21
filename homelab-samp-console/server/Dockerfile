# SA-MP сервер требует 32-битный (i386) рантайм — сам бинарник samp03svr собран под x86 32-бит.
# Поэтому этот образ собирается ТОЛЬКО под linux/amd64 (см. workflow) — на ARM (Raspberry Pi и т.д.)
# 32-битная эмуляция x86 через QEMU для игрового сервера практически бесполезна по производительности.
FROM debian:bullseye-slim

# Библиотеки ставим на этапе СБОРКИ образа, а не при каждом запуске контейнера —
# так контейнер стартует мгновенно и не зависит от доступности apt-репозиториев в рантайме.
RUN dpkg --add-architecture i386 \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        libc6:i386 \
        libstdc++6:i386 \
        libgcc-s1:i386 \
        zlib1g:i386 \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /server

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Сам бинарник samp03svr и server.cfg сюда монтируются volume-мом из ${APP_DATA_DIR}/server —
# в образ они не входят (распространяются отдельно, см. README проекта).
ENTRYPOINT ["/entrypoint.sh"]
