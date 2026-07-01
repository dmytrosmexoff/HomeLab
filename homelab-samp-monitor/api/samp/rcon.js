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

// Отправляет RCON-команду по UDP (стандартный протокол SA-MP, требует rcon_password).
// Используется как резервный способ управления (например, с другого устройства в сети),
// основной канал команд в этом приложении — прямой ввод в консоль запущенного процесса.
function sendRcon(host, port, password, command, timeoutMs = 1500) {
  return new Promise((resolve) => {
    const socket = dgram.createSocket('udp4');
    const header = buildHeader(host, port, 'x');

    const passBuf = Buffer.alloc(2 + Buffer.byteLength(password));
    passBuf.writeUInt16LE(Buffer.byteLength(password), 0);
    passBuf.write(password, 2, 'ascii');

    const cmdBuf = Buffer.alloc(2 + Buffer.byteLength(command));
    cmdBuf.writeUInt16LE(Buffer.byteLength(command), 0);
    cmdBuf.write(command, 2, 'utf8');

    const packet = Buffer.concat([header, passBuf, cmdBuf]);
    const lines = [];
    let closed = false;

    const finish = () => {
      if (closed) return;
      closed = true;
      socket.close();
      resolve(lines);
    };

    let timer = setTimeout(finish, timeoutMs);

    socket.on('message', (msg) => {
      const body = msg.slice(11);
      if (body.length < 2) return;
      const len = body.readUInt16LE(0);
      const line = body.slice(2, 2 + len).toString('utf8');
      lines.push(line);
      clearTimeout(timer);
      timer = setTimeout(finish, 300); // ждём возможные доп. строки ответа
    });

    socket.on('error', finish);
    socket.send(packet, port, host);
  });
}

module.exports = { sendRcon };
