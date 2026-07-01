'use strict';
const express = require('express');
const multer = require('multer');
const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');
const { WebSocketServer } = require('ws');
const http = require('http');

const query = require('./samp/query');
const rcon = require('./samp/rcon');

const DATA_DIR = process.env.DATA_DIR || '/data';
const GAME_PORT = parseInt(process.env.GAME_PORT || '7777', 10);
const API_PORT = parseInt(process.env.PORT || '3000', 10);

const GAMEMODES_DIR = path.join(DATA_DIR, 'gamemodes');
const FILTERSCRIPTS_DIR = path.join(DATA_DIR, 'filterscripts');
const CFG_PATH = path.join(DATA_DIR, 'server.cfg');
const BINARY_PATH = path.join(DATA_DIR, 'samp03svr');

for (const dir of [GAMEMODES_DIR, FILTERSCRIPTS_DIR]) {
  fs.mkdirSync(dir, { recursive: true });
}

const app = express();
app.use(express.json());

// ---------- состояние процесса ----------
let child = null;
let childStartedAt = null;
const consoleBuffer = []; // последние строки консоли для новых WS-клиентов
const MAX_BUFFER = 300;
const wsClients = new Set();

function pushConsole(line) {
  consoleBuffer.push({ t: Date.now(), line });
  if (consoleBuffer.length > MAX_BUFFER) consoleBuffer.shift();
  for (const ws of wsClients) {
    if (ws.readyState === 1) ws.send(JSON.stringify({ type: 'line', t: Date.now(), line }));
  }
}

function isRunning() {
  return !!child && !child.killed;
}

// ---------- server.cfg ----------
function readConfig() {
  if (!fs.existsSync(CFG_PATH)) return null;
  const text = fs.readFileSync(CFG_PATH, 'utf8');
  const cfg = {};
  for (const raw of text.split('\n')) {
    const line = raw.trim();
    if (!line || line.startsWith('#')) continue;
    const idx = line.indexOf(' ');
    if (idx === -1) continue;
    cfg[line.slice(0, idx)] = line.slice(idx + 1).trim();
  }
  return cfg;
}

function writeConfig({ hostname, rcon_password, maxplayers, gamemode, announce }) {
  const lines = [
    'echo Executing Server Config...',
    'lanmode 0',
    `rcon_password ${rcon_password}`,
    `maxplayers ${maxplayers || 50}`,
    `port ${GAME_PORT}`,
    `hostname ${hostname || 'SA-MP Server'}`,
    `gamemode0 ${gamemode} 1`,
    'filterscripts ' + listFilterscriptNames().join(' '),
    `announce ${announce ? 1 : 0}`,
    'query 1',
    'weburl www.sa-mp.com',
    'onfoot_rate 40',
    'incar_rate 40',
    'weapon_rate 40',
    'stream_distance 300.0',
    'stream_rate 1000',
    'maxnpc 0',
    'logtimeformat [%H:%M:%S]',
    'rcon 1',
    '',
  ];
  fs.writeFileSync(CFG_PATH, lines.join('\n'), 'utf8');
}

function listGamemodeNames() {
  if (!fs.existsSync(GAMEMODES_DIR)) return [];
  return fs.readdirSync(GAMEMODES_DIR)
    .filter((f) => f.endsWith('.amx'))
    .map((f) => f.replace(/\.amx$/, ''));
}

function listFilterscriptNames() {
  if (!fs.existsSync(FILTERSCRIPTS_DIR)) return [];
  return fs.readdirSync(FILTERSCRIPTS_DIR)
    .filter((f) => f.endsWith('.amx'))
    .map((f) => f.replace(/\.amx$/, ''));
}

// ---------- загрузка файлов ----------
const upload = multer({ storage: multer.memoryStorage(), limits: { fileSize: 25 * 1024 * 1024 } });

app.post('/upload/gamemode', upload.single('file'), (req, res) => {
  if (!req.file || !req.file.originalname.endsWith('.amx')) {
    return res.status(400).json({ error: 'Нужен .amx файл gamemode' });
  }
  fs.writeFileSync(path.join(GAMEMODES_DIR, req.file.originalname), req.file.buffer);
  res.json({ ok: true, name: req.file.originalname.replace(/\.amx$/, '') });
});

app.post('/upload/filterscript', upload.single('file'), (req, res) => {
  if (!req.file || !req.file.originalname.endsWith('.amx')) {
    return res.status(400).json({ error: 'Нужен .amx файл filterscript' });
  }
  fs.writeFileSync(path.join(FILTERSCRIPTS_DIR, req.file.originalname), req.file.buffer);
  res.json({ ok: true, name: req.file.originalname.replace(/\.amx$/, '') });
});

app.get('/files', (req, res) => {
  res.json({ gamemodes: listGamemodeNames(), filterscripts: listFilterscriptNames() });
});

// ---------- конфигурация ----------
app.post('/config', (req, res) => {
  const { hostname, rcon_password, maxplayers, gamemode, announce } = req.body || {};
  if (!gamemode) return res.status(400).json({ error: 'Не указан gamemode' });
  if (!listGamemodeNames().includes(gamemode)) {
    return res.status(400).json({ error: 'Такой gamemode не загружен' });
  }
  if (!rcon_password || rcon_password.length < 4) {
    return res.status(400).json({ error: 'rcon_password должен быть не короче 4 символов' });
  }
  writeConfig({ hostname, rcon_password, maxplayers, gamemode, announce });
  res.json({ ok: true });
});

// ---------- управление процессом ----------
app.get('/state', (req, res) => {
  const cfg = readConfig();
  res.json({
    running: isRunning(),
    hasGamemode: listGamemodeNames().length > 0,
    configured: !!cfg,
    config: cfg,
    startedAt: childStartedAt,
  });
});

