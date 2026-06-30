# Реальный сервер SA-MP (San Andreas Multiplayer).
# Бинарник 32-битный, официально распространяется SA-MP team.
FROM debian:bookworm-slim

ARG SAMP_VERSION=R2-2-1
ARG SAMP_URL=https://gta-multiplayer.cz/downloads/samp037svr_R2-2-1.tar.gz

RUN dpkg --add-architecture i386 && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        wget ca-certificates gettext-base \
        libc6:i386 libstdc++6:i386 libgcc-s1:i386 zlib1g:i386 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /server

# Если официальный URL поменяется/будет недоступен — сборка завершится с понятной
# ошибкой; в этом случае нужно скачать архив вручную и положить в ./vendor/samp.tar.gz
# рядом с этим Dockerfile, и заменить RUN ниже на: COPY vendor/samp.tar.gz /tmp/samp.tar.gz
RUN wget -q "${SAMP_URL}" -O /tmp/samp.tar.gz && \
    tar -xzf /tmp/samp.tar.gz -C /server && \
    rm /tmp/samp.tar.gz && \
    chmod +x /server/samp03svr

COPY server.cfg.template /server/server.cfg.template
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 7777/udp
ENTRYPOINT ["/entrypoint.sh"]
