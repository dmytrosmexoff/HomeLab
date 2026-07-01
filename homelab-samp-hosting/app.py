import os
import json
import subprocess
import time
import re
from datetime import datetime, timedelta
from flask import Flask, render_template, jsonify, request, send_from_directory
import psutil
from rcon import RCON

app = Flask(__name__)

# Загрузка конфига
with open('config.json', 'r') as f:
    config = json.load(f)

SERVER_PATH = config['server_path']
RCON_PASS = config['rcon_password']
SERVER_PORT = config['server_port']
HOST = config['host']
PORT = config['port']

# файлы
PID_FILE = os.path.join(SERVER_PATH, 'samp.pid')
LOG_FILE = os.path.join(SERVER_PATH, 'server_log.txt')
CFG_FILE = os.path.join(SERVER_PATH, 'server.cfg')
HISTORY_FILE = 'logs/history.json'

# инициализация истории
if not os.path.exists(HISTORY_FILE):
    os.makedirs('logs', exist_ok=True)
    with open(HISTORY_FILE, 'w') as f:
        json.dump({"hourly": [], "daily": []}, f)

def get_server_pid():
    if os.path.exists(PID_FILE):
        with open(PID_FILE, 'r') as f:
            try:
                pid = int(f.read().strip())
                if psutil.pid_exists(pid):
                    return pid
            except:
                pass
    return None

def is_server_running():
    return get_server_pid() is not None

def get_process_info():
    pid = get_server_pid()
    if not pid:
        return None
    try:
        proc = psutil.Process(pid)
        cpu = proc.cpu_percent(interval=0.5)
        mem = proc.memory_info().rss / (1024**3)  # GB
        return {"cpu": cpu, "ram": mem}
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None

def start_server():
    if is_server_running():
        return False
    # запуск в фоне
    proc = subprocess.Popen(
        [os.path.join(SERVER_PATH, 'samp03svr')],
        cwd=SERVER_PATH,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL
    )
    with open(PID_FILE, 'w') as f:
        f.write(str(proc.pid))
    return True

def stop_server():
    pid = get_server_pid()
    if not pid:
        return False
    try:
        proc = psutil.Process(pid)
        proc.terminate()
        proc.wait(timeout=5)
    except:
        proc.kill()
    if os.path.exists(PID_FILE):
        os.remove(PID_FILE)
    return True

def restart_server():
    stop_server()
    time.sleep(1)
    start_server()

def get_rcon_connection():
    return RCON('127.0.0.1', SERVER_PORT, RCON_PASS)

def get_players_from_rcon():
    if not is_server_running():
        return None
    try:
        with get_rcon_connection() as rcon:
            resp = rcon.command('status')
            if resp is None:
                return None
            # парсинг
            lines = resp.splitlines()
            players = []
            for line in lines:
                # формат: "0\tCarl_Johnson\t100\t200"
                parts = line.split('\t')
                if len(parts) >= 3:
                    try:
                        pid = int(parts[0])
                        name = parts[1]
                        ping = int(parts[2]) if len(parts) > 2 else 0
                        players.append({"id": pid, "name": name, "ping": ping})
                    except:
                        continue
            return players
    except Exception as e:
        print("RCON error:", e)
        return None

def get_server_info_from_rcon():
    # пробуем получить через status
    players = get_players_from_rcon()
    if players is not None:
        return {"players": players, "count": len(players)}
    return None

def parse_log_for_history():
    # парсим server_log.txt за последние 14 дней, собираем статистику по дням и часам
    if not os.path.exists(LOG_FILE):
        return
    with open(LOG_FILE, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()
    # ищем строки подключения и отключения
    # пример: [connection] 192.168.1.1:1234 (или [join] PlayerName)
    # будем считать изменения количества игроков
    # но для простоты будем записывать текущее количество каждый час, если сервер запущен.
    pass

def get_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, 'r') as f:
            return json.load(f)
    return {"hourly": [], "daily": []}

