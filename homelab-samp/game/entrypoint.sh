#!/bin/bash
set -e

export RCON_PASSWORD="${RCON_PASSWORD:-changeme123}"
ACTIVE_FILE="/server/data/active.json"
SERVERS_DIR="/server/data/servers"
RUN_DIR="/server/run"

echo "[entrypoint] Ожидание выбранного сервера..."
while true; do
  if [ -f "$ACTIVE_FILE" ]; then
    NAME=$(grep -o '"name"[[:space:]]*:[[:space:]]*"[^"]*"' "$ACTIVE_FILE" | sed -E 's/.*"name"[[:space:]]*:[[:space:]]*"([^"]*)"/\1/')
    if [ -n "$NAME" ] && [ -d "$SERVERS_DIR/$NAME" ]; then
      break
    fi
  fi
  echo "[entrypoint] Сервер ещё не выбран в веб-панели (Менеджер серверов -> скачать/выбрать). Жду..."
  sleep 5
done

echo "[entrypoint] Запускаю сервер: $NAME"
rm -rf "$RUN_DIR"
ln -s "$SERVERS_DIR/$NAME" "$RUN_DIR"
cd "$RUN_DIR"

# Подставляем актуальный rcon_password в server.cfg пакета, если он есть
if [ -f "server.cfg" ]; then
  if grep -q '^rcon_password ' server.cfg; then
    sed -i "s/^rcon_password .*/rcon_password ${RCON_PASSWORD}/" server.cfg
  else
    echo "rcon_password ${RCON_PASSWORD}" >> server.cfg
  fi
fi

BIN=$(ls samp03svr omp-server 2>/dev/null | head -n1)
if [ -z "$BIN" ]; then
  echo "[entrypoint] Не найден исполняемый файл сервера в $SERVERS_DIR/$NAME"
  sleep infinity
fi
chmod +x "./$BIN"
echo "[entrypoint] exec ./$BIN"
exec "./$BIN"
