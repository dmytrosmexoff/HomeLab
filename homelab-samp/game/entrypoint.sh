#!/bin/bash
set -e

export RCON_PASSWORD="${RCON_PASSWORD:-changeme123}"
export MAX_PLAYERS="${MAX_PLAYERS:-100}"
export HOSTNAME_="${HOSTNAME_:-HomeLab SA-MP Server}"
export GAMEMODE="${GAMEMODE:-rivershell}"
export GAMEMODE_TEXT="${GAMEMODE_TEXT:-HomeLab RP}"
export ANNOUNCE="${ANNOUNCE:-0}"
export WEBURL="${WEBURL:-}"

mkdir -p /server/data
cd /server

# Подставляем переменные окружения в server.cfg при каждом старте,
# чтобы пароль RCON и настройки задавались из docker-compose/Umbrel UI.
envsubst < /server/server.cfg.template > /server/server.cfg

# Если в volume лежат пользовательские gamemodes/filterscripts/scriptfiles —
# они уже на месте благодаря монтированию ${APP_DATA_DIR}/data в /server/data,
# здесь линкуем их поверх дефолтных, если присутствуют.
for d in gamemodes filterscripts scriptfiles; do
  if [ -d "/server/data/$d" ] && [ "$(ls -A /server/data/$d 2>/dev/null)" ]; then
    rm -rf "/server/$d"
    ln -s "/server/data/$d" "/server/$d"
  fi
done

echo "[entrypoint] Starting samp03svr..."
exec ./samp03svr
