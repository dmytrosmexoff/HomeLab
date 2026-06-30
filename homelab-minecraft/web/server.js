const express = require('express');
const path = require('path');
const Docker = require('dockerode');
const { Rcon } = require('rcon-client');

const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

const docker = new Docker({ socketPath: '/var/run/docker.sock' });
const CONTAINER_NAME = process.env.DOCKER_CONTAINER_NAME || 'homelab-minecraft_mc_1';
const RCON_HOST = process.env.MC_RCON_HOST || 'homelab-minecraft_mc_1';
const RCON_PORT = parseInt(process.env.MC_RCON_PORT || '25575', 10);
const RCON_PASSWORD = process.env.MC_RCON_PASSWORD || 'changeme123';

function getContainer() {
  return docker.getContainer(CONTAINER_NAME);
}

async function rconCommand(cmd, timeoutMs = 4000) {
  const rcon = await Promise.race([
    Rcon.connect({ host: RCON_HOST, port: RCON_PORT, password: RCON_PASSWORD }),
    new Promise((_, rej) => setTimeout(() => rej(new Error('RCON timeout')), timeoutMs)),
  ]);
  try {
    const res = await rcon.send(cmd);
    return res;
  } finally {
    rcon.end().catch(() => {});
  }
}

function calcCpuPercent(stats) {
  try {
    const cpuDelta = stats.cpu_stats.cpu_usage.total_usage - stats.precpu_stats.cpu_usage.total_usage;
    const sysDelta = stats.cpu_stats.system_cpu_usage - stats.precpu_stats.system_cpu_usage;
    const numCpus = stats.cpu_stats.online_cpus ||
      (stats.cpu_stats.cpu_usage.percpu_usage ? stats.cpu_stats.cpu_usage.percpu_usage.length : 1);
    if (sysDelta > 0 && cpuDelta >= 0) {
      return (cpuDelta / sysDelta) * numCpus * 100;
    }
  } catch (e) {}
  return 0;
}

function parsePlayers(listResponse) {
  // "There are 3 of a max of 100 players online: Steve, Alex, Bob"
  const m = listResponse.match(/There are (\d+) of a max(?: of)? (\d+) players online:?\s*(.*)/i);
  if (!m) return { online: 0, max: 0, names: [] };
  const names = m[3] ? m[3].split(',').map(s => s.trim()).filter(Boolean) : [];
  return { online: parseInt(m[1], 10), max: parseInt(m[2], 10), names };
}

function parseTps(tpsResponse) {
  // "TPS from last 1m, 5m, 15m: 20.0, 19.98, 19.9" (Paper/Spigot)
  const m = tpsResponse.match(/([\d.]+),\s*([\d.]+),\s*([\d.]+)/);
  if (!m) return null;
  return { tps1m: parseFloat(m[1]), tps5m: parseFloat(m[2]), tps15m: parseFloat(m[3]) };
}

app.get('/api/status', async (req, res) => {
  const out = { running: false, container: null, rcon: null, error: null };
  try {
    const container = getContainer();
    const inspect = await container.inspect();
    out.running = inspect.State.Running;
    out.container = {
      startedAt: inspect.State.StartedAt,
      status: inspect.State.Status,
    };
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
      const listRes = await rconCommand('list');
      out.rcon = { players: parsePlayers(listRes) };
      try {
        const tpsRes = await rconCommand('tps');
        out.rcon.tps = parseTps(tpsRes);
      } catch (e) { /* some forks/vanilla may not support tps */ }
    } catch (e) {
      out.rcon = null;
      out.rconError = 'Сервер ещё запускается или RCON недоступен: ' + e.message;
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
    const out = await rconCommand(cmd);
    res.json({ ok: true, output: out });
  } catch (e) {
    res.status(500).json({ ok: false, error: e.message });
  }
});

app.post('/api/power', async (req, res) => {
  const action = req.body && req.body.action;
  try {
    const container = getContainer();
    if (action === 'start') await container.start();
    else if (action === 'stop') {
      // graceful: tell server to save & stop via RCON if possible, then docker stop as fallback
      try { await rconCommand('stop'); } catch (e) {}
      await container.stop({ t: 60 });
    } else if (action === 'restart') {
      try { await rconCommand('stop'); } catch (e) {}
      await container.restart({ t: 60 });
    } else {
      return res.status(400).json({ error: 'Неизвестное действие' });
    }
    res.json({ ok: true });
  } catch (e) {
    res.status(500).json({ ok: false, error: e.message });
  }
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log('Minecraft panel listening on ' + PORT));