def update_history(current_count):
    # обновляем историю: добавляем запись с текущим временем
    history = get_history()
    now = datetime.now()
    # hourly: храним до 24 записей (по часам)
    hourly = history.get('hourly', [])
    # если последняя запись была более часа назад, добавляем новую
    if hourly:
        last_time = datetime.fromisoformat(hourly[-1]['time'])
        if (now - last_time).total_seconds() < 3600:
            # обновляем последнюю запись
            hourly[-1]['count'] = current_count
        else:
            hourly.append({"time": now.isoformat(), "count": current_count})
    else:
        hourly.append({"time": now.isoformat(), "count": current_count})
    # ограничиваем 24 записями
    if len(hourly) > 24:
        hourly = hourly[-24:]
    history['hourly'] = hourly

    # daily: храним до 14 записей (по дням)
    daily = history.get('daily', [])
    day_key = now.strftime('%Y-%m-%d')
    # ищем запись за сегодня
    found = False
    for entry in daily:
        if entry['day'] == day_key:
            entry['count'] = current_count  # или можно хранить среднее, но пусть последнее
            found = True
            break
    if not found:
        daily.append({"day": day_key, "count": current_count})
    # ограничиваем 14 днями
    if len(daily) > 14:
        daily = daily[-14:]
    history['daily'] = daily

    with open(HISTORY_FILE, 'w') as f:
        json.dump(history, f)

@app.route('/')
def index():
    return render_template('index.html', brand="Homelab")

@app.route('/api/status')
def api_status():
    running = is_server_running()
    players = []
    count = 0
    if running:
        info = get_server_info_from_rcon()
        if info:
            players = info['players']
            count = info['count']
    else:
        # если сервер не запущен, пытаемся получить через query (просто кол-во)
        # но для простоты оставляем 0
        pass
    proc = get_process_info()
    cpu = proc['cpu'] if proc else 0
    ram = proc['ram'] if proc else 0
    # uptime – по времени запуска процесса
    uptime_seconds = 0
    if running and proc:
        pid = get_server_pid()
        try:
            p = psutil.Process(pid)
            uptime_seconds = int(time.time() - p.create_time())
        except:
            pass

    # обновляем историю (с текущим количеством игроков)
    if running:
        update_history(count)

    return jsonify({
        "online": running,
        "players": players,
        "count": count,
        "max_players": 150,  # можно читать из server.cfg
        "cpu": round(cpu, 1),
        "ram": round(ram, 2),
        "uptime_seconds": uptime_seconds,
        "server_info": {
            "gamemode": "Roleplay",  # можно парсить из лога
            "version": "0.3.7-R5",
            "slots": 150
        }
    })

@app.route('/api/history')
def api_history():
    history = get_history()
    return jsonify(history)

@app.route('/api/logs')
def api_logs():
    # возвращаем последние N строк лога
    if not os.path.exists(LOG_FILE):
        return jsonify({"lines": []})
    with open(LOG_FILE, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()
    # последние 50 строк
    lines = lines[-50:]
    return jsonify({"lines": lines})

@app.route('/api/config')
def api_config():
    if not os.path.exists(CFG_FILE):
        return jsonify({"content": ""})
    with open(CFG_FILE, 'r') as f:
        content = f.read()
    return jsonify({"content": content})

@app.route('/api/config', methods=['POST'])
def save_config():
    data = request.json
    new_content = data.get('content', '')
    with open(CFG_FILE, 'w') as f:
        f.write(new_content)
    return jsonify({"success": True})

@app.route('/api/control', methods=['POST'])
def control_server():
    action = request.json.get('action')
    if action == 'start':
        result = start_server()
        return jsonify({"success": result})
    elif action == 'stop':
        result = stop_server()
        return jsonify({"success": result})
    elif action == 'restart':
        restart_server()
        return jsonify({"success": True})
    else:
        return jsonify({"success": False, "error": "Неизвестное действие"})

@app.route('/api/rcon', methods=['POST'])
def rcon_command():
    cmd = request.json.get('cmd')
    if not cmd:
        return jsonify({"success": False, "error": "Команда не указана"})
    if not is_server_running():
        return jsonify({"success": False, "error": "Сервер не запущен"})
    try:
        with get_rcon_connection() as rcon:
            resp = rcon.command(cmd)
            return jsonify({"success": True, "response": resp})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

# для статики
@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory('static', filename)

if __name__ == '__main__':
    app.run(host=HOST, port=PORT, debug=config.get('debug', False))