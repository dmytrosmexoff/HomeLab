#!/bin/bash
set -e

BIN="/server/samp03svr"

if [ ! -f "$BIN" ]; then
    echo "[samp-server] Файл $BIN не найден."
    echo "[samp-server] Скопируй файлы сервера (samp03svr, server.cfg, gamemodes/ и т.д.)"
    echo "[samp-server] в ~/umbrel/app-data/homelab-samp-console/server/ и перезапусти контейнер:"
    echo "[samp-server]   sudo docker restart homelab-samp-console_samp-server_1"
    echo "[samp-server] Подробности — в README.md приложения."
    exec sleep infinity
fi

chmod +x "$BIN"
cd /server
exec "$BIN"
