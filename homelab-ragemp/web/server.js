const express = require('express');
const path = require('path');
const Docker = require('dockerode');
const downloader = require('./downloader');

const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

const docker = new Docker({ socketPath: '/var/run/docker.sock' });
const CONTAINER_NAME = process.env.DOCKER_CONTAINER_NAME || 'homelab-ragemp_game_1';

// Официальные файлы сервера RAGE:MP пользователь скачивает вручную с rage.mp
// (после принятия условий) и вставляет сюда прямую ссылку на полученный архив.
const ENTRY_CANDIDATES = ['ragemp-server', 'ragemp-server.exe'];

function getContainer() { return docker.getContainer(CONTAINER_NAME); }

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
    const { slug } = await downloader.downloadAndExtract(url, name || ('ragemp-' + Date.now()), ENTRY_CANDIDATES);
    const servers = downloader.listServers(ENTRY_CANDIDATES);
    if (servers.length === 1) {
      downloader.setActive(slug);
      try { await getContainer().restart({ t: 10 }); } catch (e) { try { await getContainer().start(); } catch (e2) {} }
    }
  } catch (e) {
    console.error('Ошибка скачивания RAGE:MP сервера:', e.message);
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

// Держим одно постоянное подключение stdin к контейнеру, чтобы реально
// передавать команды в процесс ragemp-server, как будто их ввели в его консоли.
let stdinStream = null;
async function getStdinStream() {
  if (stdinStream && !stdinStream.destroyed) return stdinStream;
  const container = getContainer();
  stdinStream = await container.attach({ stream: true, stdin: true, stdout: false, stderr: false, hijack: true });
  stdinStream.on('error', () => { stdinStream = null; });
  stdinStream.on('close', () => { stdinStream = null; });
  return stdinStream;
}

app.get('/api/status', async (req, res) => {
  const out = { running: false, container: null, error: null, filesPresent: null };
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
  res.json(out);
});

app.get('/api/logs', async (req, res) => {
  try {
    const container = getContainer();
    const buf = await container.logs({ stdout: true, stderr: true, tail: 300, timestamps: false });
    res.type('text/plain').send(buf.toString('utf8'));
  } catch (e) {
    res.status(500).type('text/plain').send('Ошибка получения логов: ' + e.message);
  }
});

app.post('/api/console', async (req, res) => {
  const cmd = (req.body && req.body.command || '').trim();
  if (!cmd) return res.status(400).json({ error: 'Пустая команда' });
  try {
    const stream = await getStdinStream();
    stream.write(cmd + '\n');
    res.json({ ok: true, note: 'Команда отправлена в STDIN процесса. Ответ смотрите в консоли ниже (обновите логи).' });
  } catch (e) {
    res.status(500).json({ ok: false, error: e.message });
  }
});

app.post('/api/power', async (req, res) => {
  const action = req.body && req.body.action;
  try {
    const container = getContainer();
    if (action === 'start') await container.start();
    else if (action === 'stop') await container.stop({ t: 20 });
    else if (action === 'restart') await container.restart({ t: 20 });
    else return res.status(400).json({ error: 'Неизвестное действие' });
    stdinStream = null;
    res.json({ ok: true });
  } catch (e) {
    res.status(500).json({ ok: false, error: e.message });
  }
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log('RAGE:MP panel listening on ' + PORT));
