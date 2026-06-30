#!/bin/bash
set -e

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
  echo "[entrypoint] Сервер RAGE:MP ещё не выбран в веб-панели (Менеджер серверов -> скачать архив с rage.mp и выбрать). Жду..."
  sleep 5
done

echo "[entrypoint] Запускаю сервер: $NAME"
rm -rf "$RUN_DIR"
ln -s "$SERVERS_DIR/$NAME" "$RUN_DIR"
cd "$RUN_DIR"

if [ ! -f "./ragemp-server" ]; then
  echo "[entrypoint] Не найден ./ragemp-server в $SERVERS_DIR/$NAME"
  sleep infinity
fi
chmod +x ./ragemp-server
echo "[entrypoint] exec ./ragemp-server"
exec ./ragemp-server
