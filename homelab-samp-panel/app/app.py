from flask import Flask, request, jsonify, render_template_string
import json, os, subprocess, signal, time, struct, socket, threading
from datetime import datetime, timedelta
import zipfile, shutil, glob

app = Flask(__name__)

SERVER_DIR = os.environ.get("SERVER_DIR", "/server")
DATA_DIR   = os.environ.get("DATA_DIR",   "/data")
STATS_FILE = os.path.join(DATA_DIR, "stats.json")
LOG_FILE   = os.path.join(DATA_DIR, "server.log")

_proc      = None
_start_time = None
_lock      = threading.Lock()

# ── persistence ──────────────────────────────────────────────────────────────
def load_stats():
    if not os.path.exists(STATS_FILE):
        return {"sessions": [], "hourly": []}
    with open(STATS_FILE) as f:
        return json.load(f)

def save_stats(s):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(STATS_FILE, "w") as f:
        json.dump(s, f, indent=2)

def log(msg):
    os.makedirs(DATA_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a") as f:
        f.write(f"[{ts}] {msg}\n")

# ── SAMP query protocol (UDP) ─────────────────────────────────────────────────
def samp_query(host="127.0.0.1", port=7777, timeout=2.0):
    """Returns (players_count, players_list, hostname, gamemode) or None."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        ip_parts = [int(x) for x in host.split(".")]
        packet  = b"SAMP"
        packet += bytes(ip_parts)
        packet += struct.pack("<H", port)
        packet += b"i"   # info packet
        sock.sendto(packet, (host, port))
        data = sock.recv(512)
        sock.close()
        if len(data) < 11 or data[:4] != b"SAMP":
            return None
        offset = 11
        password   = struct.unpack_from("<B", data, offset)[0]; offset += 1
        players    = struct.unpack_from("<H", data, offset)[0]; offset += 2
        max_players= struct.unpack_from("<H", data, offset)[0]; offset += 2
        hn_len     = struct.unpack_from("<I", data, offset)[0]; offset += 4
        hostname   = data[offset:offset+hn_len].decode("cp1251","ignore"); offset += hn_len
        gm_len     = struct.unpack_from("<I", data, offset)[0]; offset += 4
        gamemode   = data[offset:offset+gm_len].decode("cp1251","ignore")
        return {"players": players, "max": max_players,
                "hostname": hostname, "gamemode": gamemode}
    except Exception:
        return None

def samp_players(host="127.0.0.1", port=7777, timeout=2.0):
    """Returns list of player names via 'd' (detailed players) packet."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        ip_parts = [int(x) for x in host.split(".")]
        packet  = b"SAMP"
        packet += bytes(ip_parts)
        packet += struct.pack("<H", port)
        packet += b"d"
        sock.sendto(packet, (host, port))
        data = sock.recv(2048)
        sock.close()
        if len(data) < 12 or data[:4] != b"SAMP":
            return []
        offset  = 11
        count   = struct.unpack_from("<B", data, offset)[0]; offset += 1
        players = []
        for _ in range(count):
            offset += 1  # id
            nlen    = struct.unpack_from("<B", data, offset)[0]; offset += 1
            name    = data[offset:offset+nlen].decode("cp1251","ignore"); offset += nlen
            offset += 4  # score
            offset += 4  # ping
            players.append(name)
        return players
    except Exception:
        return []

# ── background recorder ───────────────────────────────────────────────────────
def _recorder():
    while True:
        time.sleep(60)
        info = samp_query()
        if info:
            stats = load_stats()
            stats.setdefault("hourly", [])
            stats["hourly"].append({
                "ts": datetime.now().isoformat(timespec="minutes"),
                "cnt": info["players"]
            })
            # keep 7 days = 10080 minutes
            stats["hourly"] = stats["hourly"][-10080:]
            save_stats(stats)

threading.Thread(target=_recorder, daemon=True).start()

# ── server control ────────────────────────────────────────────────────────────
def _find_binary():
    for name in ["samp03svr", "samp-server", "samp03svr_x86"]:
        p = os.path.join(SERVER_DIR, name)
        if os.path.isfile(p):
            return p, "linux"
    for name in ["samp-server.exe", "samp03svr.exe"]:
        p = os.path.join(SERVER_DIR, name)
        if os.path.isfile(p):
            return p, "wine"
    return None, None

def server_running():
    global _proc
    return _proc is not None and _proc.poll() is None

def start_server():
    global _proc, _start_time
    if server_running():
        return False, "Уже запущен"
    binary, mode = _find_binary()
    if not binary:
        return False, "Бинарник сервера не найден в /server"
    cmd = [binary] if mode == "linux" else ["wine", binary]
    if mode == "linux":
        os.chmod(binary, 0o755)
    _proc = subprocess.Popen(cmd, cwd=SERVER_DIR,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _start_time = time.time()
    stats = load_stats()
    stats.setdefault("sessions", [])
    stats["sessions"].append({"start": datetime.now().isoformat(), "stop": None})
    save_stats(stats)
    log(f"Server started (mode={mode}, pid={_proc.pid})")
    return True, "Сервер запущен"

def stop_server():
    global _proc, _start_time
    if not server_running():
        return False, "Сервер не запущен"
    _proc.terminate()
    try:
        _proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        _proc.kill()
    stats = load_stats()
    if stats.get("sessions") and stats["sessions"][-1]["stop"] is None:
        stats["sessions"][-1]["stop"] = datetime.now().isoformat()
    save_stats(stats)
    log("Server stopped")
    _proc = None; _start_time = None
    return True, "Сервер остановлен"

# ── server.cfg helpers ────────────────────────────────────────────────────────
def read_cfg():
    path = os.path.join(SERVER_DIR, "server.cfg")
    if not os.path.exists(path):
        return {}
    result = {}
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and " " in line:
                k, _, v = line.partition(" ")
                result[k] = v
    return result

def write_cfg(data: dict):
    path = os.path.join(SERVER_DIR, "server.cfg")
    with open(path, "w", encoding="utf-8") as f:
        for k, v in data.items():
            f.write(f"{k} {v}\n")

# ── API routes ────────────────────────────────────────────────────────────────
@app.route("/api/status")
def api_status():
    running = server_running()
    info    = samp_query() if running else None
    uptime  = int(time.time() - _start_time) if running and _start_time else 0
    return jsonify({
        "running": running,
        "uptime": uptime,
        "info": info,
        "has_binary": _find_binary()[0] is not None,
        "server_dir_files": os.listdir(SERVER_DIR) if os.path.isdir(SERVER_DIR) else []
    })

@app.route("/api/players")
def api_players():
    if not server_running():
        return jsonify({"players": []})
    return jsonify({"players": samp_players()})

@app.route("/api/start",   methods=["POST"])
def api_start():
    ok, msg = start_server()
    return jsonify({"ok": ok, "msg": msg})

@app.route("/api/stop",    methods=["POST"])
def api_stop():
    ok, msg = stop_server()
    return jsonify({"ok": ok, "msg": msg})

@app.route("/api/restart", methods=["POST"])
def api_restart():
    stop_server()
    time.sleep(1)
    ok, msg = start_server()
    return jsonify({"ok": ok, "msg": msg})

@app.route("/api/cfg",     methods=["GET"])
def api_cfg_get():
    return jsonify({"cfg": read_cfg()})

@app.route("/api/cfg",     methods=["POST"])
def api_cfg_set():
    data = request.get_json() or {}
    write_cfg(data.get("cfg", {}))
    return jsonify({"ok": True})

@app.route("/api/chart/week")
def api_chart_week():
    stats  = load_stats()
    hourly = stats.get("hourly", [])
    now    = datetime.now()
    days   = {}
    for i in range(6, -1, -1):
        d = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        days[d] = {"date": d, "max": 0, "avg": 0, "samples": []}
    for entry in hourly:
        d = entry["ts"][:10]
        if d in days:
            days[d]["samples"].append(entry["cnt"])
    result = []
    for d, v in sorted(days.items()):
        s = v["samples"]
        result.append({
            "date":  d,
            "max":   max(s) if s else 0,
            "avg":   round(sum(s)/len(s), 1) if s else 0
        })
    return jsonify({"chart": result})

@app.route("/api/chart/today")
def api_chart_today():
    stats  = load_stats()
    hourly = stats.get("hourly", [])
    today  = datetime.now().strftime("%Y-%m-%d")
    points = [e for e in hourly if e["ts"].startswith(today)]
    return jsonify({"points": points[-120:]})   # last 2h max

@app.route("/api/upload", methods=["POST"])
def api_upload():
    f = request.files.get("file")
    if not f:
        return jsonify({"ok": False, "msg": "Файл не выбран"})
    fname = f.filename or ""
    if fname.endswith(".zip"):
        tmp = "/tmp/samp_upload.zip"
        f.save(tmp)
        with zipfile.ZipFile(tmp) as z:
            z.extractall(SERVER_DIR)
        os.remove(tmp)
        return jsonify({"ok": True, "msg": "Архив распакован в /server"})
    else:
        dest = os.path.join(SERVER_DIR, fname)
        f.save(dest)
        return jsonify({"ok": True, "msg": f"Файл сохранён: {fname}"})

@app.route("/api/log")
def api_log():
    if not os.path.exists(LOG_FILE):
        return jsonify({"log": ""})
    with open(LOG_FILE) as f:
        lines = f.readlines()
    return jsonify({"log": "".join(lines[-100:])})

@app.route("/api/sessions")
def api_sessions():
    stats    = load_stats()
    sessions = stats.get("sessions", [])[-20:]
    result   = []
    for s in reversed(sessions):
        start = datetime.fromisoformat(s["start"])
        if s["stop"]:
            stop     = datetime.fromisoformat(s["stop"])
            duration = int((stop - start).total_seconds())
        else:
            duration = int((datetime.now() - start).total_seconds())
        result.append({
            "start":    s["start"][:16].replace("T", " "),
            "stop":     (s["stop"] or "")[:16].replace("T", " ") or "—",
            "duration": duration
        })
    return jsonify({"sessions": result})

# ── HTML ──────────────────────────────────────────────────────────────────────
HTML = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SAMP Panel</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0f1115;color:#eee;min-height:100vh;padding:28px 16px}
h1{font-size:1.7rem;font-weight:700;background:linear-gradient(90deg,#3D6BFF,#00d2a0);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:4px}
.sub{color:#6c727f;font-size:.9rem;margin-bottom:28px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px;margin-bottom:24px}
.card{background:#1a1d24;border:1px solid #2a2d36;border-radius:16px;padding:22px}
.card h2{font-size:.85rem;font-weight:600;color:#6c727f;text-transform:uppercase;letter-spacing:.5px;margin-bottom:14px}
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
.btn-row{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}
.chart-wrap{position:relative;height:180px}
.full-chart{height:200px}
table{width:100%;border-collapse:collapse;font-size:.82rem}
th{color:#6c727f;font-weight:600;padding:10px 12px;border-bottom:1px solid #2a2d36;text-align:left;text-transform:uppercase;font-size:.72rem;letter-spacing:.4px}
td{padding:11px 12px;border-bottom:1px solid #1e2128;color:#ccc}
tr:last-child td{border-bottom:none}
.empty{color:#6c727f;text-align:center;padding:24px}
.log-box{background:#0f1115;border:1px solid #2a2d36;border-radius:8px;padding:12px;font-family:monospace;font-size:.75rem;color:#8a9ab5;max-height:160px;overflow-y:auto;white-space:pre-wrap;word-break:break-all}
.cfg-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.cfg-row{display:flex;gap:6px;align-items:center}
.cfg-row label{font-size:.75rem;color:#6c727f;width:110px;flex-shrink:0}
.cfg-row input{flex:1;background:#0f1115;border:1px solid #2a2d36;border-radius:6px;color:#fff;font-size:.8rem;padding:6px 10px;outline:none;min-width:0}
.cfg-row input:focus{border-color:#3D6BFF}
.upload-zone{border:2px dashed #2a2d36;border-radius:10px;padding:28px;text-align:center;color:#6c727f;font-size:.85rem;cursor:pointer;transition:border-color .2s;margin-top:10px}
.upload-zone:hover{border-color:#3D6BFF}
.toast{position:fixed;bottom:24px;right:24px;background:#1a1d24;border:1px solid #2a2d36;border-radius:10px;padding:12px 20px;font-size:.85rem;display:none;z-index:100;color:#eee}
.toast.show{display:block}
.player-pill{display:inline-block;background:#1e2128;border:1px solid #2a2d36;border-radius:20px;padding:4px 12px;font-size:.8rem;margin:3px;color:#ccc}
.section{background:#1a1d24;border:1px solid #2a2d36;border-radius:16px;padding:22px;margin-bottom:24px}
.section h2{font-size:.85rem;font-weight:600;color:#6c727f;text-transform:uppercase;letter-spacing:.5px;margin-bottom:16px}
</style>
</head>
<body>
<h1>🎮 SAMP Panel</h1>
<p class="sub">Панель управления SA-MP сервером</p>

<!-- Stat cards -->
<div class="grid" id="statCards">
  <div class="card">
    <h2>Статус</h2>
    <div id="statusBadge"><span class="badge off">Офлайн</span></div>
    <div class="btn-row">
      <button class="btn btn-green" onclick="ctrl('start')">▶ Запустить</button>
      <button class="btn btn-red"   onclick="ctrl('stop')">■ Стоп</button>
      <button class="btn btn-gray"  onclick="ctrl('restart')">↺ Рестарт</button>
    </div>
  </div>
  <div class="card">
    <h2>Игроки онлайн</h2>
    <div class="stat-val" id="cntOnline">—</div>
    <div class="stat-sub" id="cntMax"></div>
  </div>
  <div class="card">
    <h2>Аптайм</h2>
    <div class="stat-val" id="uptimeVal">—</div>
    <div class="stat-sub" id="hostnameVal"></div>
  </div>
  <div class="card">
    <h2>Режим игры</h2>
    <div class="stat-val" style="font-size:1.1rem" id="gamemodeVal">—</div>
    <div class="stat-sub" id="binaryInfo"></div>
  </div>
</div>

<!-- Charts row -->
<div class="grid" style="grid-template-columns:1fr 1fr">
  <div class="card">
    <h2>Онлайн за 7 дней (макс)</h2>
    <div class="chart-wrap"><canvas id="weekChart"></canvas></div>
  </div>
  <div class="card">
    <h2>Онлайн сегодня (реальное время)</h2>
    <div class="chart-wrap"><canvas id="todayChart"></canvas></div>
  </div>
</div>

<!-- Players list -->
<div class="section">
  <h2>Игроки в сети <span id="playerCount" style="color:#fff"></span></h2>
  <div id="playersWrap"><span class="empty">Загрузка...</span></div>
</div>

<!-- Sessions table -->
<div class="section">
  <h2>История сессий</h2>
  <table>
    <thead><tr><th>Запуск</th><th>Остановка</th><th>Длительность</th></tr></thead>
    <tbody id="sessionsBody"><tr><td colspan="3" class="empty">Загрузка...</td></tr></tbody>
  </table>
</div>

<!-- server.cfg editor -->
<div class="section">
  <h2>server.cfg</h2>
  <div class="cfg-grid" id="cfgGrid"></div>
  <div class="btn-row"><button class="btn btn-blue" onclick="saveCfg()">💾 Сохранить</button></div>
</div>

<!-- Upload -->
<div class="section">
  <h2>Загрузить файлы сервера</h2>
  <p style="font-size:.82rem;color:#6c727f;margin-bottom:8px">Загрузите .zip-архив с папкой сервера или отдельные файлы. Они попадут в /server.</p>
  <div class="upload-zone" onclick="document.getElementById('fileInput').click()">
    📁 Нажмите или перетащите сюда .zip или файл
  </div>
  <input type="file" id="fileInput" style="display:none" onchange="uploadFile(this)">
</div>

<!-- Log -->
<div class="section">
  <h2>Лог панели</h2>
  <div class="log-box" id="logBox">Загрузка...</div>
</div>

<div class="toast" id="toast"></div>

<script>
// ── helpers ──
function fmt(s){
  const h=Math.floor(s/3600),m=Math.floor((s%3600)/60),sec=s%60;
  if(h)return`${h}ч ${m}м`;
  if(m)return`${m}м ${sec}с`;
  return`${sec}с`;
}
function fmtDate(d){
  const dt=new Date(d);return`${String(dt.getDate()).padStart(2,'0')}.${String(dt.getMonth()+1).padStart(2,'0')}`;
}
function toast(msg,ok=true){
  const t=document.getElementById('toast');
  t.textContent=msg;t.style.borderColor=ok?'#00d264':'#ff3d3d';
  t.className='toast show';setTimeout(()=>t.className='toast',2500);
}

// ── charts ──
const chartCfg = (labels,data,label,color)=>({
  type:'line',
  data:{labels,datasets:[{label,data,borderColor:color,backgroundColor:color+'22',borderWidth:2,pointRadius:3,fill:true,tension:.35}]},
  options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},
    scales:{x:{ticks:{color:'#6c727f',font:{size:10}},grid:{color:'#1e2128'}},
            y:{ticks:{color:'#6c727f',font:{size:10}},grid:{color:'#1e2128'},beginAtZero:true}}}
});

let weekChart, todayChart;
function initCharts(){
  weekChart  = new Chart(document.getElementById('weekChart'),  chartCfg([],[],  'Макс игроков','#3D6BFF'));
  todayChart = new Chart(document.getElementById('todayChart'), chartCfg([],[], 'Игроков', '#00d2a0'));
}

function updateWeekChart(data){
  weekChart.data.labels   = data.map(d=>fmtDate(d.date));
  weekChart.data.datasets[0].data = data.map(d=>d.max);
  weekChart.update();
}
function updateTodayChart(pts){
  todayChart.data.labels  = pts.map(p=>p.ts.slice(11,16));
  todayChart.data.datasets[0].data = pts.map(p=>p.cnt);
  todayChart.update();
}

// ── status ──
let cfgData = {};
async function fetchStatus(){
  const r=await fetch('/api/status');const d=await r.json();
  const badge=document.getElementById('statusBadge');
  badge.innerHTML=d.running?'<span class="badge on">● Онлайн</span>':'<span class="badge off">○ Офлайн</span>';
  document.getElementById('uptimeVal').textContent = d.running?fmt(d.uptime):'—';
  if(d.info){
    document.getElementById('cntOnline').textContent  = d.info.players;
    document.getElementById('cntMax').textContent     = `из ${d.info.max}`;
    document.getElementById('hostnameVal').textContent= d.info.hostname||'';
    document.getElementById('gamemodeVal').textContent= d.info.gamemode||'—';
  } else {
    document.getElementById('cntOnline').textContent='—';
    document.getElementById('cntMax').textContent='';
    document.getElementById('hostnameVal').textContent='';
    document.getElementById('gamemodeVal').textContent='—';
  }
  const files=d.server_dir_files||[];
  document.getElementById('binaryInfo').textContent=
    files.includes('samp03svr')?'Linux-бинарник':
    files.some(f=>f.endsWith('.exe'))?'Windows (Wine)':
    d.has_binary?'Бинарник найден':'Бинарник не найден';
}

async function fetchPlayers(){
  const r=await fetch('/api/players');const d=await r.json();
  const w=document.getElementById('playersWrap');
  const pl=d.players||[];
  document.getElementById('playerCount').textContent=pl.length?`(${pl.length})`:'';
  if(!pl.length){w.innerHTML='<span class="empty">Игроков нет или сервер офлайн</span>';return;}
  w.innerHTML=pl.map(n=>`<span class="player-pill">👤 ${n}</span>`).join('');
}

async function fetchCharts(){
  const [wr,tr]=await Promise.all([fetch('/api/chart/week'),fetch('/api/chart/today')]);
  const [wd,td]=await Promise.all([wr.json(),tr.json()]);
  updateWeekChart(wd.chart||[]);
  updateTodayChart(td.points||[]);
}

async function fetchSessions(){
  const r=await fetch('/api/sessions');const d=await r.json();
  const body=document.getElementById('sessionsBody');
  const ses=d.sessions||[];
  if(!ses.length){body.innerHTML='<tr><td colspan="3" class="empty">Сессий нет</td></tr>';return;}
  body.innerHTML=ses.map(s=>`
    <tr>
      <td>${s.start}</td>
      <td>${s.stop}</td>
      <td>${fmt(s.duration)}</td>
    </tr>`).join('');
}

async function fetchCfg(){
  const r=await fetch('/api/cfg');const d=await r.json();
  cfgData=d.cfg||{};
  const grid=document.getElementById('cfgGrid');
  const keys=Object.keys(cfgData);
  if(!keys.length){grid.innerHTML='<span style="color:#6c727f;font-size:.82rem">server.cfg не найден или пуст</span>';return;}
  grid.innerHTML=keys.map(k=>`
    <div class="cfg-row">
      <label>${k}</label>
      <input id="cfg_${k}" value="${cfgData[k]||''}">
    </div>`).join('');
}

async function saveCfg(){
  const keys=Object.keys(cfgData);
  const updated={};
  keys.forEach(k=>{updated[k]=document.getElementById('cfg_'+k)?.value||'';});
  const r=await fetch('/api/cfg',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cfg:updated})});
  const d=await r.json();
  toast(d.ok?'server.cfg сохранён':'Ошибка',d.ok);
}

async function fetchLog(){
  const r=await fetch('/api/log');const d=await r.json();
  const box=document.getElementById('logBox');
  box.textContent=d.log||'Лог пуст';
  box.scrollTop=box.scrollHeight;
}

async function ctrl(action){
  const r=await fetch('/api/'+action,{method:'POST'});
  const d=await r.json();
  toast(d.msg, d.ok);
  setTimeout(fetchAll,1000);
}

async function uploadFile(input){
  const file=input.files[0];if(!file)return;
  const fd=new FormData();fd.append('file',file);
  toast('Загрузка...');
  const r=await fetch('/api/upload',{method:'POST',body:fd});
  const d=await r.json();
  toast(d.msg,d.ok);
  input.value='';
  fetchCfg();
}

// ── drag-drop ──
const zone=document.querySelector('.upload-zone');
zone.addEventListener('dragover',e=>{e.preventDefault();zone.style.borderColor='#3D6BFF';});
zone.addEventListener('dragleave',()=>{zone.style.borderColor='#2a2d36';});
zone.addEventListener('drop',e=>{
  e.preventDefault();zone.style.borderColor='#2a2d36';
  const file=e.dataTransfer.files[0];if(!file)return;
  const fd=new FormData();fd.append('file',file);
  toast('Загрузка...');
  fetch('/api/upload',{method:'POST',body:fd}).then(r=>r.json()).then(d=>toast(d.msg,d.ok));
});

function fetchAll(){
  fetchStatus();fetchPlayers();fetchCharts();fetchSessions();fetchLog();
}

initCharts();
fetchAll();
fetchCfg();
setInterval(fetchStatus,5000);
setInterval(fetchPlayers,10000);
setInterval(fetchCharts,60000);
setInterval(fetchLog,15000);
setInterval(fetchSessions,30000);
</script>
</body>
</html>"""

@app.route("/")
def index():
    return render_template_string(HTML)

if __name__ == "__main__":
    os.makedirs(SERVER_DIR, exist_ok=True)
    os.makedirs(DATA_DIR,   exist_ok=True)
    app.run(host="0.0.0.0", port=5750, threaded=True)
