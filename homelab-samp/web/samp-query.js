// Реализация официального публичного query/RCON протокола SA-MP.
// Это тот же протокол, который используют все браузеры серверов и мониторинги
// (сайт sa-mp.com, samp.statussites и т.д.) — он намеренно открытый и документирован
// на wiki.open.mp / форумах SA-MP. Здесь нет ничего, что обходит защиту сервера:
// RCON всё ещё требует правильный пароль, который сервер сам проверяет.

const dgram = require('dgram');
const dns = require('dns').promises;

async function resolveIpOctets(host) {
  try {
    const { address } = await dns.lookup(host, { family: 4 });
    return address.split('.').map(Number);
  } catch (e) {
    return [0, 0, 0, 0];
  }
}

function buildHeader(ipOctets, port, opcode) {
  const buf = Buffer.alloc(11);
  buf.write('SAMP', 0, 'ascii');
  buf[4] = ipOctets[0]; buf[5] = ipOctets[1]; buf[6] = ipOctets[2]; buf[7] = ipOctets[3];
  buf.writeUInt16LE(port, 8);
  buf.write(opcode, 10, 'ascii');
  return buf;
}

function singleRequest(host, port, opcode, extraPayload, timeoutMs = 1500) {
  return new Promise(async (resolve, reject) => {
    const ipOctets = await resolveIpOctets(host);
    const socket = dgram.createSocket('udp4');
    const packet = Buffer.concat([buildHeader(ipOctets, port, opcode), extraPayload || Buffer.alloc(0)]);

    const timer = setTimeout(() => {
      socket.close();
      reject(new Error('Сервер не ответил (timeout). Возможно, он ещё запускается.'));
    }, timeoutMs);

    socket.once('message', (msg) => {
      clearTimeout(timer);
      socket.close();
      resolve(msg);
    });
    socket.once('error', (err) => {
      clearTimeout(timer);
      socket.close();
      reject(err);
    });
    socket.send(packet, port, host, (err) => {
      if (err) { clearTimeout(timer); socket.close(); reject(err); }
    });
  });
}

async function getInfo(host, port) {
  const msg = await singleRequest(host, port, 'i');
  let off = 11;
  const password = msg.readUInt8(off); off += 1;
  const players = msg.readUInt16LE(off); off += 2;
  const maxplayers = msg.readUInt16LE(off); off += 2;
  const hostnameLen = msg.readUInt32LE(off); off += 4;
  const hostname = msg.slice(off, off + hostnameLen).toString('utf8'); off += hostnameLen;
  const gamemodeLen = msg.readUInt32LE(off); off += 4;
  const gamemode = msg.slice(off, off + gamemodeLen).toString('utf8'); off += gamemodeLen;
  const languageLen = msg.readUInt32LE(off); off += 4;
  const language = msg.slice(off, off + languageLen).toString('utf8'); off += languageLen;
  return { password: !!password, players, maxplayers, hostname, gamemode, language };
}

async function getPlayers(host, port) {
  // opcode 'c' — короткий список (имя+счёт), доступен только если игроков < 100
  const msg = await singleRequest(host, port, 'c');
  let off = 11;
  const count = msg.readUInt16LE(off); off += 2;
  const players = [];
  for (let i = 0; i < count; i++) {
    const nameLen = msg.readUInt8(off); off += 1;
    const name = msg.slice(off, off + nameLen).toString('utf8'); off += nameLen;
    const score = msg.readInt32LE(off); off += 4;
    players.push({ name, score });
  }
  return players;
}

function sendRcon(host, port, password, command, collectMs = 600) {
  return new Promise(async (resolve, reject) => {
    const ipOctets = await resolveIpOctets(host);
    const pwBuf = Buffer.from(password, 'utf8');
    const cmdBuf = Buffer.from(command, 'utf8');
    const payload = Buffer.concat([
      Buffer.from([pwBuf.length & 0xff, (pwBuf.length >> 8) & 0xff]), pwBuf,
      Buffer.from([cmdBuf.length & 0xff, (cmdBuf.length >> 8) & 0xff]), cmdBuf,
    ]);
    const packet = Buffer.concat([buildHeader(ipOctets, port, 'x'), payload]);
    const socket = dgram.createSocket('udp4');
    const lines = [];

    socket.on('message', (msg) => {
      // header(11) + opcode(1, 'x') + 2 bytes line length + line
      let off = 12;
      if (msg.length > off + 2) {
        const lineLen = msg.readUInt16LE(off); off += 2;
        const line = msg.slice(off, off + lineLen).toString('utf8');
        lines.push(line);
      }
    });
    socket.on('error', (err) => { socket.close(); reject(err); });

    socket.send(packet, port, host, (err) => {
      if (err) { socket.close(); return reject(err); }
      setTimeout(() => {
        socket.close();
        resolve(lines);
      }, collectMs);
    });
  });
}

module.exports = { getInfo, getPlayers, sendRcon };
