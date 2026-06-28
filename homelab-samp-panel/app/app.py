from flask import Flask, request, jsonify, render_template_string
import json, os, subprocess, signal, time, struct, socket, threading, psutil
from datetime import datetime, timedelta

app = Flask(__name__)
SERVER_DIR = os.environ.get("SERVER_DIR", "/server")
DATA_DIR   = os.environ.get("DATA_DIR",   "/data")
STATS_FILE = os.path.join(DATA_DIR, "stats.json")
LOG_FILE   = os.path.join(DATA_DIR, "panel.log")
RCON_PASS  = os.environ.get("RCON_PASSWORD", "changeme")

_proc = None
_start_time = None
_lock = threading.Lock()

def load_stats():
    try:
        if os.path.exists(STATS_FILE):
            with open(STATS_FILE) as f: return json.load(f)
    except: pass
    return {"sessions": [], "timeline": [], "daily_peak": {}}

def save_stats(s):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(STATS_FILE, "w") as f: json.dump(s, f, indent=2)

def log(msg):
    os.makedirs(DATA_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a") as f: f.write(f"[{ts}] {msg}\n")

def samp_query(host="127.0.0.1", port=7777, timeout=2.0):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        ip_parts = [int(x) for x in host.split(".")]
        pkt = b"SAMP" + bytes(ip_parts) + struct.pack("<H", port) + b"i"
        sock.sendto(pkt, (host, port))
        data = sock.recv(512); sock.close()
        if len(data) < 11 or data[:4] != b"SAMP": return None
        off = 11
        off += 1
        players = struct.unpack_from("<H", data, off)[0]; off += 2
        max_pl  = struct.unpack_from("<H", data, off)[0]; off += 2
        hn_len  = struct.unpack_from("<I", data, off)[0]; off += 4
        hostname = data[off:off+hn_len].decode("cp1251","ignore"); off += hn_len
        gm_len  = struct.unpack_from("<I", data, off)[0]; off += 4
        gamemode = data[off:off+gm_len].decode("cp1251","ignore")
        return {"players": players, "max": max_pl, "hostname": hostname, "gamemode": gamemode}
    except: return None

def samp_players(host="127.0.0.1", port=7777, timeout=2.0):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        ip_parts = [int(x) for x in host.split(".")]
        pkt = b"SAMP" + bytes(ip_parts) + struct.pack("<H", port) + b"d"
        sock.sendto(pkt, (host, port))
        data = sock.recv(2048); sock.close()
        if len(data) < 12 or data[:4] != b"SAMP": return []
        off = 11; count = struct.unpack_from("<B", data, off)[0]; off += 1
        players = []
        for _ in range(count):
            pid = struct.unpack_from("<B", data, off)[0]; off += 1
            nlen = struct.unpack_from("<B", data, off)[0]; off += 1
            name = data[off:off+nlen].decode("cp1251","ignore"); off += nlen
            score = struct.unpack_from("<i", data, off)[0]; off += 4
            ping  = struct.unpack_from("<i", data, off)[0]; off += 4
            players.append({"id": pid, "name": name, "score": score, "ping": ping})
        return players
    except: return []

def get_proc_metrics():
    global _proc
    cpu_total = psutil.cpu_percent(interval=0.1)
    ram = psutil.virtual_memory()
    ram_total_pct = ram.percent
    cpu_proc = ram_proc = 0
    if _proc and _proc.poll() is None:
        try:
            p = psutil.Process(_proc.pid)
            cpu_proc = p.cpu_percent(interval=0.1)
            ram_proc = round(p.memory_info().rss / ram.total * 100, 1)
        except: pass
    return {"cpu_total": cpu_total, "cpu_proc": cpu_proc,
            "ram_total": ram_total_pct, "ram_proc": ram_proc}

def _recorder():
    while True:
        time.sleep(300)
        info = samp_query()
        if info:
            stats = load_stats()
            ts = datetime.now().strftime("%H:%M")
            day = datetime.now().strftime("%Y-%m-%d")
            stats.setdefault("timeline", [])
            stats["timeline"].append({"t": ts, "v": info["players"]})
            if len(stats["timeline"]) > 288: stats["timeline"] = stats["timeline"][-288:]
            dp = stats.setdefault("daily_peak", {})
            dp[day] = max(dp.get(day, 0), info["players"])
            save_stats(stats)

threading.Thread(target=_recorder, daemon=True).start()

STYLE = """
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0f1115;color:#eee;min-height:100vh;padding:28px 16px}
h1{font-size:1.7rem;font-weight:700;background:linear-gradient(90deg,#3D6BFF,#00d2a0);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:4px}
.sub{color:#6c727f;font-size:.9rem;margin-bottom:24px}
.card{background:#1a1d24;border:1px solid #2a2d36;border-radius:16px;padding:22px;margin-bottom:20px}
.card h2{font-size:.78rem;font-weight:600;color:#6c727f;text-transform:uppercase;letter-spacing:.6px;margin-bottom:14px}
.stat-val{font-size:2rem;font-weight:700;color:#fff}
.stat-sub{font-size:.8rem;color:#6c727f;margin-top:2px}
.badge{display:inline-block;padding:4px 12px;border-radius:20px;font-size:.8rem;font-weight:600}
.badge.on{background:rgba(0,210,100,.15);color:#00d264}
.badge.off{background:rgba(255,61,61,.15);color:#ff3d3d}
.btn{border:none;border-radius:8px;cursor:pointer;font-size:.85rem;font-weight:600;padding:9px 18px;transition:opacity .2s}
.btn:hover{opacity:.8}
.btn-green{background:linear-gradient(90deg,#00d264,#00a86b);color:#fff}
.btn-red{background:linear-gradient(90deg,#ff3d3d,#c0392b);color:#fff}
.btn-blue{background:linear-gradient(90deg,#3D6BFF,#7b2dff);color:#fff}
.btn-gray{background:#2a2d36;color:#ccc}
.grid{display:grid;gap:16px}
.g2{grid-template-columns:1fr 1fr}
.g3{grid-template-columns:1fr 1fr 1fr}
.g4{grid-template-columns:repeat(4,1fr)}
table{width:100%;border-collapse:collapse;font-size:.82rem}
th{color:#6c727f;font-weight:600;padding:10px 12px;border-bottom:1px solid #2a2d36;text-align:left;text-transform:uppercase;font-size:.72rem;letter-spacing:.4px}
td{padding:11px 12px;border-bottom:1px solid #1e2128;color:#ccc}
.empty{color:#6c727f;text-align:center;padding:24px}
.log-box{background:#0f1115;border:1px solid #2a2d36;border-radius:8px;padding:12px;font-family:monospace;font-size:.75rem;color:#8a9ab5;height:220px;overflow-y:auto;white-space:pre-wrap;word-break:break-all}
.toast{position:fixed;bottom:24px;right:24px;background:#1a1d24;border:1px solid #2a2d36;border-radius:10px;padding:12px 20px;font-size:.85rem;display:none;z-index:100;color:#eee}
/* triple bar */
.bar-wrap{margin-bottom:14px}
.bar-label{display:flex;justify-content:space-between;font-size:.75rem;color:#6c727f;margin-bottom:5px}
.bar-track{position:relative;height:18px;background:rgba(0,0,0,.5);border-radius:9px;overflow:hidden}
.bar-total{position:absolute;left:0;top:0;height:100%;background:rgba(255,255,255,.07);border-radius:9px;transition:width .6s}
.bar-proc{position:absolute;left:0;top:0;height:100%;border-radius:9px;transition:width .6s}
.bar-peak{position:absolute;top:0;width:3px;height:100%;background:rgba(189,100,255,.9);border-radius:2px;transition:left .6s}
.bar-cpu .bar-proc{background:linear-gradient(90deg,#3D6BFF,#00d2a0)}
.bar-ram .bar-proc{background:linear-gradient(90deg,#7b2dff,#3D6BFF)}
/* console */
.console-out{background:#0a0c10;border:1px solid #2a2d36;border-radius:8px;padding:10px;font-family:monospace;font-size:.75rem;color:#00d264;height:160px;overflow-y:auto;white-space:pre-wrap;margin-bottom:8px}
.console-row{display:flex;gap:8px}
.console-row input{flex:1;background:#0f1115;border:1px solid #2a2d36;border-radius:6px;color:#fff;font-size:.82rem;padding:8px 12px;outline:none}
.console-row input:focus{border-color:#3D6BFF}
canvas{width:100%!important}
@media(max-width:640px){.g2,.g3,.g4{grid-template-columns:1fr}}
</style>
"""

HTML = STYLE + """
<div style="max-width:1100px;margin:0 auto">
<h1>🎮 SAMP Panel</h1>
<p class="sub">SA-MP Server Management</p>

<div class="grid g4">
  <div class="card"><h2>Статус</h2><div id="badge_status"><span class="badge off">Офлайн</span></div></div>
  <div class="card"><h2>Игроки</h2><div class="stat-val" id="stat_players">—</div><div class="stat-sub" id="stat_max">/ — слотов</div></div>
  <div class="card"><h2>Пик сегодня</h2><div class="stat-val" id="stat_peak">—</div><div class="stat-sub">игроков</div></div>
  <div class="card"><h2>Аптайм</h2><div class="stat-val" id="stat_uptime">—</div><div class="stat-sub" id="stat_mode">—</div></div>
</div>

<div class="card">
  <h2>Управление сервером</h2>
  <div style="display:flex;gap:10px;flex-wrap:wrap">
    <button class="btn btn-green" onclick="srv('start')">▶ Старт</button>
    <button class="btn btn-red"   onclick="srv('stop')">■ Стоп</button>
    <button class="btn btn-blue"  onclick="srv('restart')">↺ Рестарт</button>
  </div>
</div>

<div class="grid g2">
  <div class="card">
    <h2>Мониторинг CPU</h2>
    <div class="bar-wrap bar-cpu">
      <div class="bar-label"><span>CPU</span><span id="cpu_vals">—</span></div>
      <div class="bar-track">
        <div class="bar-total" id="cpu_total_bar"></div>
        <div class="bar-proc" id="cpu_proc_bar"></div>
        <div class="bar-peak" id="cpu_peak_bar"></div>
      </div>
      <div style="margin-top:6px;font-size:.7rem;color:#6c727f;display:flex;gap:14px">
        <span>⬛ Общая нагрузка</span><span style="color:#3D6BFF">🟦 Сервер</span><span style="color:#bd64ff">🟪 Пик</span>
      </div>
    </div>
    <div class="bar-wrap bar-ram">
      <div class="bar-label"><span>RAM</span><span id="ram_vals">—</span></div>
      <div class="bar-track">
        <div class="bar-total" id="ram_total_bar"></div>
        <div class="bar-proc" id="ram_proc_bar"></div>
        <div class="bar-peak" id="ram_peak_bar"></div>
      </div>
      <div style="margin-top:6px;font-size:.7rem;color:#6c727f;display:flex;gap:14px">
        <span>⬛ Общая нагрузка</span><span style="color:#7b2dff">🟪 Сервер</span><span style="color:#bd64ff">🟪 Пик</span>
      </div>
    </div>
  </div>
  <div class="card">
    <h2>RCON Консоль</h2>
    <div class="console-out" id="rcon_out">Введите команду...\n</div>
    <div class="console-row">
      <input id="rcon_cmd" placeholder="say Hello World" onkeydown="if(event.key==='Enter')sendRcon()">
      <button class="btn btn-blue" onclick="sendRcon()">Отправить</button>
    </div>
  </div>
</div>

<div class="grid g2">
  <div class="card">
    <h2>Онлайн (5-мин шаги)</h2>
    <canvas id="chart_timeline" height="120"></canvas>
  </div>
  <div class="card">
    <h2>Пик по дням</h2>
    <canvas id="chart_daily" height="120"></canvas>
  </div>
</div>

<div class="card">
  <h2>Онлайн игроки</h2>
  <table><thead><tr><th>#</th><th>Ник</th><th>Уровень</th><th>Онлайн</th><th>Пинг</th></tr></thead>
  <tbody id="players_body"><tr><td colspan="5" class="empty">Нет игроков</td></tr></tbody></table>
</div>

<div class="card">
  <h2>Лог сервера</h2>
  <div class="log-box" id="log_box">Загрузка...</div>
</div>
</div>

<div class="toast" id="toast"></div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js"></script>
<script>
let cpuPeak=0, ramPeak=0;
let tlChart=null, dayChart=null;

function toast(msg,ok=true){
  const t=document.getElementById('toast');
  t.textContent=msg; t.style.background=ok?'#1a1d24':'#2a1010';
  t.style.display='block'; setTimeout(()=>t.style.display='none',2500);
}

async function srv(action){
  const r=await fetch('/api/server/'+action,{method:'POST'});
  const d=await r.json(); toast(d.message, d.ok);
}

async function sendRcon(){
  const inp=document.getElementById('rcon_cmd');
  const cmd=inp.value.trim(); if(!cmd)return;
  const out=document.getElementById('rcon_out');
  out.textContent+=`> ${cmd}\n`; inp.value='';
  const r=await fetch('/api/rcon',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cmd})});
  const d=await r.json();
  out.textContent+=d.result+'\n'; out.scrollTop=out.scrollHeight;
}

function updateBar(totalId,procId,peakId,total,proc,peak,peakRef){
  document.getElementById(totalId).style.width=total+'%';
  document.getElementById(procId).style.width=Math.min(proc,100)+'%';
  document.getElementById(peakId).style.left=Math.min(peak,99)+'%';
}

function initChart(id,label,color){
  const ctx=document.getElementById(id).getContext('2d');
  return new Chart(ctx,{type:'line',data:{labels:[],datasets:[{label,data:[],borderColor:color,backgroundColor:color+'22',fill:true,tension:.4,pointRadius:2}]},options:{responsive:true,plugins:{legend:{display:false}},scales:{x:{ticks:{color:'#6c727f',maxTicksLimit:8}},y:{ticks:{color:'#6c727f'},beginAtZero:true,grid:{color:'#1e2128'}}}}});
}

async function poll(){
  try{
    const r=await fetch('/api/status'); const d=await r.json();
    // status
    document.getElementById('badge_status').innerHTML=d.running?'<span class="badge on">Онлайн</span>':'<span class="badge off">Офлайн</span>';
    document.getElementById('stat_players').textContent=d.info?d.info.players:'—';
    document.getElementById('stat_max').textContent=d.info?'/ '+d.info.max+' слотов':'/ — слотов';
    document.getElementById('stat_peak').textContent=d.today_peak;
    document.getElementById('stat_uptime').textContent=d.uptime||'—';
    document.getElementById('stat_mode').textContent=d.info?d.info.gamemode:'—';
    // bars
    const m=d.metrics;
    if(m.cpu_proc>cpuPeak)cpuPeak=m.cpu_proc;
    if(m.ram_proc>ramPeak)ramPeak=m.ram_proc;
    document.getElementById('cpu_vals').textContent=`Сервер: ${m.cpu_proc}% / Всего: ${m.cpu_total}%`;
    document.getElementById('ram_vals').textContent=`Сервер: ${m.ram_proc}% / Всего: ${m.ram_total}%`;
    updateBar('cpu_total_bar','cpu_proc_bar','cpu_peak_bar',m.cpu_total,m.cpu_proc,cpuPeak);
    updateBar('ram_total_bar','ram_proc_bar','ram_peak_bar',m.ram_total,m.ram_proc,ramPeak);
    // players
    const tbody=document.getElementById('players_body');
    if(d.players&&d.players.length){
      tbody.innerHTML=d.players.map((p,i)=>`<tr><td>${i+1}</td><td>${p.name}</td><td>${p.score}</td><td>—</td><td>${p.ping} ms</td></tr>`).join('');
    } else {
      tbody.innerHTML='<tr><td colspan="5" class="empty">Нет игроков онлайн</td></tr>';
    }
    // charts
    const stats=d.stats;
    if(stats.timeline&&tlChart){
      tlChart.data.labels=stats.timeline.map(x=>x.t);
      tlChart.data.datasets[0].data=stats.timeline.map(x=>x.v);
      tlChart.update('none');
    }
    if(stats.daily_peak&&dayChart){
      const days=Object.keys(stats.daily_peak).slice(-14);
      dayChart.data.labels=days.map(d=>d.slice(5));
      dayChart.data.datasets[0].data=days.map(d=>stats.daily_peak[d]);
      dayChart.update('none');
    }
    // log
    const lr=await fetch('/api/log'); const lt=await lr.text();
    const lb=document.getElementById('log_box');
    lb.textContent=lt; lb.scrollTop=lb.scrollHeight;
  }catch(e){}
  setTimeout(poll,5000);
}

tlChart=initChart('chart_timeline','Игроки','#3D6BFF');
dayChart=initChart('chart_daily','Пик','#00d2a0');
poll();
</script>
"""

@app.route("/")
def index(): return render_template_string(HTML)

@app.route("/api/status")
def status():
    global _proc, _start_time
    running = _proc is not None and _proc.poll() is None
    info = samp_query() if running else None
    players = samp_players() if running else []
    stats = load_stats()
    today = datetime.now().strftime("%Y-%m-%d")
    today_peak = stats.get("daily_peak", {}).get(today, 0)
    uptime = ""
    if running and _start_time:
        sec = int(time.time() - _start_time)
        h, m = divmod(sec, 3600); m, s = divmod(m, 60)
        uptime = f"{h:02d}:{m:02d}:{s:02d}"
    metrics = get_proc_metrics()
    return jsonify({"running": running, "info": info, "players": players,
                    "today_peak": today_peak, "uptime": uptime,
                    "metrics": metrics, "stats": stats})

@app.route("/api/server/<action>", methods=["POST"])
def server_action(action):
    global _proc, _start_time
    with _lock:
        if action == "start":
            if _proc and _proc.poll() is None:
                return jsonify({"ok": False, "message": "Сервер уже запущен"})
            binary = os.path.join(SERVER_DIR, "samp03svr")
            if not os.path.exists(binary):
                return jsonify({"ok": False, "message": "Бинарник samp03svr не найден в /server"})
            _proc = subprocess.Popen([binary], cwd=SERVER_DIR,
                                     stdout=open(os.path.join(DATA_DIR,"server.log"),"a"),
                                     stderr=subprocess.STDOUT)
            _start_time = time.time()
            log("Сервер запущен")
            return jsonify({"ok": True, "message": "Сервер запускается..."})
        elif action == "stop":
            if not _proc or _proc.poll() is not None:
                return jsonify({"ok": False, "message": "Сервер не запущен"})
            _proc.terminate()
            try: _proc.wait(timeout=15)
            except: _proc.kill()
            log("Сервер остановлен")
            return jsonify({"ok": True, "message": "Сервер остановлен"})
        elif action == "restart":
            if _proc and _proc.poll() is None:
                _proc.terminate()
                try: _proc.wait(timeout=15)
                except: _proc.kill()
            binary = os.path.join(SERVER_DIR, "samp03svr")
            if os.path.exists(binary):
                _proc = subprocess.Popen([binary], cwd=SERVER_DIR,
                                         stdout=open(os.path.join(DATA_DIR,"server.log"),"a"),
                                         stderr=subprocess.STDOUT)
                _start_time = time.time()
            log("Рестарт сервера")
            return jsonify({"ok": True, "message": "Сервер перезапускается..."})
    return jsonify({"ok": False, "message": "Неизвестное действие"})

@app.route("/api/rcon", methods=["POST"])
def rcon():
    data = request.get_json()
    cmd = data.get("cmd", "").strip()
    if not cmd: return jsonify({"result": "Пустая команда"})
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(3)
        ip_parts = [int(x) for x in "127.0.0.1".split(".")]
        pw = RCON_PASS.encode()
        pkt = b"SAMP" + bytes(ip_parts) + struct.pack("<H", 7777)
        pkt += b"x" + struct.pack("<H", len(pw)) + pw
        pkt += struct.pack("<H", len(cmd)) + cmd.encode()
        sock.sendto(pkt, ("127.0.0.1", 7777))
        sock.close()
        log(f"RCON: {cmd}")
        return jsonify({"result": f"[OK] Команда отправлена: {cmd}"})
    except Exception as e:
        return jsonify({"result": f"[ERR] {e}"})

@app.route("/api/log")
def get_log():
    log_path = os.path.join(DATA_DIR, "server.log")
    if not os.path.exists(log_path): return "Лог пуст\n"
    with open(log_path) as f:
        lines = f.readlines()
    return "".join(lines[-200:])

if __name__ == "__main__":
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(SERVER_DIR, exist_ok=True)
    app.run(host="0.0.0.0", port=5750, debug=False)
