from flask import Flask, request, jsonify, render_template_string
import json, os, subprocess, time, threading
from datetime import datetime, timedelta
import zipfile, psutil

app = Flask(__name__)

SERVER_DIR = os.environ.get("SERVER_DIR", "/server")
DATA_DIR   = os.environ.get("DATA_DIR",   "/data")
STATS_FILE = os.path.join(DATA_DIR, "stats.json")
LOG_FILE   = os.path.join(DATA_DIR, "server.log")

_proc       = None
_start_time = None
_lock       = threading.Lock()

# ── persistence ───────────────────────────────────────────────────────────────
def load_stats():
    if not os.path.exists(STATS_FILE):
        return {"sessions": [], "hourly": [], "daily_peak": [],
                "resource_usage": [], "total_players_played": 0,
                "total_uptime": 0, "crashes": 0}
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

# ── RAGE-MP: читаем conf.json напрямую ───────────────────────────────────────
def read_conf():
    path = os.path.join(SERVER_DIR, "conf.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log(f"read_conf error: {e}")
        return {}

def write_conf(data):
    path = os.path.join(SERVER_DIR, "conf.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def get_server_info():
    """Берём данные прямо из conf.json — не нужен HTTP API"""
    conf = read_conf()
    return {
        "hostname":    conf.get("name", "RAGE-MP Server"),
        "max_players": conf.get("maxPlayers", 100),
        "gamemode":    conf.get("gamemode", ""),
        "language":    conf.get("language", "ru"),
    }

# ── процесс ───────────────────────────────────────────────────────────────────
def _find_binary():
    for name in ["server", "ragemp-server", "server_linux"]:
        p = os.path.join(SERVER_DIR, name)
        if os.path.isfile(p):
            return p
    return None

def server_running():
    global _proc
    return _proc is not None and _proc.poll() is None

def start_server():
    global _proc, _start_time
    with _lock:
        if server_running():
            return False, "Уже запущен"
        binary = _find_binary()
        if not binary:
            return False, "Бинарник сервера не найден в /server"
        if not os.path.exists(os.path.join(SERVER_DIR, "conf.json")):
            return False, "conf.json не найден в /server"
        os.chmod(binary, 0o755)
        _proc = subprocess.Popen(
            [binary], cwd=SERVER_DIR,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        _start_time = time.time()
        stats = load_stats()
        stats.setdefault("sessions", []).append(
            {"start": datetime.now().isoformat(), "stop": None}
        )
        save_stats(stats)
        log(f"Server started pid={_proc.pid}")
        return True, "Сервер запущен"

def stop_server():
    global _proc, _start_time
    with _lock:
        if not server_running():
            return False, "Сервер не запущен"
        _proc.terminate()
        killed = False
        try:
            _proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _proc.kill()
            _proc.wait()
            killed = True
        if not killed and _proc.returncode not in (0, -15):
            stats = load_stats()
            stats["crashes"] = stats.get("crashes", 0) + 1
            save_stats(stats)
        stats = load_stats()
        if stats.get("sessions") and stats["sessions"][-1]["stop"] is None:
            stats["sessions"][-1]["stop"] = datetime.now().isoformat()
            if _start_time:
                dur = int(time.time() - _start_time)
                stats["sessions"][-1]["duration"] = dur
                stats["total_uptime"] = stats.get("total_uptime", 0) + dur
        save_stats(stats)
        log("Server stopped")
        _proc = None
        _start_time = None
        return True, "Сервер остановлен"

# ── фоновый рекордер ──────────────────────────────────────────────────────────
def _recorder():
    while True:
        time.sleep(30)
        if not server_running():
            continue
        stats = load_stats()
        now = datetime.now()

        stats.setdefault("hourly", [])
        hour_str = now.strftime("%Y-%m-%dT%H")
        if not stats["hourly"] or stats["hourly"][-1]["ts"][:13] != hour_str:
            stats["hourly"].append({"ts": now.isoformat(timespec="minutes"), "cnt": 0})
        stats["hourly"] = stats["hourly"][-336:]

        sys = get_system_stats()
        if sys:
            stats.setdefault("resource_usage", []).append({
                "ts":     now.isoformat(timespec="minutes"),
                "cpu":    sys["cpu"],
                "memory": sys["memory_percent"],
                "disk":   sys["disk_percent"],
            })
            stats["resource_usage"] = stats["resource_usage"][-336:]

        save_stats(stats)

threading.Thread(target=_recorder, daemon=True).start()

# ── системные ресурсы ─────────────────────────────────────────────────────────
def get_system_stats():
    try:
        mem  = psutil.virtual_memory()
        disk = psutil.disk_usage(SERVER_DIR)
        return {
            "cpu":            psutil.cpu_percent(interval=0.5),
            "memory_percent": mem.percent,
            "memory_used":    mem.used,
            "memory_total":   mem.total,
            "disk_percent":   disk.percent,
            "disk_used":      disk.used,
            "disk_total":     disk.total,
        }
    except:
        return None

# ── API ───────────────────────────────────────────────────────────────────────
@app.route("/api/status")
def api_status():
    running = server_running()
    uptime  = int(time.time() - _start_time) if running and _start_time else 0
    stats   = load_stats()
    info    = get_server_info() if running else None
    return jsonify({
        "running":    running,
        "uptime":     uptime,
        "info":       info,
        "system":     get_system_stats(),
        "has_binary": _find_binary() is not None,
        "crashes":    stats.get("crashes", 0),
        "total_uptime": stats.get("total_uptime", 0),
    })

@app.route("/api/start",   methods=["POST"])
def api_start():
    ok, msg = start_server(); return jsonify({"ok": ok, "msg": msg})

@app.route("/api/stop",    methods=["POST"])
def api_stop():
    ok, msg = stop_server();  return jsonify({"ok": ok, "msg": msg})

@app.route("/api/restart", methods=["POST"])
def api_restart():
    stop_server(); time.sleep(2)
    ok, msg = start_server(); return jsonify({"ok": ok, "msg": msg})

@app.route("/api/config",  methods=["GET"])
def api_config_get():
    return jsonify({"config": read_conf()})

@app.route("/api/config",  methods=["POST"])
def api_config_set():
    data = request.get_json() or {}
    config = data.get("config", {})
    if not isinstance(config, dict):
        return jsonify({"ok": False, "msg": "Неверный формат конфига"}), 400
    write_conf(config)
    log("Config updated")
    return jsonify({"ok": True})

@app.route("/api/chart/week")
def api_chart_week():
    stats = load_stats()
    now   = datetime.now()
    days  = {}
    for i in range(6, -1, -1):
        d = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        days[d] = {"date": d, "max": 0, "samples": []}
    for e in stats.get("hourly", []):
        d = e["ts"][:10]
        if d in days:
            days[d]["samples"].append(e.get("cnt", 0))
    result = []
    for d, v in sorted(days.items()):
        s = v["samples"]
        result.append({"date": d, "max": max(s) if s else 0,
                       "avg": round(sum(s)/len(s), 1) if s else 0})
    return jsonify({"chart": result})

@app.route("/api/chart/resources")
def api_chart_resources():
    stats = load_stats()
    return jsonify({"resources": stats.get("resource_usage", [])[-48:]})

@app.route("/api/sessions")
def api_sessions():
    stats   = load_stats()
    sessions = list(reversed(stats.get("sessions", [])[-30:]))
    result  = []
    for s in sessions:
        start = datetime.fromisoformat(s["start"])
        dur   = s.get("duration", int((datetime.now() - start).total_seconds()))
        result.append({
            "start":    s["start"][:16].replace("T", " "),
            "stop":     (s.get("stop") or "")[:16].replace("T", " ") or "—",
            "duration": dur,
        })
    return jsonify({"sessions": result})

@app.route("/api/log")
def api_log():
    if not os.path.exists(LOG_FILE):
        return jsonify({"log": ""})
    with open(LOG_FILE) as f:
        return jsonify({"log": "".join(f.readlines()[-200:])})

@app.route("/api/upload", methods=["POST"])
def api_upload():
    f = request.files.get("file")
    if not f:
        return jsonify({"ok": False, "msg": "Файл не выбран"})
    fname = os.path.basename(f.filename or "")
    if not fname:
        return jsonify({"ok": False, "msg": "Некорректное имя файла"}), 400
    os.makedirs(SERVER_DIR, exist_ok=True)
    if fname.endswith(".zip"):
        tmp = "/tmp/ragemp_upload.zip"
        f.save(tmp)
        try:
            with zipfile.ZipFile(tmp) as z:
                # Защита от zip slip
                for member in z.namelist():
                    dest_path = os.path.realpath(os.path.join(SERVER_DIR, member))
                    if not dest_path.startswith(os.path.realpath(SERVER_DIR)):
                        log(f"Zip slip blocked: {member}")
                        return jsonify({"ok": False, "msg": "Небезопасный архив"}), 400
                z.extractall(SERVER_DIR)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
        return jsonify({"ok": True, "msg": "Архив распакован в /server"})
    dest = os.path.join(SERVER_DIR, fname)
    f.save(dest)
    return jsonify({"ok": True, "msg": f"Файл сохранён: {fname}"})

# ── HTML ──────────────────────────────────────────────────────────────────────
HTML = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>RAGE-MP Panel</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0a0e1a;color:#e8eaf0;min-height:100vh;padding:28px 16px}
h1{font-size:1.7rem;font-weight:700;background:linear-gradient(135deg,#ff6b35,#ffa500);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:4px}
.sub{color:#6c727f;font-size:.9rem;margin-bottom:28px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px;margin-bottom:24px}
.card{background:rgba(26,30,45,.85);border:1px solid rgba(255,255,255,.06);border-radius:16px;padding:22px}
.card h2{font-size:.75rem;color:#6c727f;text-transform:uppercase;letter-spacing:.5px;margin-bottom:14px}
.stat-val{font-size:2rem;font-weight:700;color:#fff}
.stat-sub{font-size:.8rem;color:#6c727f;margin-top:2px}
.badge{display:inline-block;padding:4px 14px;border-radius:20px;font-size:.8rem;font-weight:600}
.badge.on{background:rgba(0,210,100,.15);color:#00d264}
.badge.off{background:rgba(255,61,61,.15);color:#ff3d3d}
.btn{border:none;border-radius:10px;cursor:pointer;font-size:.85rem;font-weight:600;padding:10px 20px;transition:all .2s}
.btn:hover{opacity:.85}
.btn-green{background:linear-gradient(135deg,#00d264,#00a86b);color:#fff}
.btn-red{background:linear-gradient(135deg,#ff3d3d,#c0392b);color:#fff}
.btn-orange{background:linear-gradient(135deg,#ff6b35,#ffa500);color:#fff}
.btn-row{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}
.section{background:rgba(26,30,45,.85);border:1px solid rgba(255,255,255,.06);border-radius:16px;padding:22px;margin-bottom:24px}
.section h2{font-size:.85rem;color:#6c727f;text-transform:uppercase;letter-spacing:.5px;margin-bottom:16px}
.chart-wrap{position:relative;height:180px}
table{width:100%;border-collapse:collapse;font-size:.82rem}
th{color:#6c727f;font-weight:600;padding:10px 12px;border-bottom:1px solid rgba(255,255,255,.06);text-align:left;text-transform:uppercase;font-size:.72rem}
td{padding:11px 12px;border-bottom:1px solid rgba(255,255,255,.04);color:#ccc}
tr:last-child td{border-bottom:none}
.empty{color:#6c727f;text-align:center;padding:24px}
.log-box{background:#0a0e1a;border:1px solid rgba(255,255,255,.06);border-radius:8px;padding:12px;font-family:monospace;font-size:.75rem;color:#8a9ab5;max-height:200px;overflow-y:auto;white-space:pre-wrap}
.upload-zone{border:2px dashed rgba(255,255,255,.1);border-radius:10px;padding:28px;text-align:center;color:#6c727f;cursor:pointer;transition:all .3s;margin-top:10px}
.upload-zone:hover{border-color:#ffa500}
.toast{position:fixed;bottom:24px;right:24px;background:rgba(26,30,45,.95);border:1px solid rgba(255,255,255,.1);border-radius:12px;padding:14px 24px;font-size:.85rem;display:none;z-index:100}
.toast.show{display:block}
.cfg-row{display:flex;gap:8px;align-items:center;margin-bottom:6px}
.cfg-row label{font-size:.75rem;color:#6c727f;width:130px;flex-shrink:0}
.cfg-row input{flex:1;background:#0a0e1a;border:1px solid rgba(255,255,255,.06);border-radius:6px;color:#fff;font-size:.8rem;padding:6px 10px;outline:none}
.cfg-row input:focus{border-color:#ffa500}
.res-bar{display:flex;gap:24px;flex-wrap:wrap}
.res-item .label{font-size:.7rem;color:#6c727f}
.res-item .value{font-size:1.2rem;font-weight:700}
</style>
</head>
<body>
<h1>🚗 RAGE-MP Panel</h1>
<p class="sub">Управление GTA 5 RP сервером на RAGE-MP</p>

<div class="grid">
  <div class="card">
    <h2>Статус</h2>
    <div id="statusBadge"><span class="badge off">Офлайн</span></div>
    <div class="btn-row">
      <button class="btn btn-green"  onclick="ctrl('start')">▶ Запустить</button>
      <button class="btn btn-red"    onclick="ctrl('stop')">■ Стоп</button>
      <button class="btn btn-orange" onclick="ctrl('restart')">↺ Рестарт</button>
    </div>
  </div>
  <div class="card">
    <h2>Аптайм сессии</h2>
    <div class="stat-val" id="uptimeVal">—</div>
    <div class="stat-sub" id="hostnameVal"></div>
  </div>
  <div class="card">
    <h2>Крашей</h2>
    <div class="stat-val" id="crashesVal">0</div>
    <div class="stat-sub">за всё время</div>
  </div>
  <div class="card">
    <h2>Бинарник</h2>
    <div class="stat-val" style="font-size:1rem" id="binaryVal">—</div>
    <div class="stat-sub">в /server</div>
  </div>
</div>

<div class="section">
  <h2>📊 Ресурсы системы</h2>
  <div class="res-bar">
    <div class="res-item"><div class="label">CPU</div><div class="value" id="cpuVal">—</div></div>
    <div class="res-item"><div class="label">RAM</div><div class="value" id="ramVal">—</div></div>
    <div class="res-item"><div class="label">Disk</div><div class="value" id="diskVal">—</div></div>
  </div>
</div>

<div class="grid" style="grid-template-columns:1fr 1fr">
  <div class="card">
    <h2>Онлайн за 7 дней</h2>
    <div class="chart-wrap"><canvas id="weekChart"></canvas></div>
  </div>
  <div class="card">
    <h2>CPU / RAM за 24ч</h2>
    <div class="chart-wrap"><canvas id="resChart"></canvas></div>
  </div>
</div>

<div class="section">
  <h2>📜 История сессий</h2>
  <table>
    <thead><tr><th>Запуск</th><th>Остановка</th><th>Длительность</th></tr></thead>
    <tbody id="sessBody"><tr><td colspan="3" class="empty">Загрузка...</td></tr></tbody>
  </table>
</div>

<div class="section">
  <h2>⚙️ conf.json</h2>
  <div id="cfgGrid"></div>
  <div class="btn-row"><button class="btn btn-orange" onclick="saveConfig()">💾 Сохранить</button></div>
</div>

<div class="section">
  <h2>📤 Загрузить файлы сервера</h2>
  <p style="font-size:.82rem;color:#6c727f;margin-bottom:8px">ZIP-архив или отдельный файл → /server</p>
  <div class="upload-zone" onclick="document.getElementById('fi').click()">📁 Нажмите или перетащите файл</div>
  <input type="file" id="fi" style="display:none" onchange="uploadFile(this)">
</div>

<div class="section">
  <h2>📋 Лог</h2>
  <div class="log-box" id="logBox">Загрузка...</div>
</div>

<div class="toast" id="toast"></div>

<script>
function fmt(s){
  const h=Math.floor(s/3600),m=Math.floor((s%3600)/60),sec=s%60;
  if(h)return h+'ч '+m+'м'; if(m)return m+'м '+sec+'с'; return sec+'с';
}
function toast(msg,ok=true){
  const t=document.getElementById('toast');
  t.textContent=msg; t.style.borderColor=ok?'#00d264':'#ff3d3d';
  t.className='toast show'; setTimeout(()=>t.className='toast',3000);
}

let weekChart, resChart;
function initCharts(){
  const base=(id,label,color)=>new Chart(document.getElementById(id),{
    type:'line',
    data:{labels:[],datasets:[{label,data:[],borderColor:color,backgroundColor:color+'22',borderWidth:2,pointRadius:2,fill:true,tension:.3}]},
    options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},
      scales:{x:{ticks:{color:'#6c727f',font:{size:9}},grid:{color:'rgba(255,255,255,.04)'}},
              y:{ticks:{color:'#6c727f',font:{size:9}},grid:{color:'rgba(255,255,255,.04)'},beginAtZero:true}}}
  });
  weekChart=base('weekChart','Макс','#ff6b35');
  resChart =base('resChart','CPU %','#3D6BFF');
}

let cfgData={};

async function fetchStatus(){
  const d=await fetch('/api/status').then(r=>r.json());
  document.getElementById('statusBadge').innerHTML=
    d.running?'<span class="badge on">● Онлайн</span>':'<span class="badge off">○ Офлайн</span>';
  document.getElementById('uptimeVal').textContent=d.running?fmt(d.uptime):'—';
  document.getElementById('hostnameVal').textContent=d.info?d.info.hostname:'';
  document.getElementById('crashesVal').textContent=d.crashes||0;
  document.getElementById('binaryVal').textContent=d.has_binary?'✅ Найден':'❌ Не найден';
  if(d.system){
    document.getElementById('cpuVal').textContent=Math.round(d.system.cpu)+'%';
    document.getElementById('ramVal').textContent=Math.round(d.system.memory_percent)+'%';
    document.getElementById('diskVal').textContent=Math.round(d.system.disk_percent)+'%';
  }
}

async function fetchCharts(){
  const [wd,rd]=await Promise.all([
    fetch('/api/chart/week').then(r=>r.json()),
    fetch('/api/chart/resources').then(r=>r.json()),
  ]);
  weekChart.data.labels=wd.chart.map(d=>d.date.slice(5));
  weekChart.data.datasets[0].data=wd.chart.map(d=>d.max);
  weekChart.update();
  resChart.data.labels=rd.resources.map(d=>d.ts.slice(11,16));
  resChart.data.datasets[0].data=rd.resources.map(d=>d.cpu);
  resChart.update();
}

async function fetchSessions(){
  const d=await fetch('/api/sessions').then(r=>r.json());
  const body=document.getElementById('sessBody');
  if(!d.sessions.length){body.innerHTML='<tr><td colspan="3" class="empty">Сессий нет</td></tr>';return;}
  body.innerHTML=d.sessions.map(s=>`<tr><td>${s.start}</td><td>${s.stop}</td><td>${fmt(s.duration)}</td></tr>`).join('');
}

async function fetchConfig(){
  const d=await fetch('/api/config').then(r=>r.json());
  cfgData=d.config||{};
  const grid=document.getElementById('cfgGrid');
  if(!Object.keys(cfgData).length){grid.innerHTML='<span style="color:#6c727f;font-size:.82rem">conf.json не найден</span>';return;}
  grid.innerHTML=Object.keys(cfgData).map(k=>`
    <div class="cfg-row">
      <label>${k}</label>
      <input id="cfg_${k}" value="${typeof cfgData[k]==='object'?JSON.stringify(cfgData[k]):cfgData[k]||''}">
    </div>`).join('');
}

async function saveConfig(){
  const updated={};
  Object.keys(cfgData).forEach(k=>{
    const v=document.getElementById('cfg_'+k)?.value||'';
    try{updated[k]=JSON.parse(v);}catch{updated[k]=v;}
  });
  const d=await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({config:updated})}).then(r=>r.json());
  toast(d.ok?'Сохранено':'Ошибка',d.ok);
}

async function fetchLog(){
  const d=await fetch('/api/log').then(r=>r.json());
  const box=document.getElementById('logBox');
  box.textContent=d.log||'Лог пуст';
  box.scrollTop=box.scrollHeight;
}

async function ctrl(a){
  const d=await fetch('/api/'+a,{method:'POST'}).then(r=>r.json());
  toast(d.msg,d.ok); setTimeout(fetchAll,1500);
}

async function uploadFile(input){
  const file=input.files[0];if(!file)return;
  toast('Загрузка...');
  const fd=new FormData();fd.append('file',file);
  const d=await fetch('/api/upload',{method:'POST',body:fd}).then(r=>r.json());
  toast(d.msg,d.ok); input.value=''; fetchConfig();
}

const zone=document.querySelector('.upload-zone');
zone.addEventListener('dragover',e=>{e.preventDefault();zone.style.borderColor='#ffa500';});
zone.addEventListener('dragleave',()=>{zone.style.borderColor='rgba(255,255,255,.1)';});
zone.addEventListener('drop',e=>{
  e.preventDefault();zone.style.borderColor='rgba(255,255,255,.1)';
  const file=e.dataTransfer.files[0];if(!file)return;
  const fd=new FormData();fd.append('file',file);
  toast('Загрузка...');
  fetch('/api/upload',{method:'POST',body:fd}).then(r=>r.json()).then(d=>toast(d.msg,d.ok));
});

function fetchAll(){fetchStatus();fetchCharts();fetchSessions();fetchLog();}

initCharts();fetchAll();fetchConfig();
setInterval(fetchStatus,5000);
setInterval(fetchCharts,60000);
setInterval(fetchSessions,30000);
setInterval(fetchLog,15000);
</script>
</body>
</html>"""

@app.route("/")
def index():
    return render_template_string(HTML)

if __name__ == "__main__":
    os.makedirs(SERVER_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    app.run(host="0.0.0.0", port=5656, threaded=True)
