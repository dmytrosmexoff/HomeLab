// Глобальные переменные
let statusInterval = null;
let currentPlayers = 0;

// Элементы
const statusDot = document.getElementById('statusDot');
const statusText = document.getElementById('statusText');
const statPlayers = document.getElementById('statPlayers');
const statPlayersSub = document.getElementById('statPlayersSub');
const statCpu = document.getElementById('statCpu');
const statRam = document.getElementById('statRam');
const statUptime = document.getElementById('statUptime');
const playersCount = document.getElementById('playersCount');
const playersList = document.getElementById('playersList');
const consoleBox = document.getElementById('consoleBox');
const cpuBar = document.getElementById('cpuBar');
const ramBar = document.getElementById('ramBar');
const chartHourly = document.getElementById('chartHourly');
const chartDaily = document.getElementById('chartDaily');
const chartNow = document.getElementById('chartNow');
const chartNowDaily = document.getElementById('chartNowDaily');
const cfgEditor = document.getElementById('cfgEditor');
const saveCfgBtn = document.getElementById('saveCfgBtn');
const cfgSaveMsg = document.getElementById('cfgSaveMsg');

// Загрузка конфига при старте
fetch('/api/config')
  .then(res => res.json())
  .then(data => {
    cfgEditor.value = data.content || '';
  });

saveCfgBtn.addEventListener('click', () => {
  const content = cfgEditor.value;
  fetch('/api/config', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({content})
  })
  .then(res => res.json())
  .then(data => {
    if (data.success) {
      cfgSaveMsg.textContent = '✅ Сохранено!';
      setTimeout(() => cfgSaveMsg.textContent = '', 3000);
    } else {
      cfgSaveMsg.textContent = '❌ Ошибка сохранения';
    }
  });
});

// Управление сервером
document.getElementById('btnStart').addEventListener('click', () => {
  fetch('/api/control', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({action:'start'})})
    .then(res => res.json())
    .then(data => {
      if(data.success) logLine('info', 'Сервер запущен');
      else logLine('warn', 'Не удалось запустить сервер');
    });
});
document.getElementById('btnStop').addEventListener('click', () => {
  fetch('/api/control', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({action:'stop'})})
    .then(res => res.json())
    .then(data => {
      if(data.success) logLine('warn', 'Сервер остановлен');
      else logLine('warn', 'Не удалось остановить сервер');
    });
});
document.getElementById('btnRestart').addEventListener('click', () => {
  fetch('/api/control', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({action:'restart'})})
    .then(res => res.json())
    .then(data => {
      if(data.success) logLine('warn', 'Сервер перезапускается...');
      else logLine('warn', 'Ошибка перезапуска');
    });
});

// Отправка RCON команды
function sendCmd() {
  const input = document.getElementById('cmdInput');
  const cmd = input.value.trim();
  if (!cmd) return;
  logLine('info', '> ' + cmd);
  fetch('/api/rcon', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({cmd})
  })
  .then(res => res.json())
  .then(data => {
    if (data.success) {
      if (data.response) logLine('info', data.response);
      else logLine('info', 'Команда выполнена (нет ответа)');
    } else {
      logLine('warn', 'Ошибка RCON: ' + data.error);
    }
  });
  input.value = '';
}

// Добавление строки в консоль
function logLine(type, msg) {
  const time = new Date().toLocaleTimeString('ru-RU');
  const div = document.createElement('div');
  div.className = 'ln ' + type;
  div.innerHTML = `<span class="t">[${time}]</span> ${msg}`;
  consoleBox.appendChild(div);
  consoleBox.scrollTop = consoleBox.scrollHeight;
  while (consoleBox.children.length > 120) consoleBox.removeChild(consoleBox.firstChild);
}

// Рендер игроков
function renderPlayers(players) {
  playersList.innerHTML = '';
  if (!players || players.length === 0) {
    playersList.innerHTML = '<div style="padding:12px;color:var(--muted);text-align:center;">Нет игроков</div>';
    return;
  }
  players.forEach(p => {
    const pingClass = p.ping < 60 ? 'good' : (p.ping < 130 ? 'med' : 'bad');
    const row = document.createElement('div');
    row.className = 'player-row';
    row.innerHTML = `
      <div class="p-left">
        <div class="p-id">${p.id}</div>
        <div>
          <div class="p-name">${p.name}</div>
          <div class="p-ping ${pingClass}">${p.ping} ms</div>
        </div>
      </div>
      <button class="kick" onclick="kickPlayer(${p.id}, '${p.name}')">Кикнуть</button>
    `;
    playersList.appendChild(row);
  });
}

// Кик игрока (через RCON)
function kickPlayer(id, name) {
  if (!confirm(`Кикнуть игрока ${name} (ID ${id})?`)) return;
  fetch('/api/rcon', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({cmd: `kick ${id}`})
  })
  .then(res => res.json())
  .then(data => {
    if (data.success) {
      logLine('leave', `${name} был кикнут.`);
    } else {
      logLine('warn', 'Ошибка кика: ' + data.error);
    }
  });
}

