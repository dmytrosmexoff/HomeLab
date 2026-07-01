# SA-MP Console — приложение для Umbrel

## Установка в твой App Store

1. Скопируй папку `samp-console/` в свой репозиторий `HomeLab` рядом с другими приложениями.
2. Подключи стор на Umbrel (если ещё не подключён):
   ```
   sudo umbreld client apps.store.add --url https://github.com/dmytrosmexoff/HomeLab
   ```
3. Установи приложение через UI Umbrel (App Store → SA-MP Console → Install),
   либо через SSH:
   ```
   sudo umbreld client apps.install --appId samp-console
   ```

## Перед первым запуском — положи файлы сервера

После установки Umbrel создаст папку данных приложения, обычно:
```
/home/umbrel/umbrel/app-data/samp-console/server/
```

Скопируй туда СВОИ файлы SA-MP сервера (`samp03svr`, `gamemode/`, `server.cfg`,
`filterscripts/` и т.д.):
```
sudo cp -r /путь/к/твоим/файлам/* /home/umbrel/umbrel/app-data/samp-console/server/
sudo chmod +x /home/umbrel/umbrel/app-data/samp-console/server/samp03svr
```

**Важно:** в `server.cfg` обязательно должны быть строки:
```
rcon 1
rcon_password твой_пароль
```
Панель читает пароль прямо из этого файла — вводить его отдельно не нужно.

## Порт

Веб-панель доступна на `http://<IP-Umbrel>:3010`.
Игровой порт сервера (по умолчанию `7777`) пробрасывается напрямую.

## Управление контейнерами вручную (если нужно)

```
sudo docker restart samp-console_samp-server_1
sudo docker logs -f samp-console_samp-server_1
```

## Структура

```
samp-console/
├── umbrel-app.yml       # манифест для App Store
├── docker-compose.yml   # samp-server + web-panel
├── data/server/         # сюда кладутся твои файлы сервера (локально для теста)
├── README.md
└── web/
    ├── Dockerfile
    ├── package.json
    ├── server.js         # API: старт/стоп/рестарт/RCON
    ├── rcon.js            # UDP RCON протокол SA-MP
    └── public/
        └── index.html    # твой дизайн + реальные данные
```
