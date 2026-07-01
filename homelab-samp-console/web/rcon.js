const dgram = require('dgram');

// Отправляет RCON-команду на SA-MP сервер и возвращает текстовый ответ
function sendRcon(host, port, password, command, timeoutMs = 1500) {
  return new Promise((resolve, reject) => {
    const socket = dgram.createSocket('udp4');
    const ipParts = [0, 0, 0, 0]; // хост подставляется DNS-резолвом ниже, тело пакета IP не критично
    const opcode = Buffer.from('x');
    const passBuf = Buffer.from(password, 'ascii');
    const cmdBuf = Buffer.from(command, 'ascii');

    const header = Buffer.concat([
      Buffer.from('SAMP'),
      Buffer.from(ipParts),
      Buffer.from([port & 0xff, (port >> 8) & 0xff]),
      Buffer.from([opcode.length & 0xff, (opcode.length >> 8) & 0xff]),
      opcode,
      Buffer.from([passBuf.length & 0xff, (passBuf.length >> 8) & 0xff]),
      passBuf,
      Buffer.from([cmdBuf.length & 0xff, (cmdBuf.length >> 8) & 0xff]),
      cmdBuf
    ]);

    let responses = [];
    const timer = setTimeout(() => {
      socket.close();
      resolve(responses.join('\n')); // SA-MP может не ответить на некоторые команды — не ошибка
    }, timeoutMs);

    socket.on('message', (msg) => {
      // Формат ответа: SAMP + ip(4) + port(2) + opcodeLen(2) + opcode(1) + textLen(2) + text
      const textLen = msg.readUInt16LE(11);
      const text = msg.slice(13, 13 + textLen).toString('ascii');
      responses.push(text);
    });

    socket.on('error', (err) => {
      clearTimeout(timer);
      socket.close();
      reject(err);
    });

    socket.send(header, port, host);
  });
}

module.exports = { sendRcon };
