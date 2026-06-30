// Скачивает архив сервера по прямой ссылке (.zip / .tar.gz / .tgz),
// распаковывает в /data/servers/<slug>/ и определяет бинарник запуска.
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { pipeline } = require('stream/promises');
const tar = require('tar');
const extractZip = require('extract-zip');

const SERVERS_DIR = process.env.SERVERS_DIR || '/data/servers';
const ACTIVE_FILE = process.env.ACTIVE_FILE || '/data/active.json';

function slugify(name) {
  return name.toLowerCase().replace(/[^a-z0-9а-я_-]+/gi, '-').replace(/^-+|-+$/g, '').slice(0, 40) || 'server';
}

// прогресс отдаём через простой in-memory объект, опрашивается фронтендом
const progress = { state: 'idle', percent: 0, message: '', error: null, serverName: null };

function getProgress() { return progress; }

async function flattenSingleDir(dir) {
  // если в архиве всё лежит в одной общей папке — поднимаем содержимое на уровень выше
  let entries = fs.readdirSync(dir, { withFileTypes: true });
  while (entries.length === 1 && entries[0].isDirectory()) {
    const inner = path.join(dir, entries[0].name);
    for (const f of fs.readdirSync(inner)) {
      fs.renameSync(path.join(inner, f), path.join(dir, f));
    }
    fs.rmdirSync(inner);
    entries = fs.readdirSync(dir, { withFileTypes: true });
  }
}

function findEntry(dir, candidates, depth = 0, maxDepth = 3) {
  if (depth > maxDepth) return null;
  let entries;
  try { entries = fs.readdirSync(dir, { withFileTypes: true }); } catch (e) { return null; }
  for (const e of entries) {
    if (!e.isDirectory() && candidates.some(c => e.name.toLowerCase() === c.toLowerCase())) {
      return path.relative(SERVERS_DIR, path.join(dir, e.name));
    }
  }
  for (const e of entries) {
    if (e.isDirectory()) {
      const found = findEntry(path.join(dir, e.name), candidates, depth + 1, maxDepth);
      if (found) return found;
    }
  }
  return null;
}

async function downloadAndExtract(url, displayName, entryCandidates) {
  if (progress.state === 'downloading' || progress.state === 'extracting') {
    throw new Error('Уже идёт загрузка другого сервера, дождитесь завершения');
  }
  const slug = slugify(displayName || ('server-' + crypto.randomBytes(3).toString('hex')));
  const destDir = path.join(SERVERS_DIR, slug);
  fs.mkdirSync(SERVERS_DIR, { recursive: true });

  Object.assign(progress, { state: 'downloading', percent: 0, message: 'Подключение...', error: null, serverName: slug });

  const tmpFile = path.join('/tmp', slug + '-' + Date.now());
  try {
    const resp = await fetch(url);
    if (!resp.ok || !resp.body) throw new Error('HTTP ' + resp.status + ' при скачивании по ссылке');
    const total = parseInt(resp.headers.get('content-length') || '0', 10);
    let loaded = 0;
    const fileStream = fs.createWriteStream(tmpFile);
    const reader = resp.body.getReader();
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      loaded += value.length;
      fileStream.write(Buffer.from(value));
      progress.percent = total ? Math.round((loaded / total) * 90) : Math.min(85, progress.percent + 1);
      progress.message = 'Скачивание: ' + (total ? (loaded / 1048576).toFixed(1) + ' / ' + (total / 1048576).toFixed(1) + ' МБ' : (loaded / 1048576).toFixed(1) + ' МБ');
    }
    await new Promise((res, rej) => fileStream.end(err => err ? rej(err) : res()));

    progress.state = 'extracting';
    progress.message = 'Распаковка архива...';
    progress.percent = 92;

    fs.mkdirSync(destDir, { recursive: true });
    const lower = url.toLowerCase();
    if (lower.endsWith('.zip') || lower.includes('.zip?')) {
      await extractZip(tmpFile, { dir: destDir });
    } else if (lower.endsWith('.tar.gz') || lower.endsWith('.tgz') || lower.includes('.tar.gz')) {
      await tar.x({ file: tmpFile, cwd: destDir });
    } else {
      // пробуем как zip по умолчанию, иначе как tar.gz
      try { await extractZip(tmpFile, { dir: destDir }); }
      catch (e) { await tar.x({ file: tmpFile, cwd: destDir }); }
    }
    await flattenSingleDir(destDir);

    const entryRel = findEntry(destDir, entryCandidates);
    if (!entryRel) {
      throw new Error('В архиве не найден исполняемый файл сервера (' + entryCandidates.join(', ') + '). Проверьте ссылку.');
    }
    try {
      fs.chmodSync(path.join(SERVERS_DIR, entryRel), 0o755);
    } catch (e) {}

    progress.state = 'done';
    progress.percent = 100;
    progress.message = 'Готово';
    return { slug, entryRel };
  } catch (e) {
    progress.state = 'error';
    progress.error = e.message;
    fs.rmSync(destDir, { recursive: true, force: true });
    throw e;
  } finally {
    fs.rm(tmpFile, { force: true }, () => {});
  }
}

function listServers(entryCandidates) {
  fs.mkdirSync(SERVERS_DIR, { recursive: true });
  const active = readActive();
  return fs.readdirSync(SERVERS_DIR, { withFileTypes: true })
    .filter(e => e.isDirectory())
    .map(e => {
      const dir = path.join(SERVERS_DIR, e.name);
      const entryRel = findEntry(dir, entryCandidates);
      return {
        name: e.name,
        ready: !!entryRel,
        active: active === e.name,
        installedAt: fs.statSync(dir).mtime,
      };
    });
}

function readActive() {
  try { return JSON.parse(fs.readFileSync(ACTIVE_FILE, 'utf8')).name; } catch (e) { return null; }
}

function setActive(name) {
  fs.mkdirSync(path.dirname(ACTIVE_FILE), { recursive: true });
  fs.writeFileSync(ACTIVE_FILE, JSON.stringify({ name }, null, 2));
}

function removeServer(name) {
  const dir = path.join(SERVERS_DIR, slugify(name) === name ? name : name);
  fs.rmSync(path.join(SERVERS_DIR, name), { recursive: true, force: true });
  if (readActive() === name) {
    try { fs.rmSync(ACTIVE_FILE, { force: true }); } catch (e) {}
  }
}

module.exports = { downloadAndExtract, listServers, getProgress, setActive, readActive, removeServer, slugify };
