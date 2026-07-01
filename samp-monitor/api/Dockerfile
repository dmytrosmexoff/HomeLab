FROM node:20-bookworm-slim

# --- системные зависимости (samp03svr — 32-битный бинарник, нужны i386-библиотеки) ---
RUN dpkg --add-architecture i386 && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        wget ca-certificates tar \
        libc6:i386 libstdc++6:i386 libgcc-s1:i386 zlib1g:i386 && \
    rm -rf /var/lib/apt/lists/*

# --- автоскачивание SA-MP server (Linux, 0.3.7 R2-2-1) ---
RUN mkdir -p /opt/samp-bin && \
    wget -O /tmp/samp.tar.gz \
      https://raw.githubusercontent.com/Se8870/SAMP-File-Archive/master/archives/samp037svr_R2-2-1.tar.gz && \
    tar -xzf /tmp/samp.tar.gz -C /opt/samp-bin && \
    rm /tmp/samp.tar.gz

WORKDIR /app

# --- npm зависимости ставятся автоматически при сборке образа ---
COPY package.json ./
RUN npm install --omit=dev

COPY . .
RUN chmod +x entrypoint.sh

ENV DATA_DIR=/data
ENV GAME_PORT=7777
ENV PORT=3000

VOLUME ["/data"]
EXPOSE 3000
EXPOSE 7777/tcp
EXPOSE 7777/udp

ENTRYPOINT ["./entrypoint.sh"]
