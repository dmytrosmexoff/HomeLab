#!/bin/sh
set -e

DATA_DIR="${DATA_DIR:-/data}"

if [ ! -f "$DATA_DIR/samp03svr" ]; then
  echo "[entrypoint] Первый запуск: копирую файлы SA-MP сервера в $DATA_DIR ..."
  cp -r /opt/samp-bin/. "$DATA_DIR"/
  chmod +x "$DATA_DIR/samp03svr"
  [ -f "$DATA_DIR/samp-npc" ] && chmod +x "$DATA_DIR/samp-npc"
  [ -f "$DATA_DIR/announce" ] && chmod +x "$DATA_DIR/announce"
  echo "[entrypoint] Готово."
fi

exec node server.js
