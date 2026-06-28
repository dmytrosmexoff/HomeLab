from flask import Flask, request, jsonify, render_template_string, abort
import json, os, subprocess, time, threading, psutil, socket, struct
from datetime import datetime
import mcrcon

app = Flask(__name__)
SERVER_DIR  = os.environ.get("SERVER_DIR", "/server")
DATA_DIR    = os.environ.get("DATA_DIR",   "/data")
STATS_FILE  = os.path.join(DATA_DIR, "stats.json")
RCON_PASS   = os.environ.get("RCON_PASSWORD", "mcrcon123")
RCON_PORT   = int(os.environ.get("RCON_PORT", 25575))
JAVA_OPTS   = os.environ.get("JAVA_OPTS", "-Xmx2G -Xms512M")

_proc = None; _start_time = None; _lock = threading.Lock()

def load_stats():
    try:
        if os.path.exists(STATS_FILE):
            with open(STATS_FILE) as f: return json.load(f)
    except: pass
    return {"timeline":[],"daily_peak":{}}

def save_stats(s):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(STATS_FILE,"w") as f: json.dump(s,f,indent=2)

def log_panel(msg):
    os.makedirs(DATA_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(os.path.join(DATA_DIR,"panel.log"),"a") as f:
        f.write(f"[{ts}] {msg}\n")

def mc_query(timeout=2.0):
    """Minecraft server list ping protocol"""
    try:
        s = socket.create_connection(("127.0.0.1", 25565), timeout=timeout)
        # Handshake
        host = b"\x09\x00\x00\x00\x00\x00\x00\x63\xdd\x01"
        s.sendall(host + b"\x01\x00")
        data = b""
        while len(data) < 5:
            chunk = s.recv(1024)
            if not chunk: break
            data += chunk
        s.close()
        if data:
            # Parse player count from JSON response
            start = data.find(b"{")
            if start >= 0:
                try:
                    js = json.loads(data[start:].decode("utf-8", "ignore"))
                    return {
                        "players": js["players"]["online"],
                        "max": js["players"]["max"],
                        "version": js["version"]["name"],
                        "description": str(js.get("description",""))
                    }
                except: pass
        return None
    except: return None

def mc_rcon(cmd):
    """Send command via RCON"""
    try:
        with mcrcon.MCRcon("127.0.0.1", RCON_PASS, port=RCON_PORT) as r:
            return r.command(cmd)
    except Exception as e:
        return f"RCON Error: {e}"

def get_metrics():
    global _proc
    cpu = psutil.cpu_percent(interval=0.1)
    ram = psutil.virtual_memory()
    cp = rp = 0
    if _proc and _proc.poll() is None:
        try:
            p = psutil.Process(_proc.pid)
            cp = p.cpu_percent(interval=0.1)
            rp = round(p.memory_info().rss/ram.total*100,1)
        except: pass
    return {"cpu_total":cpu,"cpu_proc":cp,"ram_total":ram.percent,"ram_proc":rp}

def _recorder():
    while True:
        time.sleep(300)
        info = mc_query()
        if info:
            stats = load_stats()
            ts = datetime.now().strftime("%H:%M")
            day = datetime.now().strftime("%Y-%m-%d")
            stats.setdefault("timeline",[]).append({"t":ts,"v":info["players"]})
            if len(stats["timeline"])>288: stats["timeline"]=stats["timeline"][-288:]
            dp = stats.setdefault("daily_peak",{})
            dp[day] = max(dp.get(day,0), info["players"])
            save_stats(stats)

threading.Thread(target=_recorder, daemon=True).start()

# ─── HTML ────────────────────────────────────────────────────────────────────
PAGE = """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Minecraft Panel</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0f1115;color:#eee;min-height:100vh}
.topbar{background:#1a1d24;border-bottom:1px solid #2a2d36;padding:14px 24px;display:flex;align-items:center;gap:20px}
.topbar h1{font-size:1.4rem;font-weight:700;background:linear-gradient(90deg,#56d364,#26a641);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.tabs{display:flex;gap:2px;margin-left:auto}
.tab{padding:8px 18px;border-radius:8px;cursor:pointer;font-size:.85rem;font-weight:600;color:#6c727f;border:none;background:none;transition:all .2s}
.tab.active{background:#2a2d36;color:#eee}
.tab:hover{color:#eee}
.page{display:none;padding:24px;max-width:1100px;margin:0 auto}
.page.active{display:block}
.card{background:#1a1d24;border:1px solid #2a2d36;border-radius:16px;padding:22px;margin-bottom:20px}
.card h2{font-size:.78rem;font-weight:600;color:#6c727f;text-transform:uppercase;letter-spacing:.6px;margin-bottom:14px}
.stat-val{font-size:2rem;font-weight:700;color:#fff}
.stat-sub{font-size:.8rem;color:#6c727f;margin-top:2px}
.badge{display:inline-block;padding:4px 12px;border-radius:20px;font-size:.8rem;font-weight:600}
.badge.on{background:rgba(86,211,100,.15);color:#56d364}
.badge.off{background:rgba(255,61,61,.15);color:#ff3d3d}
.btn{border:none;border-radius:8px;cursor:pointer;font-size:.85rem;font-weight:600;padding:9px 18px;transition:opacity .2s}
.btn:hover{opacity:.8}
.btn-green{background:linear-gradient(90deg,#56d364,#26a641);color:#fff}
.btn-red{background:linear-gradient(90deg,#ff3d3d,#c0392b);color:#fff}
.btn-blue{background:linear-gradient(90deg,#3D6BFF,#7b2dff);color:#fff}
.btn-gray{background:#2a2d36;color:#ccc}
.btn-sm{padding:5px 12px;font-size:.78rem}
.grid{display:grid;gap:16px}
.g2{grid-template-columns:1fr 1fr}
.g4{grid-template-columns:repeat(4,1fr)}
table{width:100%;border-collapse:collapse;font-size:.82rem}
th{color:#6c727f;font-weight:600;padding:10px 12px;border-bottom:1px solid #2a2d36;text-align:left;text-transform:uppercase;font-size:.72rem;letter-spacing:.4px}
td{padding:11px 12px;border-bottom:1px solid #1e2128;color:#ccc}
.empty{color:#6c727f;text-align:center;padding:24px}
.log-box{background:#0f1115;border:1px solid #2a2d36;border-radius:8px;padding:12px;font-family:monospace;font-size:.75rem;color:#8a9ab5;height:260px;overflow-y:auto;white-space:pre-wrap;word-break:break-all}
.console-out{background:#0a0c10;border:1px solid #2a2d36;border-radius:8px;padding:10px;font-family:monospace;font-size:.75rem;color:#56d364;height:200px;overflow-y:auto;white-space:pre-wrap;margin-bottom:8px}
.console-row{display:flex;gap:8px}
.console-row input,.editor-area{background:#0f1115;border:1px solid #2a2d36;border-radius:6px;color:#fff;font-size:.82rem;padding:8px 12px;outline:none}
.console-row input{flex:1}
.console-row input:focus{border-color:#56d364}
.bar-wrap{margin-bottom:14px}
.bar-label{display:flex;justify-content:space-between;font-size:.75rem;color:#6c727f;margin-bottom:5px}
.bar-track{position:relative;height:18px;background:rgba(0,0,0,.5);border-radius:9px;overflow:hidden}
.bar-total{position:absolute;left:0;top:0;height:100%;background:rgba(255,255,255,.07);border-radius:9px;transition:width .6s}
.bar-proc{position:absolute;left:0;top:0;height:100%;border-radius:9px;transition:width .6s}
.bar-peak{position:absolute;top:0;width:3px;height:100%;background:rgba(255,211,56,.9);border-radius:2px;transition:left .6s}
.bar-cpu .bar-proc{background:linear-gradient(90deg,#56d364,#26a641)}
.bar-ram .bar-proc{background:linear-gradient(90deg,#26a641,#3D6BFF)}
.toast{position:fixed;bottom:24px;right:24px;background:#1a1d24;border:1px solid #2a2d36;border-radius:10px;padding:12px 20px;font-size:.85rem;display:none;z-index:100;color:#eee}
/* file manager */
.fm-path{background:#0f1115;border:1px solid #2a2d36;border-radius:8px;padding:8px 14px;font-family:monospace;font-size:.8rem;color:#6c727f;margin-bottom:12px}
.fm-item{display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:8px;cursor:pointer;font-size:.82rem}
.fm-item:hover{background:#1e2128}
.fm-icon{font-size:1rem;width:20px;text-align:center}
.fm-name{flex:1;color:#ccc}
.editor-area{width:100%;height:400px;resize:vertical;font-family:monospace;font-size:.78rem;display:block}
canvas{width:100%!important}
@media(max-width:640px){.g2,.g4{grid-template-columns:1fr}}
</style></head><body>

<div class="topbar">
  <h1>⛏️ Minecraft Panel</h1>
  <div class="tabs">
    <button class="tab active" onclick="showTab('main',this)">Главная</button>
    <button class="tab" onclick="showTab('console',this)">Консоль</button>
    <button class="tab" onclick="showTab('files',this)">Файлы</button>
  </div>
</div>

<!-- TAB: MAIN -->
<div class="page active" id="tab_main">
  <div class="grid g4" style="margin-bottom:16px">
    <div class="card"><h2>Статус</h2><div id="badge_status"><span class="badge off">Офлайн</span></div></div>
    <div class="card"><h2>Игроки</h2><div class="stat-val" id="stat_players">—</div><div class="stat-sub" id="stat_max">/ — слотов</div></div>
    <div class="card"><h2>Пик сегодня</h2><div class="stat-val" id="stat_peak">—</div><div class="stat-sub">игроков</div></div>
    <div class="card"><h2>Аптайм</h2><div class="stat-val" id="stat_uptime">—</div><div class="stat-sub" id="stat_ver">Vanilla</div></div>
  </div>

  <div class="card">
    <h2>Управление сервером</h2>
    <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center">
      <button class="btn btn-green" onclick="srv('start')">▶ Старт</button>
      <button class="btn btn-red"   onclick="srv('stop')">■ Стоп</button>
      <button class="btn btn-blue"  onclick="srv('restart')">↺ Рестарт</button>
      <span style="margin-left:8px;font-size:.8rem;color:#6c727f">JAVA_OPTS: <code id="java_opts" style="color:#56d364"></code></span>
    </div>
  </div>

  <div class="grid g2">
    <div class="card">
      <h2>Мониторинг CPU</h2>
      <div class="bar-wrap bar-cpu">
        <div class="bar-label"><span>CPU</span><span id="cpu_vals">—</span></div>
        <div class="bar-track">
          <div class="bar-total" id="cpu_total_bar"></div>
          <div class="bar-proc"  id="cpu_proc_bar"></div>
          <div class="bar-peak"  id="cpu_peak_bar"></div>
        </div>
        <div style="margin-top:6px;font-size:.7rem;color:#6c727f;display:flex;gap:14px">
          <span>⬛ Общая</span><span style="color:#56d364">🟩 Сервер</span><span style="color:#ffd338">| Пик</span>
        </div>
      </div>
      <div class="bar-wrap bar-ram">
        <div class="bar-label"><span>RAM</span><span id="ram_vals">—</span></div>
        <div class="bar-track">
          <div class="bar-total" id="ram_total_bar"></div>
          <div class="bar-proc"  id="ram_proc_bar"></div>
          <div class="bar-peak"  id="ram_peak_bar"></div>
        </div>
      </div>
    </div>
    <div class="card">
      <h2>Онлайн игроки</h2>
      <table><thead><tr><th>#</th><th>Ник</th><th>Онлайн</th><th>Пинг</th></tr></thead>
      <tbody id="players_body"><tr><td colspan="4" class="empty">Нет игроков</td></tr></tbody></table>
    </div>
  </div>

  <div class="grid g2">
    <div class="card"><h2>Онлайн (5-мин шаги)</h2><canvas id="chart_tl" height="120"></canvas></div>
    <div class="card"><h2>Пик по дням</h2><canvas id="chart_dp" height="120"></canvas></div>
  </div>

  <div class="card"><h2>Лог сервера</h2><div class="log-box" id="log_box">Загрузка...</div></div>
</div>

<!-- TAB: CONSOLE -->
<div class="page" id="tab_console">
  <div class="card">
    <h2>RCON Веб-консоль</h2>
    <div class="console-out" id="rcon_out">Minecraft RCON готов. Введите команду...\n</div>
    <div class="console-row">
      <input id="rcon_cmd" placeholder="say Hello! | op PlayerName | list" onkeydown="if(event.key==='Enter')sendRcon()">
      <button class="btn btn-green" onclick="sendRcon()">Отправить</button>
    </div>
    <div style="margin-top:12px;display:flex;gap:8px;flex-wrap:wrap">
      <button class="btn btn-gray btn-sm" onclick="quickCmd('list')">list</button>
      <button class="btn btn-gray btn-sm" onclick="quickCmd('time set day')">день</button>
      <button class="btn btn-gray btn-sm" onclick="quickCmd('weather clear')">ясно</button>
      <button class="btn btn-gray btn-sm" onclick="quickCmd('difficulty peaceful')">мирно</button>
      <button class="btn btn-gray btn-sm" onclick="quickCmd('save-all')">сохранить</button>
    </div>
  </div>
  <div class="card"><h2>Лог сервера</h2><div class="log-box" id="console_log">Загрузка...</div></div>
</div>

<!-- TAB: FILES -->
<div class="page" id="tab_files">
  <div class="card">
    <h2>Файловый менеджер</h2>
    <div class="fm-path" id="fm_path">/server</div>
    <div id="fm_list">Загрузка...</div>
  </div>
  <div class="card" id="editor_card" style="display:none">
    <h2 id="editor_title">Редактор</h2>
    <textarea class="editor-area" id="editor_area"></textarea>
    <div style="display:flex;gap:8px;margin-top:12px">
      <button class="btn btn-green" onclick="saveFile()">💾 Сохранить</button>
      <button class="btn btn-gray"  onclick="closeEditor()">✕ Закрыть</button>
    </div>
  </div>
</div>

<div class="toast" id="toast"></div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js"></script>
<script>
let cpuPeak=0,ramPeak=0,tlC=null,dpC=null,fmPath='/server',editPath='';

function showTab(id,btn){
  document.querySelectorAll('.page').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  document.getElementById('tab_'+id).classList.add('active');
  btn.classList.add('active');
  if(id==='files') loadFm(fmPath);
}

function toast(msg,ok=true){
  const t=document.getElementById('toast');t.textContent=msg;
  t.style.borderColor=ok?'#56d364':'#ff3d3d';t.style.display='block';
  setTimeout(()=>t.style.display='none',2500);
}

async function srv(a){
  const r=await fetch('/api/server/'+a,{method:'POST'});
  const d=await r.json(); toast(d.message,d.ok);
}

async function sendRcon(){
  const inp=document.getElementById('rcon_cmd'),out=document.getElementById('rcon_out');
  const cmd=inp.value.trim();if(!cmd)return;
  out.textContent+=`> ${cmd}\n`;inp.value='';
  const r=await fetch('/api/rcon',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cmd})});
  const d=await r.json();
  out.textContent+=d.result+'\n';out.scrollTop=out.scrollHeight;
}

function quickCmd(c){document.getElementById('rcon_cmd').value=c;sendRcon();}

function initChart(id,color){
  return new Chart(document.getElementById(id).getContext('2d'),{type:'line',
    data:{labels:[],datasets:[{data:[],borderColor:color,backgroundColor:color+'22',fill:true,tension:.4,pointRadius:2}]},
    options:{responsive:true,plugins:{legend:{display:false}},
      scales:{x:{ticks:{color:'#6c727f',maxTicksLimit:8}},y:{ticks:{color:'#6c727f'},beginAtZero:true,grid:{color:'#1e2128'}}}}});
}

async function poll(){
  try{
    const r=await fetch('/api/status');const d=await r.json();
    document.getElementById('badge_status').innerHTML=d.running?'<span class="badge on">Онлайн</span>':'<span class="badge off">Офлайн</span>';
    document.getElementById('stat_players').textContent=d.info?d.info.players:'—';
    document.getElementById('stat_max').textContent=d.info?'/ '+d.info.max+' слотов':'/ — слотов';
    document.getElementById('stat_peak').textContent=d.today_peak;
    document.getElementById('stat_uptime').textContent=d.uptime||'—';
    document.getElementById('stat_ver').textContent=d.info?d.info.version:'Vanilla';
    document.getElementById('java_opts').textContent=d.java_opts||'';
    const m=d.metrics;
    if(m.cpu_proc>cpuPeak)cpuPeak=m.cpu_proc;
    if(m.ram_proc>ramPeak)ramPeak=m.ram_proc;
    document.getElementById('cpu_vals').textContent=`Сервер: ${m.cpu_proc}% / Всего: ${m.cpu_total}%`;
    document.getElementById('ram_vals').textContent=`Сервер: ${m.ram_proc}% / Всего: ${m.ram_total}%`;
    ['cpu','ram'].forEach(t=>{
      document.getElementById(t+'_total_bar').style.width=(t=='cpu'?m.cpu_total:m.ram_total)+'%';
      document.getElementById(t+'_proc_bar').style.width=Math.min(t=='cpu'?m.cpu_proc:m.ram_proc,100)+'%';
      document.getElementById(t+'_peak_bar').style.left=Math.min(t=='cpu'?cpuPeak:ramPeak,99)+'%';
    });
    const st=d.stats;
    if(st.timeline){tlC.data.labels=st.timeline.map(x=>x.t);tlC.data.datasets[0].data=st.timeline.map(x=>x.v);tlC.update('none');}
    if(st.daily_peak){const days=Object.keys(st.daily_peak).slice(-14);dpC.data.labels=days.map(d=>d.slice(5));dpC.data.datasets[0].data=days.map(d=>st.daily_peak[d]);dpC.update('none');}
    // players
    if(d.players&&d.players.length){
      document.getElementById('players_body').innerHTML=d.players.map((p,i)=>`<tr><td>${i+1}</td><td>${p.name}</td><td>—</td><td>${p.ping||'—'}</td></tr>`).join('');
    } else {
      document.getElementById('players_body').innerHTML='<tr><td colspan="4" class="empty">Нет игроков онлайн</td></tr>';
    }
    // log
    const lr=await fetch('/api/log');const lt=await lr.text();
    ['log_box','console_log'].forEach(id=>{const el=document.getElementById(id);el.textContent=lt;el.scrollTop=el.scrollHeight;});
  }catch(e){}
  setTimeout(poll,5000);
}

// File Manager
async function loadFm(path){
  fmPath=path;
  document.getElementById('fm_path').textContent=path;
  const r=await fetch('/api/files?path='+encodeURIComponent(path));
  const d=await r.json();
  if(d.error){document.getElementById('fm_list').innerHTML='<div class="empty">'+d.error+'</div>';return;}
  let html='';
  if(path!=='/server')html+=`<div class="fm-item" onclick="loadFm('${d.parent||'/server'}')"><span class="fm-icon">📁</span><span class="fm-name">..</span></div>`;
  d.items.forEach(item=>{
    if(item.type==='dir'){
      html+=`<div class="fm-item" onclick="loadFm('${item.path}')"><span class="fm-icon">📁</span><span class="fm-name">${item.name}</span></div>`;
    } else {
      const editable=['cfg','json','txt','log','yml','yaml','properties','sh','conf'].some(e=>item.name.endsWith('.'+e));
      html+=`<div class="fm-item"><span class="fm-icon">📄</span><span class="fm-name">${item.name}</span>`;
      if(editable)html+=`<button class="btn btn-gray btn-sm" onclick="openEditor('${item.path}','${item.name}')">✏️</button>`;
      html+=`</div>`;
    }
  });
  document.getElementById('fm_list').innerHTML=html||'<div class="empty">Папка пуста</div>';
}

async function openEditor(path,name){
  const r=await fetch('/api/file?path='+encodeURIComponent(path));
  const d=await r.json();
  if(d.error){toast(d.error,false);return;}
  editPath=path;
  document.getElementById('editor_title').textContent='✏️ '+name;
  document.getElementById('editor_area').value=d.content;
  document.getElementById('editor_card').style.display='block';
  document.getElementById('editor_card').scrollIntoView({behavior:'smooth'});
}

async function saveFile(){
  const content=document.getElementById('editor_area').value;
  const r=await fetch('/api/file',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:editPath,content})});
  const d=await r.json();
  toast(d.message,d.ok);
}

function closeEditor(){
  document.getElementById('editor_card').style.display='none';
  editPath='';
}

tlC=initChart('chart_tl','#56d364');
dpC=initChart('chart_dp','#26a641');
poll();
loadFm('/server');
</script></body></html>"""

@app.route("/")
def index(): return PAGE

@app.route("/api/status")
def status():
    global _proc, _start_time
    running = _proc is not None and _proc.poll() is None
    info = mc_query() if running else None
    stats = load_stats()
    today = datetime.now().strftime("%Y-%m-%d")
    today_peak = stats.get("daily_peak", {}).get(today, 0)
    uptime = ""
    if running and _start_time:
        sec = int(time.time()-_start_time); h,m=divmod(sec,3600); m,s=divmod(m,60)
        uptime = f"{h:02d}:{m:02d}:{s:02d}"
    # Get player list via RCON
    players = []
    if running:
        try:
            out = mc_rcon("list")
            # Parse: "There are X of a max of Y players online: name1, name2"
            if ":" in out:
                names_part = out.split(":")[-1].strip()
                if names_part:
                    players = [{"name": n.strip(), "ping": "—"} for n in names_part.split(",") if n.strip()]
        except: pass
    return jsonify({"running":running,"info":info,"players":players,
                    "today_peak":today_peak,"uptime":uptime,"java_opts":JAVA_OPTS,
                    "metrics":get_metrics(),"stats":stats})

@app.route("/api/server/<action>", methods=["POST"])
def srv_action(action):
    global _proc, _start_time
    jar = None
    for f in os.listdir(SERVER_DIR) if os.path.isdir(SERVER_DIR) else []:
        if f.endswith(".jar"):
            jar = os.path.join(SERVER_DIR, f); break
    with _lock:
        if action == "start":
            if _proc and _proc.poll() is None:
                return jsonify({"ok":False,"message":"Сервер уже запущен"})
            if not jar:
                return jsonify({"ok":False,"message":"server.jar не найден в /server. Загрузите Minecraft server.jar"})
            # Ensure eula.txt
            eula = os.path.join(SERVER_DIR, "eula.txt")
            if not os.path.exists(eula):
                with open(eula,"w") as f: f.write("eula=true\n")
            # Ensure server.properties with RCON
            props = os.path.join(SERVER_DIR, "server.properties")
            if not os.path.exists(props):
                with open(props,"w") as f:
                    f.write(f"enable-rcon=true\nrcon.password={RCON_PASS}\nrcon.port={RCON_PORT}\nserver-port=25565\n")
            cmd = ["java"] + JAVA_OPTS.split() + ["-jar", jar, "nogui"]
            _proc = subprocess.Popen(cmd, cwd=SERVER_DIR,
                                     stdout=open(os.path.join(DATA_DIR,"server.log"),"a"),
                                     stderr=subprocess.STDOUT)
            _start_time = time.time(); log_panel("Сервер запущен")
            return jsonify({"ok":True,"message":"Сервер запускается..."})
        elif action == "stop":
            if not _proc or _proc.poll() is not None:
                return jsonify({"ok":False,"message":"Сервер не запущен"})
            try: mc_rcon("stop")
            except: pass
            try: _proc.wait(timeout=30)
            except: _proc.kill()
            log_panel("Сервер остановлен")
            return jsonify({"ok":True,"message":"Сервер остановлен"})
        elif action == "restart":
            if _proc and _proc.poll() is None:
                try: mc_rcon("stop")
                except: pass
                try: _proc.wait(timeout=30)
                except: _proc.kill()
            if jar:
                eula = os.path.join(SERVER_DIR, "eula.txt")
                if not os.path.exists(eula):
                    with open(eula,"w") as f: f.write("eula=true\n")
                cmd = ["java"] + JAVA_OPTS.split() + ["-jar", jar, "nogui"]
                _proc = subprocess.Popen(cmd, cwd=SERVER_DIR,
                                         stdout=open(os.path.join(DATA_DIR,"server.log"),"a"),
                                         stderr=subprocess.STDOUT)
                _start_time = time.time()
            log_panel("Рестарт")
            return jsonify({"ok":True,"message":"Рестарт..."})
    return jsonify({"ok":False,"message":"Неизвестное действие"})

@app.route("/api/rcon", methods=["POST"])
def rcon_api():
    data = request.get_json()
    cmd = data.get("cmd","").strip()
    if not cmd: return jsonify({"result":"Пустая команда"})
    result = mc_rcon(cmd)
    log_panel(f"RCON: {cmd} -> {result}")
    return jsonify({"result": result or "[OK] Команда выполнена"})

@app.route("/api/log")
def get_log():
    p = os.path.join(DATA_DIR,"server.log")
    if not os.path.exists(p): return "Лог пуст\n"
    with open(p) as f: lines=f.readlines()
    return "".join(lines[-300:])

@app.route("/api/files")
def list_files():
    path = request.args.get("path", SERVER_DIR)
    # Security: must stay within SERVER_DIR
    real = os.path.realpath(path)
    if not real.startswith(os.path.realpath(SERVER_DIR)):
        return jsonify({"error":"Доступ запрещён"})
    if not os.path.isdir(real):
        return jsonify({"error":"Не директория"})
    items = []
    try:
        for name in sorted(os.listdir(real)):
            full = os.path.join(real, name)
            items.append({"name":name,"path":full,"type":"dir" if os.path.isdir(full) else "file"})
    except Exception as e:
        return jsonify({"error":str(e)})
    parent = os.path.dirname(real) if real != os.path.realpath(SERVER_DIR) else None
    return jsonify({"items":items,"parent":parent})

@app.route("/api/file", methods=["GET","POST"])
def file_api():
    if request.method == "GET":
        path = request.args.get("path","")
        real = os.path.realpath(path)
        if not real.startswith(os.path.realpath(SERVER_DIR)):
            return jsonify({"error":"Доступ запрещён"})
        try:
            with open(real,"r",errors="replace") as f:
                return jsonify({"content":f.read()})
        except Exception as e:
            return jsonify({"error":str(e)})
    else:
        data = request.get_json()
        path = data.get("path",""); content = data.get("content","")
        real = os.path.realpath(path)
        if not real.startswith(os.path.realpath(SERVER_DIR)):
            return jsonify({"ok":False,"message":"Доступ запрещён"})
        try:
            with open(real,"w") as f: f.write(content)
            return jsonify({"ok":True,"message":"Файл сохранён"})
        except Exception as e:
            return jsonify({"ok":False,"message":str(e)})

if __name__ == "__main__":
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(SERVER_DIR, exist_ok=True)
    app.run(host="0.0.0.0", port=5770, debug=False)
