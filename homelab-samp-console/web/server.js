const express = require('express');
const { exec } = require('child_process');
const fs = require('fs');
const path = require('path');
const { sendRcon } = require('./rcon');

const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

const TARGET = process.env.DOCKER_TARGET || 'samp-console_samp-server_1';
const RCON_HOST = process.env.RCON_HOST || 'samp-console_samp-server_1';
const RCON_PORT = parseInt(process.env.RCON_PORT || '7777', 10);

function readRconPassword() {
  try {
    const cfg = fs.readFileSync('/serverdata/server.cfg', 'utf8');
    const m = cfg.match(/rcon_password\s+(\S+)/);
    return m ? m[1] : '';
  } catch (e) {
    return '';
  }
}

app.post('/api/start', (req, res) => {
  exec(`docker start ${TARGET}`, (err, stdout, stderr) => {
    if (err) return res.status(500).json({ error: stderr });
    res.json({ ok: true });
  });
});

app.post('/api/stop', (req, res) => {
  exec(`docker stop ${TARGET}`, (err, stdout, stderr) => {
    if (err) return res.status(500).json({ error: stderr });
    res.json({ ok: true });
  });
});

app.post('/api/restart', (req, res) => {
  exec(`docker restart ${TARGET}`, (err, stdout, stderr) => {
    if (err) return res.status(500).json({ error: stderr });
    res.json({ ok: true });
  });
});

app.get('/api/status', (req, res) => {
  exec(`docker inspect -f "{{.State.Running}}" ${TARGET}`, (err, stdout) => {
    const running = stdout.trim() === 'true';
    exec(`docker stats ${TARGET} --no-stream --format "{{.CPUPerc}};{{.MemUsage}}"`, (err2, stdout2) => {
      let cpu = '0%', mem = '0MB / 0MB';
      if (!err2 && stdout2) {
        const [c, m] = stdout2.trim().split(';');
        cpu = c || cpu;
        mem = m || mem;
      }
      res.json({ running, cpu, mem });
    });
  });
});

app.get('/api/players', async (req, res) => {
  try {
    const pass = readRconPassword();
    const text = await sendRcon(RCON_HOST, RCON_PORT, pass, 'players');
    res.json({ raw: text });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.post('/api/rcon', async (req, res) => {
  const { command } = req.body;
  if (!command) return res.status(400).json({ error: 'command required' });
  try {
    const pass = readRconPassword();
    const text = await sendRcon(RCON_HOST, RCON_PORT, pass, command);
    res.json({ response: text || 'Команда отправлена, ответа нет.' });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.listen(3000, () => console.log('SA-MP Console web-panel listening on 3000'));
