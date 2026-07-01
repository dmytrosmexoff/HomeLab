'use strict';
const dgram = require('dgram');

function buildHeader(host, port, opcode) {
  const ipParts = host.split('.').map(Number);
  const header = Buffer.alloc(11);
  header.write('SAMP', 0, 'ascii');
  header[4] = ipParts[0]; header[5] = ipParts[1]; header[6] = ipParts[2]; header[7] = ipParts[3];
  header.writeUInt16LE(port, 8);
  header[10] = opcode.charCodeAt(0);
  return header;
}

function query(host, port, opcode, timeoutMs = 2000) {
  return new Promise((resolve, reject) => {
    const socket = dgram.createSocket('udp4');
    const packet = buildHeader(host, port, opcode);
    let done = false;

    const timer = setTimeout(() => {
      if (done) return;
      done = true;
      socket.close();
      reject(new Error('SA-MP query timeout: сервер не ответил'));
    }, timeoutMs);

    socket.once('message', (msg) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      socket.close();
      resolve(msg.slice(11)); // отрезаем заголовок SAMP+ip+port+opcode
    });

    socket.once('error', (err) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      socket.close();
      reject(err);
    });

    socket.send(packet, port, host);
  });
}

async function getInfo(host, port) {
  const data = await query(host, port, 'i');
  let o = 0;
  const password = data.readUInt8(o); o += 1;
  const players = data.readUInt16LE(o); o += 2;
  const maxplayers = data.readUInt16LE(o); o += 2;
  const hostnameLen = data.readUInt32LE(o); o += 4;
  const hostname = data.slice(o, o + hostnameLen).toString('utf8'); o += hostnameLen;
  const gamemodeLen = data.readUInt32LE(o); o += 4;
  const gamemode = data.slice(o, o + gamemodeLen).toString('utf8'); o += gamemodeLen;
  const languageLen = data.readUInt32LE(o); o += 4;
  const language = data.slice(o, o + languageLen).toString('utf8'); o += languageLen;
  return { password: !!password, players, maxplayers, hostname, gamemode, language };
}

// 'd' даёт список игроков вместе с реальным пингом каждого (работает пока players <= 100)
async function getPlayers(host, port) {
  const data = await query(host, port, 'd');
  let o = 0;
  const count = data.readUInt16LE(o); o += 2;
  const list = [];
  for (let i = 0; i < count; i++) {
    const id = data.readUInt8(o); o += 1;
    const nameLen = data.readUInt8(o); o += 1;
    const name = data.slice(o, o + nameLen).toString('utf8'); o += nameLen;
    const score = data.readInt32LE(o); o += 4;
    const ping = data.readInt32LE(o); o += 4;
    list.push({ id, name, score, ping });
  }
  return list;
}

async function getRules(host, port) {
  const data = await query(host, port, 'r');
  let o = 0;
  const count = data.readUInt16LE(o); o += 2;
  const rules = {};
  for (let i = 0; i < count; i++) {
    const keyLen = data.readUInt8(o); o += 1;
    const key = data.slice(o, o + keyLen).toString('utf8'); o += keyLen;
    const valLen = data.readUInt8(o); o += 1;
    const val = data.slice(o, o + valLen).toString('utf8'); o += valLen;
    rules[key] = val;
  }
  return rules;
}

module.exports = { getInfo, getPlayers, getRules };
