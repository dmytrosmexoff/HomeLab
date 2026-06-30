const express = require('express');
const path = require('path');
const Docker = require('dockerode');
const samp = require('./samp-query');
const downloader = require('./downloader');

const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

const docker = new Docker({ socketPath: '/var/run/docker.sock' });
const CONTAINER_NAME = process.env.DOCKER_CONTAINER_NAME || 'homelab-samp_game_1';
const SAMP_HOST = process.env.SAMP_HOST || 'homelab-samp_game_1';
const SAMP_PORT = parseInt(process.env.SAMP_PORT || '7777', 10);
const RCON_PASSWORD = process.env.SAMP_RCON_PASSWORD || 'changeme123';

// SA-MP сборки распространяются под разными именами бинарника в зависимости
// от форка/версии (оригинальный samp03svr, форки open.mp - omp-server и т.д.)
const ENTRY_CANDIDATES = ['samp03svr', 'samp03svr.exe', 'omp-server', 'omp-server.exe'];

function getContainer() { return docker.getContainer(CONTAINER_NAME); }

// ---- Менеджер серверов: скачать по ссылке / распаковать / выбрать активный ----
app.get('/api/servers', (req, res) => {
  res.json({ servers: downloader.listServers(ENTRY_CANDIDATES), progress: downloader.getProgress() });
});

app.get('/api/servers/progress', (req, res) => {
  res.json(downloader.getProgress());
});

app.post('/api/servers/download', async (req, res) => {
  const { url, name } = req.body || {};
  if (!url || !/^https?:\/\//i.test(url)) return res.status(400).json({ error: 'Укажите корректную прямую ссылку на .zip или .tar.gz' });
  res.json({ ok: true, started: true });
  try {
    const { slug } = await downloader.downloadAndExtract(url, name || ('samp-' + Date.now()), ENTRY_CANDIDATES);
    const servers = downloader.listServers(ENTRY_CANDIDATES);
    if (servers.length === 1) {
      // первый успешно скачанный сервер сразу делаем активным и стартуем
      downloader.setActive(slug);
      try { await getContainer().restart({ t: 10 }); } catch (e) { try { await getContainer().start(); } catch (e2) {} }
    }
  } catch (e) {
    console.error('Ошибка скачивания SA-MP сервера:', e.message);
  }
});

app.post('/api/servers/:name/activate', async (req, res) => {
  try {
    downloader.setActive(req.params.name);
    const container = getContainer();
    try { await container.restart({ t: 10 }); } catch (e) { await container.start(); }
    res.json({ ok: true });
  } catch (e) {
    res.status(500).json({ ok: false, error: e.message });
  }
});

app.delete('/api/servers/:name', (req, res) => {
  try {
    downloader.removeServer(req.params.name);
    res.json({ ok: true });
  } catch (e) {
    res.status(500).json({ ok: false, error: e.message });
  }
});

function calcCpuPercent(stats) {
  try {
    const cpuDelta = stats.cpu_stats.cpu_usage.total_usage - stats.precpu_stats.cpu_usage.total_usage;
    const sysDelta = stats.cpu_stats.system_cpu_usage - stats.precpu_stats.system_cpu_usage;
    const numCpus = stats.cpu_stats.online_cpus ||
      (stats.cpu_stats.cpu_usage.percpu_usage ? stats.cpu_stats.cpu_usage.percpu_usage.length : 1);
    if (sysDelta > 0 && cpuDelta >= 0) return (cpuDelta / sysDelta) * numCpus * 100;
  } catch (e) {}
  return 0;
}

app.get('/api/status', async (req, res) => {
  const out = { running: false, container: null, query: null, error: null };
  try {
    const container = getContainer();
    const inspect = await container.inspect();
    out.running = inspect.State.Running;
    out.container = { startedAt: inspect.State.StartedAt, status: inspect.State.Status };
    if (out.running) {
      const stats = await container.stats({ stream: false });
      out.container.cpuPercent = calcCpuPercent(stats);
      const memUsage = stats.memory_stats.usage - ((stats.memory_stats.stats && stats.memory_stats.stats.cache) || 0);
      out.container.memUsageMB = memUsage / 1024 / 1024;
      out.container.memLimitMB = stats.memory_stats.limit / 1024 / 1024;
    }
  } catch (e) {
    out.error = 'docker: ' + e.message;
  }

  if (out.running) {
    try {
      const info = await samp.getInfo(SAMP_HOST, SAMP_PORT);
      out.query = { info };
      try {
        out.query.players = await samp.getPlayers(SAMP_HOST, SAMP_PORT);
      } catch (e) {
        out.query.players = [];
      }
    } catch (e) {
      out.queryError = 'Сервер не отвечает на query (порт 7777/UDP): ' + e.message;
    }
  }

  res.json(out);
});

app.get('/api/logs', async (req, res) => {
  try {
    const container = getContainer();
    const buf = await container.logs({ stdout: true, stderr: true, tail: 200, timestamps: false });
    res.type('text/plain').send(buf.toString('utf8'));
  } catch (e) {
    res.status(500).type('text/plain').send('Ошибка получения логов: ' + e.message);
  }
});

app.post('/api/console', async (req, res) => {
  const cmd = (req.body && req.body.command || '').trim();
  if (!cmd) return res.status(400).json({ error: 'Пустая команда' });
  try {
    const lines = await samp.sendRcon(SAMP_HOST, SAMP_PORT, RCON_PASSWORD, cmd);
    res.json({ ok: true, output: lines.length ? lines.join('\n') : '(нет ответа — команда могла выполниться без вывода, либо неверный rcon-пароль)' });
  } catch (e) {
    res.status(500).json({ ok: false, error: e.message });
  }
});

app.post('/api/power', async (req, res) => {
  const action = req.body && req.body.action;
  try {
    const container = getContainer();
    if (action === 'start') await container.start();
    else if (action === 'stop') await container.stop({ t: 15 });
    else if (action === 'restart') await container.restart({ t: 15 });
    else return res.status(400).json({ error: 'Неизвестное действие' });
    res.json({ ok: true });
  } catch (e) {
    res.status(500).json({ ok: false, error: e.message });
  }
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log('SA-MP panel listening on ' + PORT));
