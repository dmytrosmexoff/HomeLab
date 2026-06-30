#!/bin/bash
set -e
cd /server/data

if [ ! -f "./ragemp-server" ]; then
  echo "============================================================"
  echo " Файлы сервера RAGE:MP не найдены в /server/data."
  echo " 1. Скачайте Linux-сборку сервера на https://rage.mp/ (раздел Download -> Server)"
  echo " 2. Распакуйте архив в папку данных приложения на Umbrel:"
  echo "    .../app-data/homelab-ragemp/data/server/"
  echo "    так, чтобы файл ragemp-server лежал прямо в этой папке"
  echo " 3. Перезапустите контейнер (кнопка Рестарт в панели)."
  echo "============================================================"
  # Не падаем в restart-loop, просто ждём, чтобы пользователь успел положить файлы
  # и перезапустить контейнер из панели управления.
  sleep infinity
fi

chmod +x ./ragemp-server
echo "[entrypoint] Запуск ./ragemp-server..."
exec ./ragemp-server
