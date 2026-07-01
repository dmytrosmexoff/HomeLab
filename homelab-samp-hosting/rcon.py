import socket
import time
import struct

class RCON:
    def __init__(self, ip, port, password):
        self.ip = ip
        self.port = port
        self.password = password
        self.sock = None

    def _connect(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(5)
        self.sock.connect((self.ip, self.port))
        # авторизация
        self._send(3, self.password)
        response = self._recv()
        if response[1] != 2:  # ID ответа авторизации
            raise Exception("RCON авторизация не удалась")
        self._recv()  # дополнительный пустой пакет

    def _send(self, cmd_id, body):
        # формат пакета: длина, ID, тип, тело, \0\0
        body_bytes = body.encode('utf-8') + b'\x00\x00'
        packet = struct.pack('<ii', 10 + len(body_bytes), cmd_id) + b'\x00' + body_bytes
        packet = struct.pack('<i', len(packet)) + packet
        self.sock.send(packet)

    def _recv(self):
        # получить длину
        length_data = self.sock.recv(4)
        if not length_data:
            return None
        length = struct.unpack('<i', length_data)[0]
        data = self.sock.recv(length)
        # распарсить: ID, тип, тело
        cmd_id, cmd_type = struct.unpack('<ii', data[:8])
        body = data[8:-2].decode('utf-8')
        return (cmd_id, cmd_type, body)

    def command(self, cmd):
        if not self.sock:
            self._connect()
        self._send(2, cmd)
        response = self._recv()
        if response and response[0] == 2:
            return response[2]
        return None

    def close(self):
        if self.sock:
            self.sock.close()
            self.sock = None

    def __enter__(self):
        self._connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()