app.post('/start', (req, res) => {
  if (isRunning()) return res.status(409).json({ error: 'Сервер уже запущен' });
  if (!fs.existsSync(BINARY_PATH)) return res.status(500).json({ error: 'Бинарник samp03svr не найден в /data' });
  if (!fs.existsSync(CFG_PATH)) return res.status(400).json({ error: 'Сначала настройте server.cfg (/config)' });

  child = spawn(BINARY_PATH, [], { cwd: DATA_DIR, stdio: ['pipe', 'pipe', 'pipe'] });
  childStartedAt = Date.now();
  pushConsole('--- Сервер запускается ---');

  child.stdout.on('data', (buf) => {
    buf.toString('utf8').split('\n').forEach((l) => { if (l.trim()) pushConsole(l); });
  });
  child.stderr.on('data', (buf) => {
    buf.toString('utf8').split('\n').forEach((l) => { if (l.trim()) pushConsole('[stderr] ' + l); });
  });
  child.on('exit', (code) => {
    pushConsole(`--- Процесс завершился (код ${code}) ---`);
    child = null;
    childStartedAt = null;
  });

  res.json({ ok: true });
});

app.post('/stop', (req, res) => {
  if (!isRunning()) return res.status(409).json({ error: 'Сервер не запущен' });
  child.stdin.write('exit\n');
  setTimeout(() => { if (isRunning()) child.kill('SIGTERM'); }, 4000);
  res.json({ ok: true });
});

app.post('/restart', async (req, res) => {
  if (isRunning()) {
    child.stdin.write('exit\n');
    await new Promise((r) => setTimeout(r, 3000));
    if (isRunning()) child.kill('SIGTERM');
  }
  res.json({ ok: true, note: 'Останов отправлен, запустите /start снова через пару секунд' });
});

// команда в консоль запущенного сервера (полные права, как локальный админ)
app.post('/console/command', (req, res) => {
  const { command } = req.body || {};
  if (!command) return res.status(400).json({ error: 'Пустая команда' });
  if (!isRunning()) return res.status(409).json({ error: 'Сервер не запущен' });
  pushConsole('> ' + command);
  child.stdin.write(command + '\n');
  res.json({ ok: true });
});

// резервный канал — внешний RCON по UDP (на случай управления с другого хоста)
app.post('/rcon', async (req, res) => {
  const { command } = req.body || {};
  const cfg = readConfig();
  if (!cfg || !cfg.rcon_password) return res.status(400).json({ error: 'RCON не настроен' });
  try {
    const lines = await rcon.sendRcon('127.0.0.1', GAME_PORT, cfg.rcon_password, command);
    res.json({ ok: true, lines });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// ---------- реальные игровые данные ----------
app.get('/info', async (req, res) => {
  try {
    const info = await query.getInfo('127.0.0.1', GAME_PORT);
    res.json(info);
  } catch (e) {
    res.status(503).json({ error: e.message });
  }
});

app.get('/players', async (req, res) => {
  try {
    const players = await query.getPlayers('127.0.0.1', GAME_PORT);
    res.json(players);
  } catch (e) {
    res.status(503).json({ error: e.message });
  }
});

// ---------- реальные метрики процесса ----------
let lastCpu = null;
function readProcStat(pid) {
  const stat = fs.readFileSync(`/proc/${pid}/stat`, 'utf8').split(') ').pop().trim().split(' ');
  const utime = parseInt(stat[11], 10);
  const stime = parseInt(stat[12], 10);
  const status = fs.readFileSync(`/proc/${pid}/status`, 'utf8');
  const rssMatch = status.match(/VmRSS:\s+(\d+) kB/);
  const rssKb = rssMatch ? parseInt(rssMatch[1], 10) : 0;
  return { totalTicks: utime + stime, rssKb, now: Date.now() };
}

app.get('/stats', (req, res) => {
  if (!isRunning()) return res.json({ running: false });
  try {
    const clockTicks = 100; // стандартное значение USER_HZ на Linux
    const cur = readProcStat(child.pid);
    let cpuPercent = 0;
    if (lastCpu && lastCpu.pid === child.pid) {
      const dTicks = cur.totalTicks - lastCpu.totalTicks;
      const dMs = cur.now - lastCpu.now;
      cpuPercent = dMs > 0 ? Math.max(0, (dTicks / clockTicks) / (dMs / 1000) * 100) : 0;
    }
    lastCpu = { pid: child.pid, ...cur };
    res.json({
      running: true,
      pid: child.pid,
      cpuPercent: Math.round(cpuPercent * 10) / 10,
      ramMb: Math.round(cur.rssKb / 1024),
      uptimeSeconds: Math.floor((Date.now() - childStartedAt) / 1000),
    });
  } catch (e) {
    res.json({ running: isRunning(), error: e.message });
  }
});

app.get('/health', (req, res) => res.json({ ok: true }));

// ---------- WebSocket консоль ----------
const server = http.createServer(app);
const wss = new WebSocketServer({ server, path: '/ws/console' });

wss.on('connection', (ws) => {
  wsClients.add(ws);
  ws.send(JSON.stringify({ type: 'backlog', lines: consoleBuffer }));
  ws.on('message', (msg) => {
    try {
      const data = JSON.parse(msg.toString());
      if (data.type === 'command' && data.command && isRunning()) {
        pushConsole('> ' + data.command);
        child.stdin.write(data.command + '\n');
      }
    } catch (_) { /* ignore malformed */ }
  });
  ws.on('close', () => wsClients.delete(ws));
});

server.listen(API_PORT, () => console.log('SA-MP API слушает порт ' + API_PORT));
