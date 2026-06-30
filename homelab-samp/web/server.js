const express = require('express');
const path = require('path');
const Docker = require('dockerode');
const samp = require('./samp-query');

const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

const docker = new Docker({ socketPath: '/var/run/docker.sock' });
const CONTAINER_NAME = process.env.DOCKER_CONTAINER_NAME || 'homelab-samp_game_1';
const SAMP_HOST = process.env.SAMP_HOST || 'homelab-samp_game_1';
const SAMP_PORT = parseInt(process.env.SAMP_PORT || '7777', 10);
const RCON_PASSWORD = process.env.SAMP_RCON_PASSWORD || 'changeme123';

function getContainer() { return docker.getContainer(CONTAINER_NAME); }

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