// Рисование графика
function drawChart(canvas, data, label) {
  const ctx = canvas.getContext('2d');
  const w = canvas.clientWidth, h = canvas.clientHeight;
  canvas.width = w; canvas.height = h;
  ctx.clearRect(0,0,w,h);
  if (!data || data.length < 2) {
    ctx.fillStyle = '#6c727f';
    ctx.font = '14px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('Нет данных', w/2, h/2);
    return;
  }
  const max = Math.max(...data.map(d => d.count)) + 5;
  const step = w / (data.length - 1);

  // Градиент заливки
  const grad = ctx.createLinearGradient(0,0,0,h);
  grad.addColorStop(0,'rgba(61,107,255,0.35)');
  grad.addColorStop(1,'rgba(180,61,255,0.0)');
  ctx.beginPath();
  data.forEach((d,i) => {
    const x = i*step, y = h - (d.count/max)*h;
    if (i===0) ctx.moveTo(x,y);
    else ctx.lineTo(x,y);
  });
  ctx.lineTo(w,h); ctx.lineTo(0,h); ctx.closePath();
  ctx.fillStyle = grad; ctx.fill();

  // Линия
  ctx.beginPath();
  data.forEach((d,i) => {
    const x = i*step, y = h - (d.count/max)*h;
    if (i===0) ctx.moveTo(x,y);
    else ctx.lineTo(x,y);
  });
  const lg = ctx.createLinearGradient(0,0,w,0);
  lg.addColorStop(0,'#3D6BFF'); lg.addColorStop(1,'#B43DFF');
  ctx.strokeStyle = lg; ctx.lineWidth=2.5; ctx.stroke();

  // Текущее значение
  const last = data[data.length-1];
  if (label) {
    label.textContent = `сейчас: ${last.count}`;
  }
}

// Основной цикл обновления
function updateStatus() {
  fetch('/api/status')
    .then(res => res.json())
    .then(data => {
      // Статус онлайн
      const online = data.online;
      statusDot.classList.toggle('off', !online);
      statusText.textContent = online ? 'Онлайн' : 'Офлайн';

      // Игроки
      currentPlayers = data.count || 0;
      const maxSlots = data.max_players || 150;
      statPlayers.textContent = `${currentPlayers}/${maxSlots}`;
      playersCount.textContent = `${currentPlayers} / ${maxSlots}`;
      statPlayersSub.textContent = `Пик сегодня: ${data.peak_today || '--'}`;

      // CPU/RAM
      const cpu = data.cpu || 0;
      const ram = data.ram || 0;
      statCpu.textContent = cpu + '%';
      statRam.textContent = ram.toFixed(1) + ' GB';
      cpuBar.style.width = Math.min(cpu, 100) + '%';
      ramBar.style.width = Math.min((ram / 4) * 100, 100) + '%'; // 4 GB выделено

      // Uptime
      const sec = data.uptime_seconds || 0;
      const days = Math.floor(sec / 86400);
      const hours = Math.floor((sec % 86400) / 3600);
      statUptime.textContent = (days > 0 ? days + 'д ' : '') + hours + 'ч';

      // Информация о сервере
      document.getElementById('infoGamemode').textContent = data.server_info?.gamemode || '--';
      document.getElementById('infoSlots').textContent = data.server_info?.slots || '--';
      // Сетевые данные - заглушка
      document.getElementById('infoNet').textContent = '--';
      document.getElementById('infoPps').textContent = '--';

      // Игроки
      renderPlayers(data.players || []);

      // Логи: подгружаем последние строки (каждые 10 обновлений)
      if (Math.random() < 0.3) {
        fetch('/api/logs')
          .then(res => res.json())
          .then(logData => {
            // Можно обновлять консоль, но проще добавлять новые строки
            // Для простоты просто заменим все
            consoleBox.innerHTML = '';
            logData.lines.forEach(line => {
              const div = document.createElement('div');
              div.className = 'ln info';
              div.textContent = line;
              consoleBox.appendChild(div);
            });
            consoleBox.scrollTop = consoleBox.scrollHeight;
          });
      }
    });

  // Обновление графиков из истории
  fetch('/api/history')
    .then(res => res.json())
    .then(history => {
      const hourly = history.hourly || [];
      const daily = history.daily || [];
      drawChart(chartHourly, hourly, document.getElementById('chartNow'));
      drawChart(chartDaily, daily, document.getElementById('chartNowDaily'));
    });
}

// Запуск обновления
updateStatus();
statusInterval = setInterval(updateStatus, 3000);

// Перерисовка графиков при изменении размера окна
window.addEventListener('resize', () => {
  fetch('/api/history')
    .then(res => res.json())
    .then(history => {
      drawChart(chartHourly, history.hourly || [], document.getElementById('chartNow'));
      drawChart(chartDaily, history.daily || [], document.getElementById('chartNowDaily'));
    });
});